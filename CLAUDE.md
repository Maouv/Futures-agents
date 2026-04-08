# 🤖 MASTER PROMPT — Crypto Multi-Agent Trading System
# Untuk: Claude Code (claude-code CLI)
# Cara pakai: Taruh file ini di root project, lalu jalankan: `claude` di folder tsb.

---

## BRIEFING AWAL (Baca Sekali, Ingat Selamanya)

Kamu adalah Senior Python Engineer yang ditugaskan membangun **Crypto Multi-Agent Trading Bot** berbasis Binance Futures (USD-M). Project ini akan eventually menggunakan uang asli, sehingga **keamanan modal dan ketelitian kode adalah prioritas mutlak**.

Sebelum menulis baris kode pertama, kamu WAJIB membaca file-file ini secara berurutan:
1. `CLAUDE.md` — Aturan arsitektur & constraint sistem (backlace setiap saat jika ragu)
2. `ENV_AND_SECRETS_RULE.md` — Aturan pengelolaan secrets (ZERO-TOLERANCE hardcoding)
3. `IMPLEMENTATION_PLAN.md` — Satu-satunya source of truth untuk urutan pengerjaan
4. `PRD.md` — Functional requirements lengkap

**RULE PALING PENTING:** Jangan pernah melompat ke Phase N+1 jika Phase N belum selesai dan diverifikasi.

---

## KOREKSI & KLARIFIKASI ARSITEKTUR (Baca Sebelum Phase 0)

> Beberapa inkonsistensi ditemukan antara file-file docs. Aturan berikut adalah **FINAL** dan override apapun yang ada di dokumen lain.

### Koreksi #1: GLM-5 Timeout & Max Tokens (Final)
Gunakan nilai dari `.env.example`, BUKAN nilai di `CLAUDE.md`:
- `CONCIERGE_TIMEOUT_SEC = 600` (bukan 120)
- `CONCIERGE_MAX_TOKENS = 5000` (bukan 2500)

### Koreksi #2: Tambahkan field `USE_TESTNET` di Settings
`settings.py` WAJIB punya field ini:
```python
USE_TESTNET: bool = Field(default=False, description="If True, connect to Binance Testnet instead of Production")
```
Gunakan field ini di ccxt factory function untuk switch antara prod/testnet. Jangan hardcode URL di agent manapun.

### Koreksi #3: Scope Porting LuxAlgo PineScript (Phase 2)
File `luxAlgo-pineScript.txt` adalah full-featured indicator dengan banyak fitur visual.
**Untuk Phase 2, hanya port 3 fungsi berikut — tidak lebih:**
1. **Order Blocks** (fungsi `storeOrderBlock` + `deleteOrderBlocks`)
2. **Fair Value Gaps** (tipe `fairValueGap` + detection logic)
3. **BOS/CHOCH** (fungsi `displayStructure` → bagian `ta.crossover/crossunder`)

Fitur visual (drawing boxes, labels, equal highs/lows, premium/discount zones) = **SKIP sepenuhnya**.

---

## PHASE 0: Scaffolding, Config & Database

### Tujuan
Membangun fondasi project: struktur folder, konfigurasi via Pydantic Settings, dan skema database SQLAlchemy. Setelah phase ini selesai, tidak ada satu pun file yang boleh diubah strukturnya tanpa persetujuan eksplisit.

### Prerequisites
```bash
# Pastikan Python 3.11+ tersedia
python --version

# Install dependencies yang dibutuhkan Phase 0
pip install pydantic-settings pydantic sqlalchemy loguru python-dotenv
```

### Task 0.1 — Buat Struktur Folder

Buat struktur folder ini PERSIS seperti di bawah. Jangan tambah, jangan kurangi:

