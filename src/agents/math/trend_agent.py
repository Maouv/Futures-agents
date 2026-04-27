"""
trend_agent.py — Analisis trend H4 menggunakan BOS/CHOCH.
"""
import pandas as pd
from pydantic import BaseModel

from src.agents.math.base_agent import BaseAgent
from src.indicators.luxalgo_smc import detect_bos_choch


class TrendResult(BaseModel):
    """Output dari TrendAgent."""
    bias: int           # 1=BULLISH, -1=BEARISH, 0=RANGING
    bias_label: str     # 'BULLISH', 'BEARISH', 'RANGING'
    confidence: float   # 0.0 - 1.0
    reason: str         # Penjelasan singkat


class TrendAgent(BaseAgent):
    """
    Analisis trend berdasarkan BOS/CHOCH di timeframe H4.

    Input: DataFrame H4
    Output: TrendResult
    """

    def run(self, df_h4: pd.DataFrame, swing_size: int = 10) -> TrendResult:
        """
        Jalankan trend analysis.

        Args:
            df_h4: DataFrame OHLCV H4
            swing_size: Swing size untuk deteksi BOS/CHOCH

        Returns:
            TrendResult dengan bias, confidence, dan reason
        """
        if df_h4.empty or len(df_h4) < 20:
            self._log(f"Data tidak cukup: {len(df_h4)} candles")
            return TrendResult(
                bias=0,
                bias_label="RANGING",
                confidence=0.0,
                reason="Data tidak cukup (minimal 20 candle)"
            )

        # Detect BOS/CHOCH
        signals = detect_bos_choch(df_h4, swing_length=swing_size)

        self._log(f"Detected {len(signals)} BOS/CHOCH signals from {len(df_h4)} candles")

        if not signals:
            return TrendResult(
                bias=0,
                bias_label="RANGING",
                confidence=0.0,
                reason="Tidak ada signal BOS/CHOCH"
            )

        # Ambil signal terakhir dalam 100 candle terakhir (relaxed untuk menangkap signal lebih luas)
        last_signal = None

        for sig in reversed(signals):
            if sig.index >= len(df_h4) - 100:  # Changed from 20 to 100
                last_signal = sig
                break

        if last_signal is None:
            return TrendResult(
                bias=0,
                bias_label="RANGING",
                confidence=0.0,
                reason="Tidak ada signal dalam 100 candle terakhir"
            )

        # Tentukan bias dari signal terakhir
        bias = last_signal.bias  # 1 = BULLISH, -1 = BEARISH

        # Hitung confidence: jumlah sinyal searah / total sinyal dalam 100 candle terakhir
        recent_signals = [s for s in signals if s.index >= len(df_h4) - 100]

        if len(recent_signals) == 0:
            confidence = 0.5
        else:
            same_direction = sum(1 for s in recent_signals if s.bias == bias)
            confidence = same_direction / len(recent_signals)

        bias_label = "BULLISH" if bias == 1 else "BEARISH"
        reason = f"BOS/CHOCH {bias_label} detected at candle {last_signal.index}"

        self._log(f"Trend: {bias_label} | Confidence: {confidence:.2f} | {reason}")

        return TrendResult(
            bias=bias,
            bias_label=bias_label,
            confidence=confidence,
            reason=reason
        )
