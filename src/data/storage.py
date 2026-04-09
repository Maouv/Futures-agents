"""
storage.py — SQLAlchemy models dan session factory.
Semua akses database WAJIB melalui session dari get_session().
DILARANG menulis raw SQL string.
"""
from datetime import datetime
from typing import Generator
from contextlib import contextmanager

from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text,
    create_engine, Index
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, Mapped, mapped_column

from src.utils.logger import logger


DATABASE_URL = "sqlite:///data/trading.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Diperlukan untuk SQLite + threading
    echo=False,
)

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
    close_reason: Mapped[str | None] = mapped_column(String(15), nullable=True)   # 'TP', 'SL', 'MANUAL', 'EXPIRED', 'RECONCILED'

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
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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

    with engine.connect() as conn:
        for table, column, col_type in new_columns:
            try:
                conn.execute(
                    __import__("sqlalchemy").text(
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
def get_session() -> Generator[Session, None, None]:
    """Context manager untuk database session. Gunakan dengan `with get_session() as db:`."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