```
project-root/
├── .env                        # Copy dari .env.example, isi dengan nilai dummy
├── .env.example                # Sudah ada, jangan diubah
├── .gitignore
├── CLAUDE.md                   # Sudah ada
├── ENV_AND_SECRETS_RULE.md     # Sudah ada
├── IMPLEMENTATION_PLAN.md      # Sudah ada
├── PRD.md                      # Sudah ada
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                 # Kosong dulu, hanya docstring
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── storage.py
│   │   ├── ohlcv_fetcher.py    # Kosong dulu
│   │   └── onchain_fetcher.py  # Kosong dulu
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── math/
│   │   │   └── __init__.py
│   │   └── llm/
│   │       └── __init__.py
│   ├── indicators/
│   │   ├── __init__.py
│   │   ├── luxalgo_smc.py      # Kosong dulu
│   │   └── mean_reversion.py   # Kosong dulu
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bot.py              # Kosong dulu
│   │   └── commands.py         # Kosong dulu
│   └── utils/
│       ├── __init__.py
│       ├── rate_limiter.py     # Kosong dulu
│       └── logger.py
├── tests/
│   └── __init__.py
└── data/                       # Folder untuk SQLite DB, dikecualikan dari git
```

Untuk file "kosong dulu", isi dengan:
```python
"""
[nama_modul] — To be implemented in Phase [N].
"""
```

### Task 0.2 — `.gitignore`

Buat `.gitignore` dengan konten minimal ini:
```gitignore
# Secrets
.env
*.env

# Database
data/
*.db
*.sqlite

# Python
__pycache__/
*.py[cod]
*.egg-info/
venv/
.venv/
dist/
build/

# IDE
.vscode/
.idea/
*.swp

# Logs
*.log
logs/

# RL Models (Phase 7)
data/rl_models/
```

### Task 0.3 — `requirements.txt`

```txt
# ==========================================
# CORE TRADING & DATA ENGINE
# ==========================================
ccxt==4.2.86              # Universal crypto API (Mendukung binanceusdm() REST)
pandas==2.2.2             # Manipulasi data OHLCV & Indikator
numpy==1.26.4             # Komputasi matematika cepat (Vectorization)
ta==0.11.0                # Library Technical Analysis standar (RSI, ATR, dll)
pandas-ta==0.3.14b1       # Tambahan indikator (jika diperlukan saat porting LuxAlgo)

# ==========================================
# DATABASE & ORM
# ==========================================
sqlalchemy==2.0.31        # ORM untuk mengelola SQLite (Paper Trade DB)
aiosqlite==0.20.0         # Driver async SQLite (Dibutuhkan oleh Telegram Bot agar tidak blocking)

# ==========================================
# SCHEDULING & INFRASTRUCTURE
# ==========================================
apscheduler==3.10.4       # Job scheduler utama (Loop 15 menit)
loguru==0.7.2             # Logging yang jauh lebih baik dari print() atau logging bawaan

# ==========================================
# TELEGRAM INTERFACE
# ==========================================
python-telegram-bot==21.5 # Framework Telegram Bot (Async, stabil, mendukung handler kompleks)

# ==========================================
# LLM API CLIENTS (COGNITIVE LAYER)
# ==========================================
openai==1.40.0            # Universal SDK (Digunakan untuk Cerebras DAN Groq karena kompatibel OpenAI standard)
# modal SDK tidak dibutuhkan — GLM-5 diakses via HTTP endpoint (MODAL_BASE_URL di .env)
# menggunakan openai SDK yang sudah ada di atas

# ==========================================
# CONFIGURATION & VALIDATION
# ==========================================
pydantic==2.8.2           # Validasi data (Pydantic Models untuk antar Agent)
pydantic-settings==2.3.4  # Mengambil & memvalidasi variabel dari file .env
python-dotenv==1.0.1      # Loader file .env

# ==========================================
# NETWORKING (ON-CHAIN & FALLBACK)
# ==========================================
httpx==0.27.0             # HTTP Client modern (Untuk fetch DefiLlama / On-chain data)
websockets==12.0          # Library WS murni Python (Phase 8: User Data Stream — bukan market data)

# ==========================================
# REINFORCEMENT LEARNING (PHASE 7 - COLAB ONLY, BUKAN VPS)
# ==========================================
# ⚠️ CATATAN UNTUK CLAUDE CODE:
# JANGAN install 3 package di bawah ini di VPS trading.
# Alur Phase 7:
#   1. Export data/trading.db → CSV dari VPS
#   2. Upload CSV ke Google Colab (gratis, GPU T4)
#   3. Training PPO di Colab (bukan di VPS)
#   4. Download model .zip dari Colab
#   5. Upload model ke VPS: data/rl_models/best_model.zip
#   6. Bot baca model dari path itu
# Jika user belum sampai Phase 7, SKIP install package ini.
# Jika user minta install di VPS, INGATKAN risiko OOM dan sarankan Colab.
gymnasium==0.29.1         # Install di Colab saja
stable-baselines3==2.3.2  # Install di Colab saja
torch==2.3.1              # Install di Colab saja — terlalu berat untuk VPS 8GB RAM

# ==========================================
# DEVELOPMENT & TESTING
# ==========================================
pytest==8.2.2             # Framework untuk menulis Unit Test (Validasi LuxAlgo di Phase 2)
```

