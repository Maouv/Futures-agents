"""
test_fetcher.py — Unit tests untuk safety checks di ohlcv_fetcher.
Fokus: Gap Detector dan Session Filter.
"""
import pytest
import pandas as pd
from datetime import datetime, timezone

from src.data.ohlcv_fetcher import detect_gap_in_batch, is_trading_session


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
        """Test bahwa gap detector return False untuk data yang berurutan."""
        dates = pd.date_range(start='2024-01-01 12:00', periods=5, freq='15min', tz='UTC')
        df = pd.DataFrame({'timestamp': dates})
        assert detect_gap_in_batch(df, '15m') is False

    def test_gap_over_threshold_returns_true(self):
        """Test bahwa gap detector return True untuk gap > threshold."""
        # Create data dengan gap 35 menit (melebihi threshold 30 menit untuk 15m timeframe)
        # Threshold = GAP_MULTIPLIER (2) × 15m = 30 menit
        dates = [
            datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 12, 50, tzinfo=timezone.utc),  # Gap 35 menit > 30 menit threshold!
        ]
        df = pd.DataFrame({'timestamp': dates})
        assert detect_gap_in_batch(df, '15m') is True

    def test_single_candle_no_gap(self):
        """Test bahwa single candle tidak men trigger gap."""
        dates = [datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)]
        df = pd.DataFrame({'timestamp': dates})
        assert detect_gap_in_batch(df, '15m') is False

    def test_exactly_16_minutes_no_gap(self):
        """Test bahwa gap tepat 16 menit tidak dianggap gap (threshold = 16)."""
        dates = [
            datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 12, 16, tzinfo=timezone.utc),  # Tepat 16 menit
        ]
        df = pd.DataFrame({'timestamp': dates})
        # Note: detect_gap_in_batch menggunakan threshold berbeda per timeframe
        # Untuk 15m, threshold = 16 * 1.1 = 17.6 menit
        # Jadi 16 menit masih OK
        assert detect_gap_in_batch(df, '15m') is False

