"""
reversal_agent.py — Deteksi reversal signal berdasarkan SMC di H1.
"""
from typing import Optional
import pandas as pd
from pydantic import BaseModel

from src.agents.math.base_agent import BaseAgent
from src.indicators.helpers import calculate_atr
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

        # Cari OB aktif terdekat berdasarkan proximity (2x ATR)
        atr = calculate_atr(df_h1).iloc[-1]
        max_distance = atr * 2  # FLAG 4: gunakan 2x, bukan 3x

        nearest_bull_ob = None  # OB bullish aktif terdekat di BAWAH harga
        nearest_bear_ob = None  # OB bearish aktif terdekat di ATAS harga

        for ob in result.order_blocks:
            if ob.mitigated:
                continue

            if ob.bias == 1:  # Bullish OB: harus di bawah current_price
                if current_price > ob.low:  # OB ada di bawah (atau price baru masuk)
                    distance = max(0, current_price - ob.high)  # 0 jika sudah dalam OB
                    if distance <= max_distance:
                        if nearest_bull_ob is None or ob.high > nearest_bull_ob.high:
                            nearest_bull_ob = ob
                            self._log(f"Bull OB candidate: {ob.low:.2f}-{ob.high:.2f} | distance: {distance:.4f} | ATR: {atr:.4f}")

            elif ob.bias == -1:  # Bearish OB: harus di atas current_price
                if current_price < ob.high:  # OB ada di atas (atau price baru masuk)
                    distance = max(0, ob.low - current_price)  # 0 jika sudah dalam OB
                    if distance <= max_distance:
                        if nearest_bear_ob is None or ob.low < nearest_bear_ob.low:
                            nearest_bear_ob = ob
                            self._log(f"Bear OB candidate: {ob.low:.2f}-{ob.high:.2f} | distance: {distance:.4f} | ATR: {atr:.4f}")

        # Cek BOS/CHOCH terbaru dalam 35 candle terakhir menggunakan confirmation candle (broken_index)
        recent_signal = None
        if result.bos_choch_signals:
            last = result.bos_choch_signals[-1]
            if last.broken_index >= len(df_h1) - 35:
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