> **⚠️ CATATAN PENTING untuk Claude Code:**
> - `modal` SDK **tidak diinstall** — koneksi ke GLM-5 cukup via `openai` SDK dengan `base_url` dari `settings.MODAL_BASE_URL`. Modal SDK hanya dibutuhkan jika deploy fungsi ke Modal, bukan konsumsi endpoint.
> - `websockets` di sini **HANYA untuk User Data Stream** (Phase 8) — mendengarkan event `ORDER_TRADE_UPDATE` dari Binance, bukan stream harga/kline. Sesuai `CLAUDE.md` Rule 2.
> - `aiosqlite` dibutuhkan karena `python-telegram-bot==21.x` berjalan async.

### Task 0.4 — `src/utils/logger.py`

```python
"""
logger.py — Loguru setup terpusat.
Semua modul WAJIB import logger dari sini. DILARANG pakai print().
"""
import sys
from loguru import logger


def setup_logger(log_level: str = "INFO") -> None:
    """Configure loguru dengan format standar project."""
    logger.remove()  # Hapus default handler
    
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>",
        level=log_level,
        colorize=True,
    )
    
    logger.add(
        "logs/trading_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
        level="DEBUG",
        rotation="00:00",      # Rotate setiap tengah malam
        retention="30 days",   # Simpan 30 hari
        compression="zip",
        enqueue=True,          # Thread-safe
    )


# Export logger langsung agar bisa `from src.utils.logger import logger`
__all__ = ["logger", "setup_logger"]
```

### Task 0.5 — `src/config/settings.py`

**KRITIS: Ikuti `ENV_AND_SECRETS_RULE.md` 100%.** Semua API Key pakai `SecretStr`, semua URL pakai `HttpUrl`, tidak ada hardcoded value kecuali default yang memang tertulis di `.env.example`.

```python
"""
settings.py — Single source of truth untuk semua konfigurasi.
Menggunakan pydantic-settings untuk validasi otomatis saat startup.
Jika ada env var yang missing, aplikasi akan CRASH dengan ValidationError (by design).
"""
from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # ── System ──────────────────────────────────────────────────────────────
    ENVIRONMENT: str = Field(default="development")
    EXECUTION_MODE: str = Field(default="paper", description="'paper' atau 'live'")
    USE_TESTNET: bool = Field(default=False, description="True = connect ke Binance Testnet")

    # ── Binance Futures (Production) ─────────────────────────────────────────
    BINANCE_REST_URL: HttpUrl = Field(default="https://fapi.binance.com")
    BINANCE_WS_URL: str = Field(default="wss://fstream.binance.com/ws")
    BINANCE_API_KEY: SecretStr = Field(..., description="Binance Futures API Key")
    BINANCE_API_SECRET: SecretStr = Field(..., description="Binance Futures API Secret")

    # ── Binance Testnet ──────────────────────────────────────────────────────
    BINANCE_TESTNET_URL: HttpUrl = Field(default="https://testnet.binancefuture.com")
    BINANCE_TESTNET_WS_URL: str = Field(default="wss://stream.binancefuture.com/ws")
    BINANCE_TESTNET_KEY: SecretStr = Field(..., description="Binance Testnet API Key")
    BINANCE_TESTNET_SECRET: SecretStr = Field(..., description="Binance Testnet API Secret")

    # ── Futures Trading Params ───────────────────────────────────────────────
    FUTURES_MARGIN_TYPE: str = Field(default="isolated", description="'isolated' atau 'cross'")
    FUTURES_DEFAULT_LEVERAGE: int = Field(default=10, ge=1, le=125)

    # ── LLM: Analyst (Cerebras) ──────────────────────────────────────────────
    CEREBRAS_API_KEY: SecretStr = Field(..., description="Cerebras API Key")
    CEREBRAS_BASE_URL: HttpUrl = Field(default="https://api.cerebras.ai/v1/chat/completions")
    CEREBRAS_MODEL: str = Field(default="qwen-3-235b-a22b-instruct-2507")

    # ── LLM: Commander (Groq) ────────────────────────────────────────────────
    GROQ_API_KEY: SecretStr = Field(..., description="Groq API Key")
    GROQ_BASE_URL: HttpUrl = Field(default="https://api.groq.com/openai/v1/chat/completions")
    GROQ_MODEL: str = Field(default="llama-3.1-8b-instant")

    # ── LLM: Concierge (Modal GLM-5) ─────────────────────────────────────────
    MODAL_TOKEN: SecretStr = Field(..., description="Modal API Token")
    MODAL_BASE_URL: HttpUrl = Field(default="https://api.us-west-2.modal.direct/v1/chat/completions")
    MODAL_MODEL: str = Field(default="zai-org/GLM-5-FP8")

    # ── Telegram ─────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: SecretStr = Field(..., description="Telegram Bot Token")
    TELEGRAM_CHAT_ID: str = Field(..., description="Telegram Chat ID (string, bisa negatif untuk group)")

    # ── Timeouts & Limits ────────────────────────────────────────────────────
    LLM_FAST_TIMEOUT_SEC: int = Field(default=45, description="Timeout Cerebras & Groq")
    CONCIERGE_TIMEOUT_SEC: int = Field(default=600, description="Timeout GLM-5 (lambat)")
    CONCIERGE_MAX_TOKENS: int = Field(default=5000, description="Max tokens GLM-5 reasoning")


# Singleton — import ini di mana saja
settings = Settings()
```

