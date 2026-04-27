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

from src.data.storage import OHLCVCandle15m, OHLCVCandleH1, OHLCVCandleH4, get_session
from src.config.settings import settings
from src.utils.logger import logger
from src.utils.rate_limiter import binance_limiter
from src.utils.exchange import get_exchange


# ── Session Windows (UTC) ────────────────────────────────────────────────────
LONDON_OPEN_UTC = (7, 0)    # 07:00 UTC
LONDON_CLOSE_UTC = (10, 0)  # 10:00 UTC
NY_OPEN_UTC = (13, 0)       # 13:00 UTC
NY_CLOSE_UTC = (16, 0)      # 16:00 UTC

# Gap multiplier: gap dianggap anomali jika > (GAP_MULTIPLIER * timeframe)
GAP_MULTIPLIER = 2

# Fetch limits per timeframe
FETCH_LIMITS = {
    '15m': 200,
    '1h':  500,
    '4h':  300,
}

# Timeframe mapping ccxt
TIMEFRAME_MAP = {
    "15m": ("ohlcv_15m", OHLCVCandle15m),
    "1h": ("ohlcv_h1", OHLCVCandleH1),
    "4h": ("ohlcv_h4", OHLCVCandleH4),
}

# Binance API weight table (per request)
# OHLCV fetch (any TF): 10 weight per request
# Fetch Balance: 10 weight per batch
# Create Order: 1 weight per pair
# Max: 6000 weight/menit
WEIGHT_TABLE = {
    "ohlcv": 10,
    "balance": 10,
    "order": 1,
}
WEIGHT_LIMIT_PER_MIN = 6000

# Session flag untuk weight logging
_weight_logged_this_session = False


def is_trading_session(dt: datetime) -> bool:
    """
    FR-1.3: Session Filter.
    Return True hanya jika dt berada di London Open atau NY Open session (UTC).
    """
    hour, minute = dt.hour, dt.minute
    total_minutes = hour * 60 + minute

    london_start = LONDON_OPEN_UTC[0] * 60 + LONDON_OPEN_UTC[1]
    london_end = LONDON_CLOSE_UTC[0] * 60 + LONDON_CLOSE_UTC[1]
    ny_start = NY_OPEN_UTC[0] * 60 + NY_OPEN_UTC[1]
    ny_end = NY_CLOSE_UTC[0] * 60 + NY_CLOSE_UTC[1]

    in_london = london_start <= total_minutes < london_end
    in_ny = ny_start <= total_minutes < ny_end

    return in_london or in_ny


def _timeframe_to_minutes(timeframe: str) -> int:
    """
    Convert timeframe string to minutes.

    Args:
        timeframe: Timeframe string (e.g., '15m', '1h', '4h', '1d')

    Returns:
        Number of minutes

    Examples:
        '15m' -> 15
        '1h'  -> 60
        '4h'  -> 240
        '1d'  -> 1440
    """
    timeframe = timeframe.lower().strip()

    if timeframe.endswith('m'):
        return int(timeframe[:-1])
    elif timeframe.endswith('h'):
        return int(timeframe[:-1]) * 60
    elif timeframe.endswith('d'):
        return int(timeframe[:-1]) * 1440
    elif timeframe.endswith('w'):
        return int(timeframe[:-1]) * 1440 * 7
    else:
        logger.warning(f"Unknown timeframe format: {timeframe}, defaulting to 60 minutes")
        return 60


def _timeframe_to_seconds(timeframe: str) -> int:
    """
    Convert timeframe string to seconds.

    Args:
        timeframe: Timeframe string (e.g., '15m', '1h', '4h')

    Returns:
        Number of seconds

    Examples:
        '15m' -> 900
        '1h'  -> 3600
        '4h'  -> 14400
    """
    return _timeframe_to_minutes(timeframe) * 60


def detect_gap_in_batch(df: pd.DataFrame, timeframe: str) -> bool:
    """
    FR-1.2: Gap Detector (Check gap inside newly fetched batch).
    Return True (ada gap) jika ada selisih > (GAP_MULTIPLIER * timeframe_seconds) di dalam batch.
    Return False jika tidak ada gap.

    Args:
        df: DataFrame hasil fetch dari Binance
        timeframe: Timeframe string (e.g., '15m', '1h', '4h')

    Returns:
        True if gap detected in batch, False otherwise
    """
    if len(df) < 2:
        return False  # Tidak bisa cek gap jika hanya 1 candle

    expected_seconds = _timeframe_to_seconds(timeframe)
    gap_threshold = GAP_MULTIPLIER * expected_seconds

    # Hitung selisih waktu antar candle (tanpa mutasi DataFrame)
    time_diff = df['timestamp'].diff().dt.total_seconds()
    max_gap = time_diff.max()

    if max_gap > gap_threshold:
        logger.error(
            f"GAP DETECTED in batch: Max gap = {max_gap:.1f} seconds "
            f"(threshold: {gap_threshold}s = {GAP_MULTIPLIER}x {timeframe}). "
            "Skipping this cycle."
        )
        return True

    return False


