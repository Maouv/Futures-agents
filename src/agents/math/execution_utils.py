# src/agents/math/execution_utils.py
"""
execution_utils.py — Shared mixin untuk ExecutionAgent dan OrderMonitor.

Berisi method-method yang dipakai oleh KEDUA class:
  - _send_alert()
  - _set_account_params()
  - _count_open_positions()

Note: _handle_ccxt_error() tidak dimasukkan ke mixin karena hanya dipakai
oleh ExecutionAgent entry logic (bukan OrderMonitor), dan ia return
ExecutionResult yang akan bikin circular import.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import ccxt

from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.logger import logger
from src.utils.mode import get_current_mode

if TYPE_CHECKING:
    pass


class ExecutionMixin:
    """
    Mixin class yang menyediakan shared utilities untuk execution layer.

    Digunakan oleh ExecutionAgent dan OrderMonitor via multiple inheritance.
    Mengasumsikan subclass punya:
      - self._notification_callback: Optional callable
      - self._log() / self._log_error() dari BaseAgent
    """
    # Type hints untuk attribute yang disediakan oleh subclass (BaseAgent + __init__)
    _notification_callback: Callable[[str], None] | None

    def _log(self, message: str) -> None: ...  # implemented by BaseAgent
    def _log_error(self, message: str) -> None: ...  # implemented by BaseAgent

    def _send_alert(self, message: str) -> None:
        """Kirim alert via callback kalau tersedia, selalu log juga."""
        self._log_error(message)
        if self._notification_callback:
            try:
                self._notification_callback(message)
            except Exception as e:
                logger.error(f"Failed to send alert notification: {e}")

    def _set_account_params(self, exchange, symbol: str, leverage: int) -> None:
        """Set leverage dan margin mode untuk symbol. Error ditoleransi (sudah diset sebelumnya)."""
        try:
            exchange.set_leverage(leverage, symbol)
            self._log(f"Leverage set to {leverage}x for {symbol}")
        except ccxt.ExchangeError as e:
            # Biasanya karena sudah diset — toleransi
            if "No need to change leverage" in str(e) or "leverage not changed" in str(e).lower():
                self._log(f"Leverage already {leverage}x for {symbol}")
            else:
                self._log_error(f"Failed to set leverage: {e}")
                raise

        try:
            exchange.set_margin_mode(settings.FUTURES_MARGIN_TYPE, symbol)
        except ccxt.ExchangeError as e:
            if "No need to change margin type" in str(e) or "margin type not changed" in str(e).lower():
                self._log(f"Margin mode already {settings.FUTURES_MARGIN_TYPE} for {symbol}")
            else:
                self._log_error(f"Failed to set margin mode: {e}")
                raise

    def _count_open_positions(self, symbol: str) -> int:
        """Hitung jumlah posisi yang sedang terbuka untuk satu pair (OPEN + PENDING_ENTRY), filtered by current mode."""
        mode = get_current_mode()
        with get_session() as db:
            count = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.pair == symbol,
                    PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
                    PaperTrade.execution_mode == mode,
                )
                .count()
            )
        return count
