"""
metrics.py — Calculate backtest performance metrics.
"""
from typing import List
from pydantic import BaseModel


class TradeResult(BaseModel):
    """Single trade result."""
    entry_time: int          # Unix timestamp
    exit_time: int           # Unix timestamp
    entry_price: float
    exit_price: float
    side: str                # 'LONG' or 'SHORT'
    size: float              # Position size in BTC
    pnl: float               # Profit/Loss in USDT
    pnl_percent: float       # PnL percentage
    fee: float               # Total fee (entry + exit)
    exit_reason: str         # 'TP', 'SL', 'TIMEOUT'


class BacktestMetrics(BaseModel):
    """Aggregated backtest metrics."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float          # Percentage
    total_pnl: float         # USDT
    gross_profit: float      # USDT
    gross_loss: float        # USDT
    profit_factor: float     # gross_profit / gross_loss
    max_drawdown: float      # Percentage
    avg_win: float           # USDT
    avg_loss: float          # USDT
    largest_win: float       # USDT
    largest_loss: float      # USDT


def calculate_metrics(trades: List[TradeResult]) -> BacktestMetrics:
    """
    Calculate performance metrics from list of trades.

    Args:
        trades: List of TradeResult objects

    Returns:
        BacktestMetrics with calculated metrics
    """
    if not trades:
        return BacktestMetrics(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            gross_profit=0.0,
            gross_loss=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            largest_win=0.0,
            largest_loss=0.0
        )

    # Separate winning and losing trades
    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]

    total_trades = len(trades)
    winning_trades = len(winners)
    losing_trades = len(losers)
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0.0

    # Calculate PnL
    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))
    total_pnl = sum(t.pnl for t in trades)

    # Profit factor
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    # Calculate max drawdown
    equity_curve = []
    equity = 0.0
    for t in trades:
        equity += t.pnl
        equity_curve.append(equity)

    max_drawdown = 0.0
    peak = equity_curve[0] if equity_curve else 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown = ((peak - value) / peak * 100) if peak > 0 else 0.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # Average and largest trades
    avg_win = gross_profit / winning_trades if winning_trades > 0 else 0.0
    avg_loss = gross_loss / losing_trades if losing_trades > 0 else 0.0
    largest_win = max((t.pnl for t in winners), default=0.0)
    largest_loss = max((abs(t.pnl) for t in losers), default=0.0)

    return BacktestMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        total_pnl=total_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        avg_win=avg_win,
        avg_loss=avg_loss,
        largest_win=largest_win,
        largest_loss=largest_loss
    )
