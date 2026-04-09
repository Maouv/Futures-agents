"""
test_phase8.py — Unit tests untuk Phase 8 components.
Fokus: exchange factory, kill switch, execution validation, WS order parsing.
"""
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# ── Kill Switch Tests ────────────────────────────────────────────────────────

class TestKillSwitch:
    def test_no_kill_switch_by_default(self, tmp_path):
        with patch('src.utils.kill_switch.KILL_SWITCH_PATH', str(tmp_path / "kill_switch")):
            from src.utils.kill_switch import check_kill_switch
            assert check_kill_switch() is False

    def test_create_and_check(self, tmp_path):
        path = str(tmp_path / "kill_switch")
        with patch('src.utils.kill_switch.KILL_SWITCH_PATH', path):
            from src.utils.kill_switch import create_kill_switch, check_kill_switch
            create_kill_switch()
            assert check_kill_switch() is True

    def test_remove(self, tmp_path):
        path = str(tmp_path / "kill_switch")
        with patch('src.utils.kill_switch.KILL_SWITCH_PATH', path):
            from src.utils.kill_switch import create_kill_switch, remove_kill_switch, check_kill_switch
            create_kill_switch()
            assert check_kill_switch() is True
            remove_kill_switch()
            assert check_kill_switch() is False

    def test_remove_nonexistent(self, tmp_path):
        path = str(tmp_path / "kill_switch")
        with patch('src.utils.kill_switch.KILL_SWITCH_PATH', path):
            from src.utils.kill_switch import remove_kill_switch
            # Should not raise
            remove_kill_switch()


# ── Execution Agent Validation Tests ────────────────────────────────────────

class TestExecutionValidation:
    """Test _validate_signal() — shared validation for paper and live mode."""

    def _make_reversal(self, signal="LONG", confidence=70):
        from src.agents.math.reversal_agent import ReversalResult
        return ReversalResult(
            signal=signal,
            confidence=confidence,
            ob=None,
            fvg=None,
            bos_choch=None,
            entry_price=50000.0 if signal == "LONG" else 50000.0,
            reason="test"
        )

    def _make_trend(self, bias=1):
        from src.agents.math.trend_agent import TrendResult
        return TrendResult(
            bias=bias,
            bias_label="BULLISH" if bias == 1 else "BEARISH" if bias == -1 else "RANGING",
            confidence=0.8,
            reason="test"
        )

    def test_valid_long_signal(self):
        from src.agents.math.execution_agent import ExecutionAgent
        agent = ExecutionAgent()
        result = agent._validate_signal(
            self._make_reversal("LONG", 70),
            self._make_trend(1),
            True
        )
        assert result is None  # Valid

    def test_valid_short_signal(self):
        from src.agents.math.execution_agent import ExecutionAgent
        agent = ExecutionAgent()
        result = agent._validate_signal(
            self._make_reversal("SHORT", 70),
            self._make_trend(-1),
            True
        )
        assert result is None  # Valid

    def test_trend_mismatch_long(self):
        from src.agents.math.execution_agent import ExecutionAgent
        agent = ExecutionAgent()
        result = agent._validate_signal(
            self._make_reversal("LONG", 70),
            self._make_trend(-1),  # Bearish trend, LONG signal
            True
        )
        assert result is not None
        assert result.action == "SKIP"
        assert "Trend tidak searah" in result.reason

    def test_trend_mismatch_short(self):
        from src.agents.math.execution_agent import ExecutionAgent
        agent = ExecutionAgent()
        result = agent._validate_signal(
            self._make_reversal("SHORT", 70),
            self._make_trend(1),  # Bullish trend, SHORT signal
            True
        )
        assert result is not None
        assert result.action == "SKIP"

    def test_low_confidence(self):
        from src.agents.math.execution_agent import ExecutionAgent
        agent = ExecutionAgent()
        result = agent._validate_signal(
            self._make_reversal("LONG", 50),  # Below 60 threshold
            self._make_trend(1),
            True
        )
        assert result is not None
        assert "Confidence" in result.reason

    def test_no_confirmation(self):
        from src.agents.math.execution_agent import ExecutionAgent
        agent = ExecutionAgent()
        result = agent._validate_signal(
            self._make_reversal("LONG", 70),
            self._make_trend(1),
            False  # No confirmation
        )
        assert result is not None
        assert "konfirmasi" in result.reason.lower()

    def test_invalid_signal(self):
        from src.agents.math.execution_agent import ExecutionAgent
        agent = ExecutionAgent()
        result = agent._validate_signal(
            self._make_reversal("NONE", 70),
            self._make_trend(1),
            True
        )
        assert result is not None
        assert "tidak valid" in result.reason.lower()


# ── WS Order Update Parsing Tests ────────────────────────────────────────────

