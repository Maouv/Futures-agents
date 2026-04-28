"""Centralized trade calculations and DB update helpers."""

from datetime import UTC, datetime


def calculate_pnl(side: str, entry_price: float, close_price: float, size: float) -> float:
    """Calculate PnL for a trade. Works for LONG and SHORT."""
    if side == 'LONG':
        return (close_price - entry_price) * size
    return (entry_price - close_price) * size


def close_trade(trade, close_reason: str, close_price: float | None = None,
                pnl: float | None = None) -> None:
    """Close a PaperTrade in DB. Sets status, reason, timestamp, and optionally price/pnl."""
    trade.status = 'CLOSED'
    trade.close_reason = close_reason
    trade.close_timestamp = datetime.now(UTC)
    if close_price is not None:
        trade.close_price = close_price
    if pnl is not None:
        trade.pnl = pnl