### Task 0.6 — `src/data/storage.py`

```python
"""
storage.py — SQLAlchemy models dan session factory.
Semua akses database WAJIB melalui session dari get_session().
DILARANG menulis raw SQL string.
"""
from datetime import datetime
from typing import Generator

from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text,
    create_engine, Index
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

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

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    timestamp: datetime = Column(DateTime, nullable=False)
    open: float = Column(Float, nullable=False)
    high: float = Column(Float, nullable=False)
    low: float = Column(Float, nullable=False)
    close: float = Column(Float, nullable=False)
    volume: float = Column(Float, nullable=False)
    symbol: str = Column(String(20), nullable=False)


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

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    pair: str = Column(String(20), nullable=False)
    side: str = Column(String(5), nullable=False)           # 'LONG' atau 'SHORT'
    entry_price: float = Column(Float, nullable=False)
    sl_price: float = Column(Float, nullable=False)
    tp_price: float = Column(Float, nullable=False)
    size: float = Column(Float, nullable=False)             # Quantity dalam kontrak
    leverage: int = Column(Integer, nullable=False)
    status: str = Column(String(10), nullable=False, default="OPEN")  # 'OPEN' atau 'CLOSED'
    pnl: float = Column(Float, nullable=True)               # Diisi saat CLOSED
    entry_timestamp: datetime = Column(DateTime, default=datetime.utcnow)
    close_timestamp: datetime = Column(DateTime, nullable=True)
    close_reason: str = Column(String(10), nullable=True)   # 'TP', 'SL', 'MANUAL'


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    timestamp: datetime = Column(DateTime, default=datetime.utcnow)
    level: str = Column(String(10), nullable=False)         # 'INFO', 'WARNING', 'ERROR'
    source: str = Column(String(50), nullable=False)        # Nama agent yang log
    message: str = Column(Text, nullable=False)
    trade_id: int = Column(Integer, nullable=True)          # FK ke paper_trades jika relevan


def init_db() -> None:
    """Buat semua tabel jika belum ada. Panggil sekali saat startup."""
    import os
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized successfully.")


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
```

### Task 0.7 — `src/main.py` (Skeleton)

```python
"""
main.py — Entry point dan orchestrator utama.
Siklus 15 menit diimplementasikan di Phase 5.
"""
from src.config.settings import settings
from src.data.storage import init_db
from src.utils.logger import logger, setup_logger


def main() -> None:
    setup_logger()
    logger.info(f"Starting Crypto Multi-Agent Trading System")
    logger.info(f"Mode: {settings.EXECUTION_MODE.upper()} | Testnet: {settings.USE_TESTNET}")
    
    init_db()
    
    logger.info("Phase 0 scaffold ready. Main loop will be implemented in Phase 5.")


if __name__ == "__main__":
    main()
```

