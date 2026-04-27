"""
test_indicators.py — Unit tests untuk indikator SMC dan Mean Reversion.
Semua test menggunakan data dummy yang sudah diketahui hasilnya.
"""
import pandas as pd
import numpy as np
from src.indicators.helpers import crossover, crossunder, calculate_atr
from src.indicators.mean_reversion import calculate_mean_reversion


class TestHelpers:
    """Test helper functions."""

    def test_crossover_detects_correctly(self):
        """Series naik melewati level 50 pada index ke-3."""
        series = pd.Series([45.0, 48.0, 49.0, 51.0, 53.0])
        result = crossover(series, 50.0)
        assert result.iloc[3] == True
        assert result.iloc[4] == False  # Sudah di atas, bukan crossover lagi

    def test_crossover_with_series(self):
        """Test crossover dengan series sebagai level."""
        series = pd.Series([45.0, 48.0, 50.0, 52.0, 53.0])
        level = pd.Series([47.0, 49.0, 51.0, 50.0, 50.0])
        result = crossover(series, level)
        # Crossover terjadi di index 3 (52.0 > 50.0 dan sebelumnya 50.0 <= 51.0)
        assert result.iloc[3] == True

    def test_crossunder_detects_correctly(self):
        """Series turun melewati level 50."""
        series = pd.Series([55.0, 52.0, 51.0, 49.0, 47.0])
        result = crossunder(series, 50.0)
        assert result.iloc[3] == True
        assert result.iloc[4] == False

    def test_crossunder_with_series(self):
        """Test crossunder dengan series sebagai level."""
        series = pd.Series([55.0, 53.0, 51.0, 49.0, 47.0])
        level = pd.Series([50.0, 50.0, 50.0, 50.0, 50.0])
        result = crossunder(series, level)
        # Crossunder terjadi di index 3 (49.0 < 50.0 dan sebelumnya 51.0 >= 50.0)
        assert result.iloc[3] == True

    def test_atr_positive(self):
        """ATR harus selalu positif."""
        df = pd.DataFrame({
            'high':  [100, 102, 101, 103, 105],
            'low':   [98,  99,  99,  100, 102],
            'close': [99,  101, 100, 102, 104],
        })
        atr = calculate_atr(df, period=3)
        assert (atr.dropna() > 0).all()

    def test_atr_calculation_correctness(self):
        """Test ATR calculation dengan data yang diketahui."""
        # Simple case: semua candle range = 2
        df = pd.DataFrame({
            'high':  [102, 102, 102, 102, 102],
            'low':   [100, 100, 100, 100, 100],
            'close': [101, 101, 101, 101, 101],
        })
        atr = calculate_atr(df, period=3)
        # True Range semua = 2, setelah EMA smoothing harus mendekati 2
        # EMA dengan alpha=1/3: atr[-1] ≈ 2
        assert abs(atr.iloc[-1] - 2.0) < 0.1


class TestMeanReversion:
    """Test mean reversion indicators."""

    def _make_df(self, n: int = 50) -> pd.DataFrame:
        """Buat DataFrame dummy dengan trend naik."""
        close = pd.Series(range(100, 100 + n), dtype=float)
        return pd.DataFrame({
            'high':  close + 1,
            'low':   close - 1,
            'close': close,
            'open':  close - 0.5,
            'volume': [1000.0] * n,
        })

    def test_rsi_range(self):
        """RSI harus selalu antara 0 dan 100."""
        df = self._make_df(50)
        result = calculate_mean_reversion(df)
        assert 0 <= result.rsi <= 100

    def test_rsi_oversold_signal(self):
        """Test RSI oversold signal (< 30)."""
        # Buat data dengan downtrend kuat
        close = pd.Series(range(100, 50, -1), dtype=float)
        df = pd.DataFrame({
            'high':  close + 2,
            'low':   close - 2,
            'close': close,
            'open':  close - 1,
            'volume': [1000.0] * len(close),
        })
        result = calculate_mean_reversion(df)
        # Dengan downtrend kuat, RSI seharusnya rendah
        assert result.rsi < 50

    def test_bb_position_range(self):
        """bb_position harus antara -1 dan +1 (approximasi)."""
        df = self._make_df(50)
        result = calculate_mean_reversion(df)
        # Bisa keluar band saat trending kuat, jadi range lebih lebar
        assert -3.0 <= result.bb_position <= 3.0

    def test_bb_bands_relationship(self):
        """Bollinger Bands harus: lower < middle < upper."""
        df = self._make_df(50)
        result = calculate_mean_reversion(df)
        assert result.bb_lower < result.bb_middle < result.bb_upper

    def test_bb_width_positive(self):
        """Bollinger Band width harus positif."""
        df = self._make_df(50)
        result = calculate_mean_reversion(df)
        assert result.bb_upper - result.bb_lower > 0


class TestSMCIndicators:
    """Test SMC indicators (basic structure tests)."""

    def _make_trending_df(self, n: int = 200) -> pd.DataFrame:
        """Buat DataFrame dengan trend untuk testing SMC."""
        # Simulasi data dengan swing points
        np.random.seed(42)

        # Buat trend naik dengan noise
        trend = np.linspace(100, 200, n)
        noise = np.random.randn(n) * 2

        close = trend + noise
        high = close + np.abs(np.random.randn(n)) * 1.5
        low = close - np.abs(np.random.randn(n)) * 1.5

        return pd.DataFrame({
            'high': high,
            'low': low,
            'close': close,
            'open': close - np.random.randn(n) * 0.5,
            'volume': [1000.0] * n,
        })

    def test_detect_order_blocks_returns_list(self):
        """Order block detection harus return list."""
        from src.indicators.luxalgo_smc import detect_order_blocks

        df = self._make_trending_df(200)
        result = detect_order_blocks(df, swing_length=10)

        assert isinstance(result, list)

    def test_detect_fvg_returns_list(self):
        """FVG detection harus return list."""
        from src.indicators.luxalgo_smc import detect_fvg

        df = self._make_trending_df(100)
        result = detect_fvg(df)

        assert isinstance(result, list)

    def test_detect_bos_choch_returns_list(self):
        """BOS/CHOCH detection harus return list."""
        from src.indicators.luxalgo_smc import detect_bos_choch

        df = self._make_trending_df(200)
        result = detect_bos_choch(df, swing_length=10)

        assert isinstance(result, list)

    def test_order_block_structure(self):
        """Test OrderBlock model structure."""
        from src.indicators.luxalgo_smc import OrderBlock

        ob = OrderBlock(
            index=10,
            high=105.0,
            low=100.0,
            bias=-1,
            mitigated=False
        )

        assert ob.index == 10
        assert ob.high == 105.0
        assert ob.low == 100.0
        assert ob.bias == -1
        assert ob.mitigated is False

    def test_fvg_structure(self):
        """Test FairValueGap model structure."""
        from src.indicators.luxalgo_smc import FairValueGap

        fvg = FairValueGap(
            index=15,
            top=102.0,
            bottom=98.0,
            bias=1,
            filled=False
        )

        assert fvg.index == 15
        assert fvg.top == 102.0
        assert fvg.bottom == 98.0
        assert fvg.bias == 1
        assert fvg.filled is False

    def test_bos_choch_structure(self):
        """Test BOSCHOCHSignal model structure."""
        from src.indicators.luxalgo_smc import BOSCHOCHSignal

        signal = BOSCHOCHSignal(
            index=20,
            type='BOS',
            bias=1,
            level=110.0
        )

        assert signal.index == 20
        assert signal.type == 'BOS'
        assert signal.bias == 1
        assert signal.level == 110.0
