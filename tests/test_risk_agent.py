"""
test_risk_agent.py — Unit tests untuk RiskAgent.
Fokus: Position size calculation (BUG #3 fix).
"""
import pytest
import pandas as pd
import numpy as np

from src.agents.math.risk_agent import RiskAgent
from src.indicators.luxalgo_smc import OrderBlock
from src.config.settings import settings


class TestRiskAgentPositionSize:
    """Test untuk verifikasi formula position size sudah benar."""

    def test_position_size_formula_correct(self):
        """
        Test bahwa position size = risk_usd / risk_distance
        TANPA leverage di numerator (BUG #3 fix).
        """
        # Setup: Entry 67000, SL 66800 (risk distance = 200)
        ob = OrderBlock(
            index=100,
            high=67050.0,
            low=66950.0,
            bias=1,
            mitigated=False
        )

        # Create dummy DataFrame untuk ATR
        dates = pd.date_range(start='2024-01-01', periods=50, freq='1h', tz='UTC')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': np.random.uniform(66000, 68000, 50),
            'high': np.random.uniform(67000, 68000, 50),
            'low': np.random.uniform(66000, 67000, 50),
            'close': np.random.uniform(66500, 67500, 50),
            'volume': np.random.uniform(100, 1000, 50)
        })

        agent = RiskAgent()
        result = agent.run(signal='LONG', order_block=ob, df=df, atr_period=14)

        # Verify position size formula
        risk_distance = abs(result.entry_price - result.sl_price)
        risk_usd = settings.RISK_PER_TRADE_USD  # From config.json
        expected_position_size = risk_usd / risk_distance

        # Position size harus sama dengan expected (tanpa leverage)
        assert result.position_size == pytest.approx(expected_position_size, rel=0.01)

        # Verify actual risk = target risk
        actual_risk = result.position_size * risk_distance
        assert actual_risk == pytest.approx(risk_usd, rel=0.01)

    def test_leverage_does_not_affect_position_size(self):
        """
        Test bahwa perubahan leverage tidak mempengaruhi position size.
        Position size hanya ditentukan oleh risk_usd dan risk_distance.
        """
        ob = OrderBlock(
            index=100,
            high=67050.0,
            low=66950.0,
            bias=1,
            mitigated=False
        )

        dates = pd.date_range(start='2024-01-01', periods=50, freq='1h', tz='UTC')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': np.random.uniform(66000, 68000, 50),
            'high': np.random.uniform(67000, 68000, 50),
            'low': np.random.uniform(66000, 67000, 50),
            'close': np.random.uniform(66500, 67500, 50),
            'volume': np.random.uniform(100, 1000, 50)
        })

        agent = RiskAgent()

        # Test dengan leverage berbeda (via settings mock)
        from src.config.settings import settings
        original_leverage = settings.FUTURES_DEFAULT_LEVERAGE

        result_10x = agent.run(signal='LONG', order_block=ob, df=df, atr_period=14)

        # Position size harus sama meski leverage berbeda
        # (margin required akan berbeda, tapi position size sama)
        risk_distance = abs(result_10x.entry_price - result_10x.sl_price)
        expected_position_size = settings.RISK_PER_TRADE_USD / risk_distance

        assert result_10x.position_size == pytest.approx(expected_position_size, rel=0.01)

    def test_margin_required_calculation(self):
        """
        Test bahwa margin required = (position_size * entry_price) / leverage.
        """
        ob = OrderBlock(
            index=100,
            high=67050.0,
            low=66950.0,
            bias=1,
            mitigated=False
        )

        dates = pd.date_range(start='2024-01-01', periods=50, freq='1h', tz='UTC')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': np.random.uniform(66000, 68000, 50),
            'high': np.random.uniform(67000, 68000, 50),
            'low': np.random.uniform(66000, 67000, 50),
            'close': np.random.uniform(66500, 67500, 50),
            'volume': np.random.uniform(100, 1000, 50)
        })

        agent = RiskAgent()
        result = agent.run(signal='LONG', order_block=ob, df=df, atr_period=14)

        # Verify margin formula
        expected_margin = (result.position_size * result.entry_price) / result.leverage
        assert result.margin_required == pytest.approx(expected_margin, rel=0.01)
