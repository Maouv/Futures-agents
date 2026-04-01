"""
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
        new = datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
        assert detect_gap(last, new) is False

    def test_gap_over_threshold_returns_true(self):
        last = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        new = datetime(2024, 1, 1, 12, 20, tzinfo=timezone.utc)  # 20 menit > 16
        assert detect_gap(last, new) is True

    def test_none_last_timestamp_no_gap(self):
        new = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert detect_gap(None, new) is False  # First run

    def test_exactly_16_minutes_no_gap(self):
        last = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        new = datetime(2024, 1, 1, 12, 16, tzinfo=timezone.utc)  # Tepat 16 = masih OK
        assert detect_gap(last, new) is False
