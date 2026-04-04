"""
test_sltp_manager.py — Unit tests untuk SL/TP Manager.
Fokus: Multi-pair error handling (BUG #5 fix).
"""
import pytest
from datetime import datetime, timezone
from _pytest.logging import LogCaptureFixture
from loguru import logger

from src.agents.math.sltp_manager import check_paper_trades
from src.data.storage import PaperTrade, init_db, get_session


class TestSLTPManagerMultiPair:
    """Test untuk verifikasi error handling multi-pair."""

    def setup_method(self):
        """Setup: Bersihkan DB sebelum setiap test."""
        init_db()
        with get_session() as db:
            db.query(PaperTrade).delete()
            db.commit()

    def test_missing_pair_logs_error(self, capfd):
        """
        Test bahwa jika ada trade dengan pair yang tidak ada di price dict,
        akan log ERROR (bukan WARNING).
        """
        from datetime import datetime, timezone

        # Setup: Buat 2 paper trades dengan pair berbeda
        with get_session() as db:
            # Trade BTCUSDT - ada di price dict
            trade1 = PaperTrade(
                pair='BTCUSDT',
                side='LONG',
                entry_price=67000.0,
                sl_price=66800.0,
                tp_price=67400.0,
                size=0.05,
                leverage=10,
                status='OPEN',
                entry_timestamp=datetime.now(timezone.utc)
            )
            # Trade ETHUSDT - TIDAK ada di price dict
            trade2 = PaperTrade(
                pair='ETHUSDT',
                side='LONG',
                entry_price=3500.0,
                sl_price=3450.0,
                tp_price=3600.0,
                size=0.5,
                leverage=10,
                status='OPEN',
                entry_timestamp=datetime.now(timezone.utc)
            )
            db.add(trade1)
            db.add(trade2)
            db.commit()

        # Execute: Hanya pass price untuk BTCUSDT
        current_prices = {'BTCUSDT': 67500.0}  # TP hit untuk BTCUSDT
        closed = check_paper_trades(current_prices)

        # Verify: BTCUSDT harusnya close, ETHUSDT di-skip
        assert len(closed) == 1
        assert closed[0]['pair'] == 'BTCUSDT'
        assert closed[0]['reason'] == 'TP'

        # Verify: Error log untuk ETHUSDT (capture stderr dari loguru)
        captured = capfd.readouterr()
        assert 'CRITICAL' in captured.err
        assert 'ETHUSDT' in captured.err
        assert 'Trade ID 2' in captured.err

    def test_all_pairs_present_no_error(self, capfd):
        """
        Test bahwa jika semua pair ada di price dict, tidak ada error.
        """
        from datetime import datetime, timezone

        # Setup: Buat 2 trades
        with get_session() as db:
            trade1 = PaperTrade(
                pair='BTCUSDT',
                side='LONG',
                entry_price=67000.0,
                sl_price=66800.0,
                tp_price=67400.0,
                size=0.05,
                leverage=10,
                status='OPEN',
                entry_timestamp=datetime.now(timezone.utc)
            )
            trade2 = PaperTrade(
                pair='ETHUSDT',
                side='SHORT',
                entry_price=3500.0,
                sl_price=3550.0,
                tp_price=3400.0,
                size=0.5,
                leverage=10,
                status='OPEN',
                entry_timestamp=datetime.now(timezone.utc)
            )
            db.add(trade1)
            db.add(trade2)
            db.commit()

        # Execute: Pass prices untuk semua pairs
        current_prices = {
            'BTCUSDT': 67100.0,  # Between entry and TP, no hit
            'ETHUSDT': 3350.0    # TP hit for SHORT
        }
        closed = check_paper_trades(current_prices)

        # Verify: Hanya ETHUSDT yang close
        assert len(closed) == 1
        assert closed[0]['pair'] == 'ETHUSDT'
        assert closed[0]['reason'] == 'TP'

        # Verify: Tidak ada CRITICAL log
        captured = capfd.readouterr()
        assert 'CRITICAL' not in captured.err

    def test_error_log_includes_context(self, capfd):
        """
        Test bahwa error log menyertakan context: trade ID dan available pairs.
        """
        from datetime import datetime, timezone

        # Setup
        with get_session() as db:
            trade = PaperTrade(
                pair='XRPUSDT',
                side='LONG',
                entry_price=0.5,
                sl_price=0.48,
                tp_price=0.55,
                size=100.0,
                leverage=10,
                status='OPEN',
                entry_timestamp=datetime.now(timezone.utc)
            )
            db.add(trade)
            db.commit()
            trade_id = trade.id

        # Execute: Price dict kosong
        current_prices = {'BTCUSDT': 67000.0}
        check_paper_trades(current_prices)

        # Verify: Error log menyertakan trade ID dan available pairs
        captured = capfd.readouterr()
        assert 'CRITICAL' in captured.err
        assert f'Trade ID {trade_id}' in captured.err
        assert 'BTCUSDT' in captured.err
        assert 'XRPUSDT' in captured.err