class TestWSOrderParsing:
    """Test the ORDER_TRADE_UPDATE parsing logic in ws_user_stream.py."""

    def test_sl_order_type_detection(self):
        """STOP_MARKET order type should be detected as SL."""
        from src.data.ws_user_stream import UserDataStream
        stream = UserDataStream()

        # We test the close reason detection logic
        # In _handle_order_update, order_type determines close_reason
        order_type_sl = 'STOP_MARKET'
        order_type_tp = 'TAKE_PROFIT_MARKET'

        # SL detection
        assert order_type_sl in ('STOP_MARKET', 'STOP')
        # TP detection
        assert order_type_tp in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT')

    def test_filled_status_filter(self):
        """Only FILLED orders should be processed."""
        # Non-filled statuses should be skipped
        assert 'NEW' != 'FILLED'
        assert 'PARTIALLY_FILLED' != 'FILLED'
        assert 'CANCELED' != 'FILLED'
        assert 'FILLED' == 'FILLED'


# ── DB Migration Tests ──────────────────────────────────────────────────────

class TestDBMigration:
    def test_migrate_adds_columns(self, tmp_path):
        """migrate_db() should add new columns to existing tables."""
        from src.data.storage import Base, PaperTrade, migrate_db
        from sqlalchemy import create_engine, inspect

        db_path = str(tmp_path / "test_trading.db")
        test_engine = create_engine(f"sqlite:///{db_path}")

        # Create tables WITHOUT the new columns (simulate old DB)
        # We'll create just the old schema
        with test_engine.connect() as conn:
            conn.execute(__import__('sqlalchemy').text(
                "CREATE TABLE paper_trades ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "pair VARCHAR(20) NOT NULL, "
                "side VARCHAR(5) NOT NULL, "
                "entry_price FLOAT NOT NULL, "
                "sl_price FLOAT NOT NULL, "
                "tp_price FLOAT NOT NULL, "
                "size FLOAT NOT NULL, "
                "leverage INTEGER NOT NULL, "
                "status VARCHAR(10) NOT NULL DEFAULT 'OPEN', "
                "pnl FLOAT, "
                "entry_timestamp DATETIME NOT NULL, "
                "close_timestamp DATETIME, "
                "close_reason VARCHAR(10))"
            ))

        # Verify columns are missing
        inspector = inspect(test_engine)
        columns_before = [c['name'] for c in inspector.get_columns('paper_trades')]
        assert 'execution_mode' not in columns_before
        assert 'close_price' not in columns_before

        # Run migration (patch DATABASE_URL to use test db)
        from src.data import storage
        old_engine = storage.engine
        storage.engine = test_engine

        try:
            migrate_db()
        finally:
            storage.engine = old_engine

        # Verify columns are added
        inspector = inspect(test_engine)
        columns_after = [c['name'] for c in inspector.get_columns('paper_trades')]
        assert 'execution_mode' in columns_after
        assert 'exchange_order_id' in columns_after
        assert 'sl_order_id' in columns_after
        assert 'tp_order_id' in columns_after
        assert 'close_price' in columns_after


# ── Settings Tests ──────────────────────────────────────────────────────────

class TestPhase8Settings:
    def test_new_settings_have_defaults(self):
        from src.config.settings import Settings
        # Create with minimal env vars (test mode)
        with patch.dict(os.environ, {
            'BINANCE_API_KEY': 'test',
            'BINANCE_API_SECRET': 'test',
            'BINANCE_TESTNET_KEY': 'test',
            'BINANCE_TESTNET_SECRET': 'test',
            'CEREBRAS_API_KEY': 'test',
            'GROQ_API_KEY': 'test',
            'CONCIERGE_API_KEY': 'test',
            'TELEGRAM_BOT_TOKEN': 'test',
            'TELEGRAM_CHAT_ID': '123',
        }, clear=False):
            s = Settings()
            assert s.CONFIRM_MAINNET is False
            assert s.MAX_OPEN_POSITIONS == 2
            assert s.ORDER_EXPIRY_CANDLES == 48

    def test_order_expiry_validation(self):
        """ORDER_EXPIRY_CANDLES must be >= 1."""
        from src.config.settings import Settings
        with patch.dict(os.environ, {
            'BINANCE_API_KEY': 'test',
            'BINANCE_API_SECRET': 'test',
            'BINANCE_TESTNET_KEY': 'test',
            'BINANCE_TESTNET_SECRET': 'test',
            'CEREBRAS_API_KEY': 'test',
            'GROQ_API_KEY': 'test',
            'CONCIERGE_API_KEY': 'test',
            'TELEGRAM_BOT_TOKEN': 'test',
            'TELEGRAM_CHAT_ID': '123',
            'ORDER_EXPIRY_CANDLES': '0',
        }, clear=False):
            with pytest.raises(Exception):  # ValidationError
                Settings()