### Task 0.8 — Verifikasi Phase 0

Setelah semua file dibuat, jalankan verifikasi ini. **Jangan lanjut ke Phase 1 sebelum semua PASS:**

```bash
# Test 1: Settings bisa diload tanpa error
python -c "
from src.config.settings import settings
print(f'✅ Settings loaded. Mode: {settings.EXECUTION_MODE}')
print(f'✅ Testnet: {settings.USE_TESTNET}')
print(f'✅ Leverage: {settings.FUTURES_DEFAULT_LEVERAGE}')
"

# Test 2: Database bisa dibuat
python -c "
from src.data.storage import init_db
init_db()
print('✅ Database created at data/trading.db')
"

# Test 3: Logger berfungsi
python -c "
from src.utils.logger import logger, setup_logger
setup_logger()
logger.info('✅ Logger working')
logger.debug('✅ Debug level working')
"

# Test 4: Main entry point berjalan
python -m src.main
```

**Expected output Test 4:**
```
YYYY-MM-DD HH:mm:ss | INFO     | ... — Starting Crypto Multi-Agent Trading System
YYYY-MM-DD HH:mm:ss | INFO     | ... — Mode: PAPER | Testnet: False
YYYY-MM-DD HH:mm:ss | INFO     | ... — Database initialized successfully.
YYYY-MM-DD HH:mm:ss | INFO     | ... — Phase 0 scaffold ready. Main loop will be implemented in Phase 5.
```

---

## PHASE 1: Data Engine, Rate Limiter & Safety Checks

> **JANGAN MULAI** Phase 1 sebelum semua Test Phase 0 PASS.

### Task 1.1 — `src/utils/rate_limiter.py`

Implementasikan sliding window rate limiter. Requirement: max 800 request/menit, thread-safe.

```python
"""
rate_limiter.py — Sliding window rate limiter untuk semua HTTP calls ke Binance.
MAX 800 request/menit sesuai PRD FR-1.1.
Thread-safe menggunakan threading.Lock.
"""
import threading
import time
from collections import deque
from typing import Callable, TypeVar, Any

from src.utils.logger import logger

T = TypeVar("T")

class RateLimiter:
    """
    Sliding window rate limiter.
    
    Usage:
        limiter = RateLimiter(max_calls=800, period=60)
        
        @limiter.limit
        def fetch_data():
            ...
    """
    
    def __init__(self, max_calls: int = 800, period: float = 60.0) -> None:
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()
    
    def wait_if_needed(self) -> None:
        """Block sampai slot tersedia dalam window."""
        with self._lock:
            now = time.monotonic()
            
            # Buang timestamps di luar window
            while self._calls and self._calls[0] <= now - self.period:
                self._calls.popleft()
            
            if len(self._calls) >= self.max_calls:
                # Hitung waktu tunggu
                sleep_time = self._calls[0] + self.period - now
                if sleep_time > 0:
                    logger.warning(f"Rate limit reached. Waiting {sleep_time:.2f}s")
                    # Release lock sebelum sleep agar thread lain bisa cek
                    self._lock.release()
                    time.sleep(sleep_time)
                    self._lock.acquire()
                    # Re-clean setelah sleep
                    now = time.monotonic()
                    while self._calls and self._calls[0] <= now - self.period:
                        self._calls.popleft()
            
            self._calls.append(time.monotonic())
    
    def limit(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator untuk membungkus fungsi dengan rate limiting."""
        def wrapper(*args: Any, **kwargs: Any) -> T:
            self.wait_if_needed()
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        return wrapper


# Singleton instance — import ini di ohlcv_fetcher
binance_limiter = RateLimiter(max_calls=800, period=60.0)
```

### Task 1.2 — `src/data/ohlcv_fetcher.py`

**KRITIS:** File ini harus implement Gap Detector (FR-1.2) dan Session Filter (FR-1.3).

