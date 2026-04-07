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
    exit_reason: str         # 'TP', 'SL', 'TIMEOUT', 'SKIPPED'
    # Additional fields for CSV export
    sl_price: float = 0.0
    tp_price: float = 0.0
    candles_held: int = 0
    atr: float = 0.0
    ob_high: float = 0.0
    ob_low: float = 0.0
    trend_bias: str = "RANGING"  # 'BULLISH', 'BEARISH', 'RANGING'
    confidence: int = 0
    # New fields for RL training
    bos_type: str = "NONE"        # 'BULLISH_BOS', 'BULLISH_CHOCH', 'BEARISH_BOS', 'BEARISH_CHOCH', 'NONE'
    ob_size: float = 0.0          # OB high - low
    distance_to_ob: float = 0.0   # Distance from entry to OB midpoint
    fvg_present: bool = False     # Is FVG present as confluence
    candle_body_ratio: float = 0.0  # abs(close - open) / (high - low)
    hour_of_day: int = 0          # Hour in UTC (0-23)
    consecutive_losses: int = 0   # Consecutive losses before this trade
    time_since_last_trade: int = 0  # Minutes since last trade
    current_drawdown_pct: float = 0.0  # Current drawdown percentage at entry


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


def calculate_metrics(trades: List[TradeResult], initial_balance: float = 10_000.0) -> BacktestMetrics:
    """
    Calculate performance metrics from list of trades.
    SKIPPED trades are excluded from metrics calculation.

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

    # Filter SKIPPED trades - only include executed trades in metrics
    executed_trades = [t for t in trades if t.exit_reason != 'SKIPPED']

    if not executed_trades:
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

    # Separate winning and losing trades (only executed trades)
    winners = [t for t in executed_trades if t.pnl > 0]
    losers = [t for t in executed_trades if t.pnl < 0]  # Exclude pnl=0 (break-even)

    total_trades = len(executed_trades)
    winning_trades = len(winners)
    losing_trades = len(losers)
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0.0

    # Calculate PnL
    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))
    total_pnl = sum(t.pnl for t in executed_trades)

    # Profit factor
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    # Calculate max drawdown (based on executed trades only)
    equity_curve = []
    equity = initial_balance
    for t in executed_trades:
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
