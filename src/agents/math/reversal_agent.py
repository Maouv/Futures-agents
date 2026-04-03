"""
reversal_agent.py — Deteksi reversal signal berdasarkan SMC di H1.
"""
from typing import Optional
import pandas as pd
from pydantic import BaseModel

from src.agents.math.base_agent import BaseAgent
from src.indicators.luxalgo_smc import detect_all, OrderBlock, FairValueGap, BOSCHOCHSignal, SMCResult


class ReversalResult(BaseModel):
    """Output dari ReversalAgent."""
    signal: str         # 'LONG', 'SHORT', 'NONE'
    confidence: int     # 0-100
    ob: Optional[OrderBlock] = None       # OB yang relevan
    fvg: Optional[FairValueGap] = None    # FVG terdekat (confluence)
    bos_choch: Optional[BOSCHOCHSignal] = None  # Signal terbaru
    entry_price: Optional[float] = None   # OB midpoint jika ada signal
    reason: str


class ReversalAgent(BaseAgent):
    """
    Analisis reversal berdasarkan Order Blocks + FVG + BOS/CHOCH di H1.

    Input: DataFrame H1
    Output: ReversalResult
    """

    def run(self, df_h1: pd.DataFrame, swing_size: int = 5) -> ReversalResult:
        """
        Jalankan reversal analysis.

        Args:
            df_h1: DataFrame OHLCV H1
            swing_size: Swing size untuk deteksi SMC

        Returns:
            ReversalResult dengan signal, OB, FVG, dan entry price
        """
        if df_h1.empty or len(df_h1) < 50:
            return ReversalResult(
                signal="NONE",
                confidence=0,
                reason="Data tidak cukup (minimal 50 candle)"
            )

        # Detect semua SMC structure
        result: SMCResult = detect_all(df_h1, swing_length_ob=swing_size, swing_length_bos=swing_size)

        if not result:
            return ReversalResult(
                signal="NONE",
                confidence=0,
                reason="Gagal mendeteksi SMC structure"
            )

        current_price = df_h1["close"].iloc[-1]
        candle_high = df_h1["high"].iloc[-1]
        candle_low = df_h1["low"].iloc[-1]

        # Cari OB aktif terdekat
        nearest_bull_ob = None  # OB bullish aktif terdekat di BAWAH harga
        nearest_bear_ob = None  # OB bearish aktif terdekat di ATAS harga

        for ob in result.order_blocks:
            if not ob.mitigated:  # Hanya OB yang belum mitigated
                if ob.bias == 1 and candle_low <= ob.high and candle_high >= ob.low:
                    # Bullish OB di bawah harga
                    if nearest_bull_ob is None or ob.high > nearest_bull_ob.high:
                        nearest_bull_ob = ob
                elif ob.bias == -1 and candle_low <= ob.high and candle_high >= ob.low:
                    # Bearish OB di atas harga
                    if nearest_bear_ob is None or ob.low < nearest_bear_ob.low:
                        nearest_bear_ob = ob

        # Cek BOS/CHOCH terbaru dalam 20 candle terakhir (relaxed dari 5)
        recent_signal = None
        if result.bos_choch_signals:
            last = result.bos_choch_signals[-1]
            if last.index >= len(df_h1) - 20:  # Changed from 5 to 20
                recent_signal = last

        # Tentukan sinyal
        signal = "NONE"
        confidence = 0
        selected_ob = None
        selected_fvg = None
        entry_price = None
        reason = ""

        # LONG: ada bullish OB + ada bullish BOS/CHOCH terbaru
        if nearest_bull_ob and recent_signal and recent_signal.bias == 1:
            signal = "LONG"
            selected_ob = nearest_bull_ob
            entry_price = (nearest_bull_ob.high + nearest_bull_ob.low) / 2

            # Cari FVG bullish unfilled sebagai confluence
            for fvg in result.fair_value_gaps:
                if not fvg.filled and fvg.bias == 1:
                    selected_fvg = fvg
                    break

            # Confidence: base 60 + 20 jika ada FVG + 20 jika BOS kuat
            confidence = 60
            if selected_fvg:
                confidence += 20
            if recent_signal.type == "BOS":
                confidence += 20
            else:
                confidence += 10

            reason = f"Bullish OB at {nearest_bull_ob.low:.2f}-{nearest_bull_ob.high:.2f} + {recent_signal.type} bullish"

        # SHORT: ada bearish OB + ada bearish BOS/CHOCH terbaru
        elif nearest_bear_ob and recent_signal and recent_signal.bias == -1:
            signal = "SHORT"
            selected_ob = nearest_bear_ob
            entry_price = (nearest_bear_ob.high + nearest_bear_ob.low) / 2

            # Cari FVG bearish unfilled sebagai confluence
            for fvg in result.fair_value_gaps:
                if not fvg.filled and fvg.bias == -1:
                    selected_fvg = fvg
                    break

            # Confidence: base 60 + 20 jika ada FVG + 20 jika BOS kuat
            confidence = 60
            if selected_fvg:
                confidence += 20
            if recent_signal.type == "BOS":
                confidence += 20
            else:
                confidence += 10

            reason = f"Bearish OB at {nearest_bear_ob.low:.2f}-{nearest_bear_ob.high:.2f} + {recent_signal.type} bearish"

        else:
            reason = "Tidak ada setup valid (OB + BOS/CHOCH confluence tidak ditemukan)"

        self._log(f"Signal: {signal} | Confidence: {confidence} | {reason}")

        return ReversalResult(
            signal=signal,
            confidence=min(confidence, 100),
            ob=selected_ob,
            fvg=selected_fvg,
            bos_choch=recent_signal,
            entry_price=entry_price,
            reason=reason
        )