def log_weight_summary(pair_count: int) -> None:
    """
    Log ringkasan estimasi API weight per cycle.
    Hanya dipanggil sekali saat startup (bukan setiap cycle).
    """
    ohlcv_per_pair = 3  # 15m, 1h, 4h
    total_ohlcv = pair_count * ohlcv_per_pair * WEIGHT_TABLE["ohlcv"]
    total_balance = WEIGHT_TABLE["balance"]  # 1x per cycle
    total_order = pair_count * WEIGHT_TABLE["order"]  # worst case
    total_worst = total_ohlcv + total_balance + total_order

    logger.info(
        f"API Weight Estimate per cycle: "
        f"OHLCV={total_ohlcv} ({pair_count} pairs × 3 TF × {WEIGHT_TABLE['ohlcv']}w) | "
        f"Balance={total_balance} | Order(worst)={total_order} | "
        f"Total(worst)={total_worst}/{WEIGHT_LIMIT_PER_MIN} "
        f"({total_worst / WEIGHT_LIMIT_PER_MIN * 100:.1f}%)"
    )


def log_actual_weight(exchange: ccxt.binanceusdm) -> None:
    """
    Log actual weight usage dari Binance response header.
    Dipanggil sekali di awal sesi (setelah first fetch berhasil).
    """
    global _weight_logged_this_session
    if _weight_logged_this_session:
        return

    try:
        headers = getattr(exchange, 'last_response_headers', None)
        if headers is None:
            return

        for k in headers:
            if k.lower() == 'x-mbxused-weight-1m':
                used = headers[k]
                pct = (int(used) / WEIGHT_LIMIT_PER_MIN) * 100
                logger.info(
                    f"Binance actual weight: {used}/{WEIGHT_LIMIT_PER_MIN} ({pct:.1f}%)"
                )
                _weight_logged_this_session = True
                return
    except Exception:
        pass


@binance_limiter.limit
def _fetch_raw_ohlcv(exchange: ccxt.binanceusdm, symbol: str, timeframe: str, limit: int = 500) -> list:
    """Internal: Fetch raw OHLCV dari Binance. Dibungkus rate limiter."""
    result = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    log_actual_weight(exchange)
    return result


def fetch_and_store_ohlcv(symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV dari Binance Futures, simpan ke DB, return sebagai DataFrame.

    Returns:
        DataFrame jika berhasil dan aman dipakai untuk analisis.
        None jika ada gap (FR-1.2) atau terjadi error.

    Note: Session filter (FR-1.3) TIDAK menghentikan fetch/store.
    Session filter hanya memberikan flag ke caller via df.attrs['skip_trade'].
    """
    exchange = get_exchange()

    # Get fetch limit based on timeframe
    limit = FETCH_LIMITS.get(timeframe, 500)

    try:
        raw_data = _fetch_raw_ohlcv(exchange, symbol, timeframe, limit=limit)
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

    # ── Gap Detector (FR-1.2) ─────────────────────────────────────────────
    # Cek gap di dalam batch yang baru di-fetch, BUKAN bandingkan dengan DB
    if detect_gap_in_batch(df, timeframe):
        return None  # Gap ditemukan di data Binance, batalkan siklus ini

    # ── Simpan ke DB ──────────────────────────────────────────────────────
    _, model_class = TIMEFRAME_MAP.get(timeframe, (None, None))
    if model_class is None:
        logger.error(f"Unknown timeframe: {timeframe}")
        return None

    with get_session() as db:
        # OPTIMIZED: Bulk query untuk cek existing timestamps
        # Konversi ke naive datetime (strip timezone) karena SQLite
        # mengembalikan naive datetime saat membaca kolom DateTime
        timestamps_to_check = [
            ts.to_pydatetime().replace(tzinfo=None)
            for ts in df["timestamp"]
        ]
        existing = (
            db.query(model_class.timestamp)
            .filter(
                model_class.symbol == symbol,
                model_class.timestamp.in_(timestamps_to_check)
            )
            .all()
        )
        existing_timestamps = {t[0] for t in existing}

        # Filter hanya candle baru — tanpa modify DataFrame (no _ts_naive column leak)
        naive_timestamps = [
            ts.to_pydatetime().replace(tzinfo=None)
            for ts in df["timestamp"]
        ]
        mask = [ts not in existing_timestamps for ts in naive_timestamps]
        new_candles_df = df[mask]

        if not new_candles_df.empty:
            # OPTIMIZED: Bulk insert dengan dict mappings
            # 1 query untuk semua inserts, bukan 500 queries
            new_candles = [
                {
                    "timestamp": row["timestamp"].to_pydatetime().replace(tzinfo=None),
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                    "symbol": symbol,
                }
                for _, row in new_candles_df.iterrows()
            ]
            db.bulk_insert_mappings(model_class, new_candles)
            logger.debug(f"Inserted {len(new_candles)} new candles for {symbol} {timeframe}")
        else:
            logger.debug(f"No new candles to insert for {symbol} {timeframe}")

    logger.info(f"Fetched & stored {len(df)} candles for {symbol} {timeframe}")

    # ── Session Filter Flag (FR-1.3) ──────────────────────────────────────
    if settings.DISABLE_SESSION_FILTER:
        df.attrs['skip_trade'] = False
        logger.debug("Session filter DISABLED by config (DISABLE_SESSION_FILTER=True)")
    else:
        now_utc = datetime.now(timezone.utc)
        skip_trade = not is_trading_session(now_utc)
        df.attrs['skip_trade'] = skip_trade
        if skip_trade:
            logger.info(
                f"Session Filter: Outside trading hours (UTC {now_utc.strftime('%H:%M')}). "
                "Data stored but SKIP_TRADE=True."
            )

    return df


def fetch_ohlcv(symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV dari Binance Futures via ccxt REST.
    Return None jika gap terdeteksi atau error.
    Attach skip_trade flag jika di luar session.

    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        timeframe: Timeframe string ('15m', '1h', '4h')

    Returns:
        DataFrame with OHLCV data, or None if error/gap detected
    """
    return fetch_and_store_ohlcv(symbol, timeframe)
