"""
storage.py — SQLAlchemy models dan session factory.
Semua akses database WAJIB melalui session dari get_session().
DILARANG menulis raw SQL string.
"""
import time
from datetime import datetime, timezone
from typing import Generator
from contextlib import contextmanager

from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text,
    create_engine, Index, text, event
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, Mapped, mapped_column

from src.utils.logger import logger


DATABASE_URL = "sqlite:///data/trading.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Diperlukan untuk SQLite + threading
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Set SQLite pragmas saat koneksi baru dibuat."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class OHLCVCandle(Base):
    """Base class untuk semua tabel OHLCV. Jangan instansiasi langsung."""
    __abstract__ = True
    __allow_unmapped__ = True  # Allow legacy style annotations

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)


class OHLCVCandle15m(OHLCVCandle):
    __tablename__ = "ohlcv_15m"
    __table_args__ = (
        Index("ix_ohlcv_15m_symbol_timestamp", "symbol", "timestamp", unique=True),
    )


class OHLCVCandleH1(OHLCVCandle):
    __tablename__ = "ohlcv_h1"
    __table_args__ = (
        Index("ix_ohlcv_h1_symbol_timestamp", "symbol", "timestamp", unique=True),
    )


class OHLCVCandleH4(OHLCVCandle):
    __tablename__ = "ohlcv_h4"
    __table_args__ = (
        Index("ix_ohlcv_h4_symbol_timestamp", "symbol", "timestamp", unique=True),
    )


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(5), nullable=False)           # 'LONG' atau 'SHORT'
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    sl_price: Mapped[float] = mapped_column(Float, nullable=False)
    tp_price: Mapped[float] = mapped_column(Float, nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)             # Quantity dalam kontrak
    leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # 'OPEN', 'CLOSED', 'PENDING_ENTRY', 'EXPIRED'
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)               # Diisi saat CLOSED
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    close_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)   # 'TP', 'SL', 'MANUAL', 'EXPIRED', 'RECONCILED', 'EMERGENCY_CLOSE_SL_FAIL', 'MODE_SWITCH'

    # ── Live mode columns (nullable, hanya terisi di EXECUTION_MODE='live') ──
    execution_mode: Mapped[str | None] = mapped_column(String(10), nullable=True, default="paper")  # 'paper' atau 'live'
    exchange_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Binance entry order ID
    sl_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)       # Binance SL order ID
    tp_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)       # Binance TP order ID
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)           # Actual fill price saat SL/TP hit


class TradeLog(Base):
    __tablename__ = "trade_logs"
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    level: Mapped[str] = mapped_column(String(10), nullable=False)         # 'INFO', 'WARNING', 'ERROR'
    source: Mapped[str] = mapped_column(String(50), nullable=False)        # Nama agent yang log
    message: Mapped[str] = mapped_column(Text, nullable=False)
    trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)          # FK ke paper_trades jika relevan


def init_db() -> None:
    """Buat semua tabel jika belum ada. Panggil sekali saat startup."""
    import os
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized successfully.")


def migrate_db() -> None:
    """
    Migrasi skema untuk existing databases.
    Menambahkan kolom baru yang diperlukan Phase 8.

    SQLAlchemy create_all() hanya membuat tabel baru — tidak menambah kolom
    ke tabel yang sudah ada. Function ini melakukan ALTER TABLE ADD COLUMN
    secara aman (IF NOT EXISTS via try/except).
    """
    new_columns = [
        ("paper_trades", "execution_mode", "VARCHAR(10) DEFAULT 'paper'"),
        ("paper_trades", "exchange_order_id", "VARCHAR(50)"),
        ("paper_trades", "sl_order_id", "VARCHAR(50)"),
        ("paper_trades", "tp_order_id", "VARCHAR(50)"),
        ("paper_trades", "close_price", "FLOAT"),
    ]

    # Widen close_reason column to fit new reasons (EMERGENCY_CLOSE_SL_FAIL, MODE_SWITCH)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE paper_trades ALTER COLUMN close_reason TYPE VARCHAR(30)"))
            conn.commit()
            logger.info("Migration: Widened close_reason column to VARCHAR(30)")
    except Exception:
        pass  # Column already wide enough or not applicable

    with engine.connect() as conn:
        for table, column, col_type in new_columns:
            try:
                # NOTE: Raw SQL diperlukan karena SQLAlchemy ORM tidak support ALTER TABLE.
                # Nilai table/column/col_type di-hardcode di atas (bukan user input).
                conn.execute(
                    text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                    )
                )
                conn.commit()
                logger.info(f"Migration: Added column {table}.{column}")
            except Exception:
                # Kolom sudah ada — aman untuk di-ignore
                conn.rollback()

    logger.info("Database migration completed.")


@contextmanager
def get_session(max_retries: int = 3) -> Generator[Session, None, None]:
    """
    Context manager untuk database session. Gunakan dengan `with get_session() as db:`.

    Auto-commits on exit. Setiap `with get_session()` adalah satu transaction boundary —
    semua perubahan di dalam block akan di-commit saat exit (jika tidak ada exception).
    Untuk operasi multi-step yang harus atomic, gunakan SATU block, jangan multiple blocks.

    Retries up to max_retries on "database is locked" errors with exponential backoff.
    """
    last_error = None
    for attempt in range(max_retries):
        db = SessionLocal()
        try:
            yield db
            db.commit()
            return
        except OperationalError as e:
            db.rollback()
            if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                backoff = 0.5 * (attempt + 1)
                logger.warning(f"DB locked, retry {attempt + 1}/{max_retries} in {backoff:.1f}s")
                time.sleep(backoff)
                last_error = e
                continue
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    # Should not reach here, but just in case
    if last_error:
        raise last_error
