"""
execution_agent.py — Eksekusi trade (PAPER MODE ONLY).
"""
import os
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from src.agents.math.base_agent import BaseAgent
from src.data.storage import PaperTrade, get_session
from src.agents.math.risk_agent import RiskResult
from src.agents.math.reversal_agent import ReversalResult
from src.agents.math.trend_agent import TrendResult


class ExecutionResult(BaseModel):
    """Output dari ExecutionAgent."""
    action: str         # 'OPEN', 'SKIP'
    reason: str
    trade_id: Optional[int] = None  # ID dari paper_trades jika OPEN


class ExecutionAgent(BaseAgent):
    """
    Eksekusi trade berdasarkan hasil analisis.

    PAPER MODE: INSERT ke database paper_trades
    LIVE MODE: Akan diimplementasi di Phase 8
    """

    def run(
        self,
        symbol: str,
        risk_result: RiskResult,
        reversal_result: ReversalResult,
        trend_result: TrendResult,
        confirmation_confirmed: bool
    ) -> ExecutionResult:
        """
        Jalankan eksekusi trade.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            risk_result: Output dari RiskAgent
            reversal_result: Output dari ReversalAgent
            trend_result: Output dari TrendAgent
            confirmation_confirmed: Hasil konfirmasi dari ConfirmationAgent

        Returns:
            ExecutionResult dengan action dan trade_id
        """
        # GUARD CLAUSE WAJIB ADA
        if os.getenv("EXECUTION_MODE") == "live":
            # Phase 8 — belum diimplementasi
            raise NotImplementedError("Live execution diimplementasi di Phase 8")

        # Validasi sebelum eksekusi
        # 1. Trend harus searah dengan signal
        if reversal_result.signal == "LONG" and trend_result.bias != 1:
            return ExecutionResult(
                action="SKIP",
                reason=f"Trend tidak searah (H4={trend_result.bias_label}, signal=LONG)"
            )

        if reversal_result.signal == "SHORT" and trend_result.bias != -1:
            return ExecutionResult(
                action="SKIP",
                reason=f"Trend tidak searah (H4={trend_result.bias_label}, signal=SHORT)"
            )

        # 2. Confidence minimal 60
        if reversal_result.confidence < 60:
            return ExecutionResult(
                action="SKIP",
                reason=f"Confidence terlalu rendah ({reversal_result.confidence}%)"
            )

        # 3. Konfirmasi 15m harus positif
        if not confirmation_confirmed:
            return ExecutionResult(
                action="SKIP",
                reason="Tidak ada konfirmasi di timeframe 15m"
            )

        # 4. Signal harus valid
        if reversal_result.signal not in ["LONG", "SHORT"]:
            return ExecutionResult(
                action="SKIP",
                reason=f"Signal tidak valid: {reversal_result.signal}"
            )

        # Paper mode: INSERT ke DB
        try:
            with get_session() as db:
                trade = PaperTrade(
                    pair=symbol,
                    side=reversal_result.signal,
                    entry_price=risk_result.entry_price,
                    sl_price=risk_result.sl_price,
                    tp_price=risk_result.tp_price,
                    size=risk_result.position_size,
                    leverage=risk_result.leverage,
                    status='OPEN',
                )
                db.add(trade)
                db.flush()  # Flush untuk mendapatkan ID
                trade_id = trade.id

            self._log(
                f"✅ PAPER TRADE OPENED | ID: {trade_id} | "
                f"{symbol} {reversal_result.signal} | "
                f"Entry: {risk_result.entry_price:.2f} | "
                f"SL: {risk_result.sl_price:.2f} | TP: {risk_result.tp_price:.2f}"
            )

            return ExecutionResult(
                action="OPEN",
                reason=f"Trade opened in PAPER mode",
                trade_id=trade_id
            )

        except Exception as e:
            self._log_error(f"Gagal menyimpan paper trade: {e}")
            return ExecutionResult(
                action="SKIP",
                reason=f"Error: {str(e)}"
            )
