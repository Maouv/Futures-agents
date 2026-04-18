"""
confirmation_agent.py — Konfirmasi signal H1 di timeframe 15m.
"""
import pandas as pd
from pydantic import BaseModel
from typing import Optional

from src.agents.math.base_agent import BaseAgent
from src.indicators.luxalgo_smc import detect_all


class ConfirmationResult(BaseModel):
    """Output dari ConfirmationAgent."""
    confirmed: bool
    reason: str
    fvg_confluence: bool    # Ada FVG 15m yang mendukung arah?
    bos_alignment: bool     # BOS 15m searah dengan signal H1?


class ConfirmationAgent(BaseAgent):
    """
    Konfirmasi signal dari H1 menggunakan timeframe 15m.

    Input: DataFrame 15m, signal dari ReversalAgent
    Output: ConfirmationResult
    """

    def run(self, df_15m: pd.DataFrame, h1_signal: str, swing_size: int = 5) -> ConfirmationResult:
        """
        Jalankan confirmation analysis.

        Args:
            df_15m: DataFrame OHLCV 15m
            h1_signal: Signal dari H1 ('LONG' atau 'SHORT')
            swing_size: Swing size untuk deteksi SMC

        Returns:
            ConfirmationResult dengan status konfirmasi
        """
        if df_15m.empty or len(df_15m) < 50:
            return ConfirmationResult(
                confirmed=False,
                reason="Data 15m tidak cukup",
                fvg_confluence=False,
                bos_alignment=False
            )

        if h1_signal not in ["LONG", "SHORT"]:
            return ConfirmationResult(
                confirmed=False,
                reason="Signal H1 tidak valid",
                fvg_confluence=False,
                bos_alignment=False
            )

        # Detect SMC di 15m
        result = detect_all(df_15m, swing_length_ob=swing_size, swing_length_bos=swing_size)

        if not result:
            return ConfirmationResult(
                confirmed=False,
                reason="Gagal mendeteksi SMC di 15m",
                fvg_confluence=False,
                bos_alignment=False
            )

        # Cek BOS/CHOCH alignment menggunakan confirmation candle (broken_index)
        bos_alignment = False
        if result.bos_choch_signals:
            # Ambil signal terakhir dalam 20 candle terakhir (window diperlebar dari 10 ke 20)
            for sig in reversed(result.bos_choch_signals):
                if sig.broken_index >= len(df_15m) - 20:
                    # Cek apakah searah dengan signal H1
                    expected_bias = 1 if h1_signal == "LONG" else -1
                    if sig.bias == expected_bias:
                        bos_alignment = True
                        break

        # Cek FVG confluence
        fvg_confluence = False
        expected_bias = 1 if h1_signal == "LONG" else -1
        for fvg in result.fair_value_gaps:
            if not fvg.filled and fvg.bias == expected_bias:
                fvg_confluence = True
                break

        # Tentukan konfirmasi
        confirmed = bos_alignment or fvg_confluence

        # Build reason
        reasons = []
        if bos_alignment:
            reasons.append("BOS 15m searah")
        if fvg_confluence:
            reasons.append("FVG 15m mendukung")

        if confirmed:
            reason = " | ".join(reasons)
        else:
            reason = "Tidak ada konfirmasi di 15m"

        self._log(f"Confirmed: {confirmed} | {reason}")

        return ConfirmationResult(
            confirmed=confirmed,
            reason=reason,
            fvg_confluence=fvg_confluence,
            bos_alignment=bos_alignment
        )
