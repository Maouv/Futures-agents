#!/usr/bin/env python3
"""
Test untuk memverifikasi SKIPPED trades tidak dihitung di metrics.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.backtest.metrics import TradeResult, calculate_metrics


def test_skipped_trades_excluded():
    """Test bahwa SKIPPED trades tidak dihitung di metrics."""
    print("=" * 60)
    print("TEST: SKIPPED TRADES EXCLUSION")
    print("=" * 60)

    # Create test trades
    trades = []

    # 3 winning trades (TP)
    for i in range(3):
        trades.append(TradeResult(
            entry_time=1704067200000 + (i * 3600000),
            exit_time=1704070800000 + (i * 3600000),
            entry_price=42000.00,
            exit_price=42500.00,
            side='LONG',
            size=0.001,
            pnl=5.0,
            pnl_percent=0.5,
            fee=0.04,
            exit_reason='TP',
            trend_bias='BULLISH',
            confidence=80,
            atr=300.0,
            ob_high=42050.0,
            ob_low=41950.0,
            bos_type='BULLISH_BOS',
            ob_size=100.0,
            distance_to_ob=25.0,
            rsi=35.5,
            fvg_present=True,
            candle_body_ratio=0.65,
            hour_of_day=14,
            consecutive_losses=0,
            time_since_last_trade=60,
            current_drawdown_pct=0.0,
        ))

    # 2 losing trades (SL)
    for i in range(2):
        trades.append(TradeResult(
            entry_time=1704082800000 + (i * 3600000),
            exit_time=1704086400000 + (i * 3600000),
            entry_price=42000.00,
            exit_price=41800.00,
            side='LONG',
            size=0.001,
            pnl=-2.0,
            pnl_percent=-0.2,
            fee=0.04,
            exit_reason='SL',
            trend_bias='BULLISH',
            confidence=70,
            atr=300.0,
            ob_high=42050.0,
            ob_low=41950.0,
            bos_type='BULLISH_CHOCH',
            ob_size=100.0,
            distance_to_ob=25.0,
            rsi=65.5,
            fvg_present=False,
            candle_body_ratio=0.45,
            hour_of_day=15,
            consecutive_losses=i + 1,
            time_since_last_trade=120,
            current_drawdown_pct=2.0,
        ))

    # 5 SKIPPED trades (harusnya tidak dihitung)
    for i in range(5):
        trades.append(TradeResult(
            entry_time=1704100000000 + (i * 3600000),
            exit_time=1704100000000 + (i * 3600000),
            entry_price=42000.00,
            exit_price=42000.00,
            side='LONG',
            size=0.0,
            pnl=0.0,
            pnl_percent=0.0,
            fee=0.0,
            exit_reason='SKIPPED',
            trend_bias='BULLISH',
            confidence=75,
            atr=300.0,
            ob_high=42050.0,
            ob_low=41950.0,
            bos_type='BULLISH_BOS',
            ob_size=100.0,
            distance_to_ob=25.0,
            rsi=40.0,
            fvg_present=True,
            candle_body_ratio=0.0,
            hour_of_day=16,
            consecutive_losses=0,
            time_since_last_trade=180,
            current_drawdown_pct=5.0,
        ))

    print(f"\nTotal trades in list: {len(trades)}")
    print("  - TP trades: 3")
    print("  - SL trades: 2")
    print("  - SKIPPED trades: 5")

    # Calculate metrics
    metrics = calculate_metrics(trades, initial_balance=10000.0)

    print("\nCalculated Metrics:")
    print(f"  Total Trades:      {metrics.total_trades}")
    print(f"  Winning Trades:    {metrics.winning_trades}")
    print(f"  Losing Trades:     {metrics.losing_trades}")
    print(f"  Win Rate:          {metrics.win_rate:.2f}%")
    print(f"  Total PnL:         {metrics.total_pnl:.2f} USDT")
    print(f"  Gross Profit:      {metrics.gross_profit:.2f} USDT")
    print(f"  Gross Loss:        {metrics.gross_loss:.2f} USDT")
    print(f"  Avg Win:           {metrics.avg_win:.2f} USDT")
    print(f"  Avg Loss:          {metrics.avg_loss:.2f} USDT")

    # Verify results
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    success = True

    # Expected: 5 trades (3 TP + 2 SL), SKIPPED excluded
    if metrics.total_trades == 5:
        print(f"✓ Total trades correct: {metrics.total_trades} (expected 5)")
    else:
        print(f"✗ Total trades WRONG: {metrics.total_trades} (expected 5)")
        success = False

    if metrics.winning_trades == 3:
        print(f"✓ Winning trades correct: {metrics.winning_trades} (expected 3)")
    else:
        print(f"✗ Winning trades WRONG: {metrics.winning_trades} (expected 3)")
        success = False

    if metrics.losing_trades == 2:
        print(f"✓ Losing trades correct: {metrics.losing_trades} (expected 2)")
    else:
        print(f"✗ Losing trades WRONG: {metrics.losing_trades} (expected 2)")
        success = False

    # Win rate: 3/5 = 60%
    if abs(metrics.win_rate - 60.0) < 0.01:
        print(f"✓ Win rate correct: {metrics.win_rate:.2f}% (expected 60%)")
    else:
        print(f"✗ Win rate WRONG: {metrics.win_rate:.2f}% (expected 60%)")
        success = False

    # Total PnL: 3*5 - 2*2 = 11 USDT
    if abs(metrics.total_pnl - 11.0) < 0.01:
        print(f"✓ Total PnL correct: {metrics.total_pnl:.2f} USDT (expected 11.0)")
    else:
        print(f"✗ Total PnL WRONG: {metrics.total_pnl:.2f} USDT (expected 11.0)")
        success = False

    # Gross profit: 3*5 = 15 USDT
    if abs(metrics.gross_profit - 15.0) < 0.01:
        print(f"✓ Gross profit correct: {metrics.gross_profit:.2f} USDT (expected 15.0)")
    else:
        print(f"✗ Gross profit WRONG: {metrics.gross_profit:.2f} USDT (expected 15.0)")
        success = False

    # Gross loss: 2*2 = 4 USDT
    if abs(metrics.gross_loss - 4.0) < 0.01:
        print(f"✓ Gross loss correct: {metrics.gross_loss:.2f} USDT (expected 4.0)")
    else:
        print(f"✗ Gross loss WRONG: {metrics.gross_loss:.2f} USDT (expected 4.0)")
        success = False

    # Avg win: 15/3 = 5 USDT
    if abs(metrics.avg_win - 5.0) < 0.01:
        print(f"✓ Avg win correct: {metrics.avg_win:.2f} USDT (expected 5.0)")
    else:
        print(f"✗ Avg win WRONG: {metrics.avg_win:.2f} USDT (expected 5.0)")
        success = False

    # Avg loss: 4/2 = 2 USDT
    if abs(metrics.avg_loss - 2.0) < 0.01:
        print(f"✓ Avg loss correct: {metrics.avg_loss:.2f} USDT (expected 2.0)")
    else:
        print(f"✗ Avg loss WRONG: {metrics.avg_loss:.2f} USDT (expected 2.0)")
        success = False

    print("=" * 60)
    if success:
        print("✓ ALL TESTS PASSED - SKIPPED trades correctly excluded!")
        return 0
    else:
        print("✗ TESTS FAILED")
        return 1

if __name__ == '__main__':
    sys.exit(test_skipped_trades_excluded())