```python
"""
ohlcv_fetcher.py — Fetch OHLCV data dari Binance Futures via ccxt REST API.

SAFETY RULES (WAJIB ADA):
- Gap Detector: Tolak data jika gap > 16 menit (FR-1.2)
- Session Filter: Skip sinyal di luar London/NY session (FR-1.3)
- Semua request dibungkus rate_limiter (FR-1.1)
- Gunakan ccxt.binanceusdm() BUKAN ccxt.binance() (CLAUDE.md Rule 1)
"""
import ccxt
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from src.config.settings import settings
from src.data.storage import OHLCVCandle15m, OHLCVCandleH1, OHLCVCandleH4, get_session
from src.utils.logger import logger
from src.utils.rate_limiter import binance_limiter


# ── Session Windows (UTC) ────────────────────────────────────────────────────
LONDON_OPEN_UTC  = (7, 0)    # 07:00 UTC
LONDON_CLOSE_UTC = (10, 0)   # 10:00 UTC
NY_OPEN_UTC      = (13, 0)   # 13:00 UTC
NY_CLOSE_UTC     = (16, 0)   # 16:00 UTC

# Gap threshold dalam menit (FR-1.2)
GAP_THRESHOLD_MINUTES = 16

# Timeframe mapping ccxt
TIMEFRAME_MAP = {
    "15m": ("ohlcv_15m", OHLCVCandle15m),
    "1h":  ("ohlcv_h1",  OHLCVCandleH1),
    "4h":  ("ohlcv_h4",  OHLCVCandleH4),
}


def _create_exchange() -> ccxt.binanceusdm:
    """
    Factory function untuk ccxt exchange instance.
    Otomatis switch ke testnet jika settings.USE_TESTNET = True.
    """
    if settings.USE_TESTNET:
        exchange = ccxt.binanceusdm({
            "apiKey": settings.BINANCE_TESTNET_KEY.get_secret_value(),
            "secret": settings.BINANCE_TESTNET_SECRET.get_secret_value(),
            "options": {"defaultType": "future"},
            "urls": {
                "api": {
                    "public": str(settings.BINANCE_TESTNET_URL),
                    "private": str(settings.BINANCE_TESTNET_URL),
                }
            }
        })
        logger.debug("Exchange: Binance Futures TESTNET")
    else:
        exchange = ccxt.binanceusdm({
            "apiKey": settings.BINANCE_API_KEY.get_secret_value(),
            "secret": settings.BINANCE_API_SECRET.get_secret_value(),
            "options": {"defaultType": "future"},
        })
        logger.debug("Exchange: Binance Futures PRODUCTION")
    
    return exchange


def is_trading_session(dt: datetime) -> bool:
    """
    FR-1.3: Session Filter.
    Return True hanya jika dt berada di London Open atau NY Open session (UTC).
    """
    hour, minute = dt.hour, dt.minute
    total_minutes = hour * 60 + minute
    
    london_start = LONDON_OPEN_UTC[0] * 60 + LONDON_OPEN_UTC[1]
    london_end   = LONDON_CLOSE_UTC[0] * 60 + LONDON_CLOSE_UTC[1]
    ny_start     = NY_OPEN_UTC[0] * 60 + NY_OPEN_UTC[1]
    ny_end       = NY_CLOSE_UTC[0] * 60 + NY_CLOSE_UTC[1]
    
    in_london = london_start <= total_minutes < london_end
    in_ny     = ny_start <= total_minutes < ny_end
    
    return in_london or in_ny


def detect_gap(last_db_timestamp: Optional[datetime], new_timestamp: datetime) -> bool:
    """
    FR-1.2: Gap Detector.
    Return True (ada gap) jika selisih > GAP_THRESHOLD_MINUTES.
    Return False jika tidak ada gap atau belum ada data di DB (first run).
    """
    if last_db_timestamp is None:
        return False  # First run, tidak ada gap
    
    diff_minutes = (new_timestamp - last_db_timestamp).total_seconds() / 60
    
    if diff_minutes > GAP_THRESHOLD_MINUTES:
        logger.error(
            f"GAP DETECTED: Last candle at {last_db_timestamp.isoformat()}, "
            f"new candle at {new_timestamp.isoformat()}, "
            f"gap = {diff_minutes:.1f} minutes (threshold: {GAP_THRESHOLD_MINUTES}m). "
            "Skipping this cycle."
        )
        return True
    
    return False


@binance_limiter.limit
def _fetch_raw_ohlcv(exchange: ccxt.binanceusdm, symbol: str, timeframe: str, limit: int = 200) -> list:
    """Internal: Fetch raw OHLCV dari Binance. Dibungkus rate limiter."""
    return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)


def fetch_and_store_ohlcv(symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV dari Binance Futures, simpan ke DB, return sebagai DataFrame.
    
    Returns:
        DataFrame jika berhasil dan aman dipakai untuk analisis.
        None jika ada gap (FR-1.2) atau terjadi error.
    
    Note: Session filter (FR-1.3) TIDAK menghentikan fetch/store.
    Session filter hanya memberikan flag ke caller via df.attrs['skip_trade'].
    """
    exchange = _create_exchange()
    
    try:
        raw_data = _fetch_raw_ohlcv(exchange, symbol, timeframe)
    except ccxt.NetworkError as e:
        logger.error(f"Network error fetching {symbol} {timeframe}: {e}")
        return None
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error fetching {symbol} {timeframe}: {e}")
        return None
    
    if not raw_data:
        logger.warning(f"No data returned for {symbol} {timeframe}")
        return None
    
    # Convert ke DataFrame
    df = pd.DataFrame(raw_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    latest_candle_time = df["timestamp"].iloc[-1].to_pydatetime()
    
    # ── Gap Detector (FR-1.2) ─────────────────────────────────────────────
    _, model_class = TIMEFRAME_MAP.get(timeframe, (None, None))
    if model_class is None:
        logger.error(f"Unknown timeframe: {timeframe}")
        return None
    
    last_db_timestamp: Optional[datetime] = None
    with get_session() as db:
        last_row = (
            db.query(model_class)
            .filter(model_class.symbol == symbol)
            .order_by(model_class.timestamp.desc())
            .first()
        )
        if last_row:
            last_db_timestamp = last_row.timestamp
    
    if detect_gap(last_db_timestamp, latest_candle_time):
        return None  # Gap ditemukan, batalkan siklus ini
    
    # ── Simpan ke DB ──────────────────────────────────────────────────────
    with get_session() as db:
        for _, row in df.iterrows():
            exists = (
                db.query(model_class)
                .filter(
                    model_class.symbol == symbol,
                    model_class.timestamp == row["timestamp"].to_pydatetime(),
                )
                .first()
            )
            if not exists:
                candle = model_class(
                    timestamp=row["timestamp"].to_pydatetime(),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    symbol=symbol,
                )
                db.add(candle)
    
    logger.info(f"Fetched & stored {len(df)} candles for {symbol} {timeframe}")
    
    # ── Session Filter Flag (FR-1.3) ──────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    skip_trade = not is_trading_session(now_utc)
    df.attrs["skip_trade"] = skip_trade
    
    if skip_trade:
        logger.info(
            f"Session Filter: Outside trading hours (UTC {now_utc.strftime('%H:%M')}). "
            "Data stored but SKIP_TRADE=True."
        )
    
    return df
```

