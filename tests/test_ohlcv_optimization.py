"""
test_ohlcv_optimization.py — Unit test untuk BUG #11 fix.
Test bahwa bulk insert optimization bekerja dengan benar.
"""
import pandas as pd
import numpy as np

from src.data.ohlcv_fetcher import TIMEFRAME_MAP
from src.data.storage import init_db, get_session


def test_bulk_insert_logic():
    """
    Test logika bulk insert secara langsung tanpa call fungsi fetch.
    Ini memverifikasi bahwa optimization bekerja dengan benar.
    """
    init_db()

    # Get model class
    _, model_class = TIMEFRAME_MAP.get('1h', (None, None))
    assert model_class is not None, "Model class untuk 1h tidak ditemukan"

    # Clear existing data
    with get_session() as db:
        db.query(model_class).filter(model_class.symbol == 'TESTCOIN').delete()
        db.commit()

    # Create test data
    dates = pd.date_range(start='2024-01-01', periods=10, freq='1h', tz='UTC')
    df = pd.DataFrame({
        'timestamp': dates,
        'open': np.random.uniform(66000, 68000, 10),
        'high': np.random.uniform(67000, 68000, 10),
        'low': np.random.uniform(66000, 67000, 10),
        'close': np.random.uniform(66500, 67500, 10),
        'volume': np.random.uniform(100, 1000, 10)
    })

    # Test bulk insert logic
    with get_session() as db:
        # Step 1: Bulk query existing
        timestamps_to_check = df["timestamp"].tolist()
        existing = (
            db.query(model_class.timestamp)
            .filter(
                model_class.symbol == 'TESTCOIN',
                model_class.timestamp.in_(timestamps_to_check)
            )
            .all()
        )
        existing_timestamps = {t[0] for t in existing}

        # Step 2: Filter new candles
        new_candles_df = df[~df['timestamp'].isin(existing_timestamps)]
        assert len(new_candles_df) == 10, "All candles should be new"

        # Step 3: Bulk insert
        new_candles = [
            {
                "timestamp": row["timestamp"].to_pydatetime(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "symbol": 'TESTCOIN',
            }
            for _, row in new_candles_df.iterrows()
        ]
        db.bulk_insert_mappings(model_class, new_candles)

    # Verify insert succeeded
    with get_session() as db:
        count = db.query(model_class).filter(
            model_class.symbol == 'TESTCOIN'
        ).count()
        assert count == 10, f"Expected 10 candles, got {count}"


def test_bulk_insert_deduplication():
    """
    Test bahwa deduplication bekerja - candles yang sudah ada tidak di-insert ulang.
    """
    init_db()

    _, model_class = TIMEFRAME_MAP.get('1h', (None, None))

    # Clear existing data
    with get_session() as db:
        db.query(model_class).filter(model_class.symbol == 'TESTCOIN2').delete()
        db.commit()

    # Insert first batch
    dates1 = pd.date_range(start='2024-01-01', periods=10, freq='1h', tz='UTC')
    df1 = pd.DataFrame({
        'timestamp': dates1,
        'open': np.random.uniform(66000, 68000, 10),
        'high': np.random.uniform(67000, 68000, 10),
        'low': np.random.uniform(66000, 67000, 10),
        'close': np.random.uniform(66500, 67500, 10),
        'volume': np.random.uniform(100, 1000, 10)
    })

    with get_session() as db:
        new_candles = [
            {
                "timestamp": row["timestamp"].to_pydatetime(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "symbol": 'TESTCOIN2',
            }
            for _, row in df1.iterrows()
        ]
        db.bulk_insert_mappings(model_class, new_candles)

    # Try to insert overlapping data
    dates2 = pd.date_range(start='2024-01-01 05:00', periods=10, freq='1h', tz='UTC')  # 5 overlap
    df2 = pd.DataFrame({
        'timestamp': dates2,
        'open': np.random.uniform(66000, 68000, 10),
        'high': np.random.uniform(67000, 68000, 10),
        'low': np.random.uniform(66000, 67000, 10),
        'close': np.random.uniform(66500, 67500, 10),
        'volume': np.random.uniform(100, 1000, 10)
    })

    with get_session() as db:
        # Deduplication logic
        timestamps_to_check = df2["timestamp"].tolist()
        existing = (
            db.query(model_class.timestamp)
            .filter(
                model_class.symbol == 'TESTCOIN2',
                model_class.timestamp.in_(timestamps_to_check)
            )
            .all()
        )
        # SQLite strips timezone, normalize to UTC naive for comparison
        existing_timestamps = {t[0].replace(tzinfo=None) for t in existing}

        # Also normalize df timestamps for comparison
        df2_naive = df2.copy()
        df2_naive['timestamp'] = df2_naive['timestamp'].dt.tz_localize(None)

        new_candles_df = df2[~df2_naive['timestamp'].isin(existing_timestamps)]
        assert len(new_candles_df) == 5, "Only 5 candles should be new"

        # Insert only new
        new_candles = [
            {
                "timestamp": row["timestamp"].to_pydatetime(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "symbol": 'TESTCOIN2',
            }
            for _, row in new_candles_df.iterrows()
        ]
        db.bulk_insert_mappings(model_class, new_candles)

    # Verify total count
    with get_session() as db:
        count = db.query(model_class).filter(
            model_class.symbol == 'TESTCOIN2'
        ).count()
        assert count == 15, f"Expected 15 candles (10 + 5), got {count}"