### Task 1.3 — `tests/test_fetcher.py`

```python"""
test_fetcher.py — Unit tests untuk safety checks di ohlcv_fetcher.
Fokus: Gap Detector dan Session Filter.
"""
import pytest
from datetime import datetime, timezone

from src.data.ohlcv_fetcher import detect_gap, is_trading_session


class TestSessionFilter:
    def test_london_open_is_trading(self):
        dt = datetime(2024, 1, 1, 8, 30, tzinfo=timezone.utc)  # 08:30 UTC
        assert is_trading_session(dt) is True

    def test_ny_open_is_trading(self):
        dt = datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc)  # 14:00 UTC
        assert is_trading_session(dt) is True

    def test_outside_session_is_skipped(self):
        dt = datetime(2024, 1, 1, 5, 0, tzinfo=timezone.utc)   # 05:00 UTC
        assert is_trading_session(dt) is False

    def test_midnight_is_skipped(self):
        dt = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert is_trading_session(dt) is False
    
    def test_london_boundary_start(self):
        dt = datetime(2024, 1, 1, 7, 0, tzinfo=timezone.utc)   # Tepat 07:00
        assert is_trading_session(dt) is True
    
    def test_london_boundary_end(self):
        dt = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)  # Tepat 10:00 = TIDAK masuk
        assert is_trading_session(dt) is False


class TestGapDetector:
    def test_no_gap_returns_false(self):
        last = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        new  = datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
        assert detect_gap(last, new) is False

    def test_gap_over_threshold_returns_true(self):
        last = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        new  = datetime(2024, 1, 1, 12, 20, tzinfo=timezone.utc)  # 20 menit > 16
        assert detect_gap(last, new) is True

    def test_none_last_timestamp_no_gap(self):
        new = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert detect_gap(None, new) is False  # First run

    def test_exactly_16_minutes_no_gap(self):
        last = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        new  = datetime(2024, 1, 1, 12, 16, tzinfo=timezone.utc)  # Tepat 16 = masih OK
        assert detect_gap(last, new) is False
```

### Verifikasi Phase 1

```bash
# Jalankan tests
pytest tests/test_fetcher.py -v

# Expected: semua test PASS
# tests/test_fetcher.py::TestSessionFilter::test_london_open_is_trading PASSED
# tests/test_fetcher.py::TestSessionFilter::test_ny_open_is_trading PASSED
# ... dst
```

---

## HANDOFF KE PHASE 2 (Checklist Sebelum Lanjut)

Sebelum memulai Phase 2 (Porting LuxAlgo Indicators), pastikan:

- [ ] Semua 4 test Phase 0 PASS
- [ ] Semua test Phase 1 PASS (`pytest tests/ -v`)
- [ ] File `data/trading.db` terbentuk dan bisa dibuka
- [ ] Tidak ada `print()` statement di seluruh codebase (semua pakai `loguru.logger`)
- [ ] Tidak ada hardcoded string URL atau API key di luar `settings.py`

**Jika semua checklist di atas hijau, baru boleh lanjut ke Phase 2.**

---

## ROADMAP LENGKAP SETELAH PHASE 1 (Referensi — Detail ada di `IMPLEMENTATION_PLAN.md`)

> Master prompt ini hanya cover Phase 0 dan Phase 1 secara detail.
> Untuk Phase 2 ke atas, **selalu baca `IMPLEMENTATION_PLAN.md`** sebagai source of truth.
> Berikut ringkasan urutan yang WAJIB diikuti:

```
Phase 0 → Phase 1 → Phase 2 → Phase 2.5 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7 → Phase 8
```

**Phase 2 — Porting Indikator (BLOCKING)**
- Port 3 fungsi LuxAlgo dari `luxAlgo-pineScript.txt`: Order Blocks, FVG, BOS/CHOCH
- Port RSI + Bollinger Bands ke `mean_reversion.py`
- Validasi manual vs TradingView, toleransi `< 0.0001`
- **JANGAN lanjut ke Phase 2.5 sebelum validasi PASS**

**Phase 2.5 — Backtest Engine & Gate Check (BLOCKING)**
- Download data historis Binance Futures dari `https://data.binance.vision` (gratis, tanpa API key)
- URL format: `https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/15m/BTCUSDT-15m-YYYY-MM.zip`
- Buat folder `scripts/` untuk: `download_historical.py`, `load_historical_to_db.py`, `run_backtest.py`, `export_trade_data.py`
- Buat `src/backtest/engine.py` — jalankan pipeline SMC terhadap data historis
- **Gate check WAJIB LULUS sebelum Phase 3:**
  - Win rate ≥ 45%
  - Profit factor ≥ 1.2
  - Max drawdown ≤ 30%
  - Total trades ≥ 50
- Jika gagal: perbaiki indikator Phase 2, ulangi backtest

**Phase 3-6 — Agents, LLM, Execution, Deployment**
- Ikuti `IMPLEMENTATION_PLAN.md` step by step

**Phase 7 — RL Training di Google Colab (BUKAN VPS)**
- `gymnasium`, `stable-baselines3`, `torch` — **JANGAN install di VPS**
- Alur: export CSV dari VPS → upload ke Colab → training → download `best_model.zip` → upload ke VPS `data/rl_models/`
- Jika user minta install torch di VPS: **INGATKAN risiko OOM**, sarankan Colab

**Phase 8 — Go Live**
- Wajib test Testnet dulu (`USE_TESTNET=True`)
- Entry + 2x Stop/TP Market Order terpisah — **DILARANG OCO**

---
*Generated by Claude — untuk dieksekusi via Claude Code CLI*
*Versi: 2.0 | Tanggal: 2026-04*

