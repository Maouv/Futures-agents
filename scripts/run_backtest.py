#!/usr/bin/env python3
"""
run_backtest.py — CLI script untuk menjalankan backtest.

Usage:
    python3 scripts/run_backtest.py --timeframe 1h --year 2024
"""
import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.backtest.engine import BacktestEngine


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Run SMC strategy backtest')
    parser.add_argument(
        '--timeframe',
        type=str,
        default='1h',
        choices=['1h'],
        help='Primary timeframe (currently only 1h supported)'
    )
    parser.add_argument(
        '--year',
        type=int,
        default=None,
        help='Filter by year (e.g., 2024)'
    )
    parser.add_argument(
        '--month',
        type=int,
        default=None,
        help='Filter by month (1-12). If specified, --year is required.'
    )
    parser.add_argument(
        '--initial-balance',
        type=float,
        default=10000.0,
        help='Initial balance in USDT (default: 10000)'
    )
    parser.add_argument(
        '--risk-per-trade',
        type=float,
        default=0.01,
        help='Risk per trade as decimal (default: 0.01 = 1%%)'
    )
    parser.add_argument(
        '--fee-rate',
        type=float,
        default=0.0005,
        help='Trading fee per side (default: 0.0005 = 0.05%%)'
    )
    parser.add_argument(
        '--slippage',
        type=float,
        default=0.001,
        help='Slippage percentage (default: 0.001 = 0.1%%)'
    )
    parser.add_argument(
        '--tp-percent',
        type=float,
        default=0.02,
        help='Take profit percentage (default: 0.02 = 2%%)'
    )
    parser.add_argument(
        '--sl-percent',
        type=float,
        default=0.01,
        help='Stop loss percentage (default: 0.01 = 1%%)'
    )

    args = parser.parse_args()

    # Paths to data
    project_root = Path(__file__).parent.parent
    h4_csv = project_root / 'data' / 'historical' / 'BTCUSDT-4h-full.csv'
    h1_csv = project_root / 'data' / 'historical' / 'BTCUSDT-1h-full.csv'

    # Check files exist
    if not h4_csv.exists():
        logger.error(f"H4 data not found: {h4_csv}")
        sys.exit(1)

    if not h1_csv.exists():
        logger.error(f"H1 data not found: {h1_csv}")
        sys.exit(1)

    # Initialize engine
    engine = BacktestEngine(
        h4_csv_path=str(h4_csv),
        h1_csv_path=str(h1_csv),
        m15_csv_path=None,  # No 15m data available
        initial_balance=args.initial_balance,
        risk_per_trade=args.risk_per_trade,
        fee_rate=args.fee_rate,
        slippage=args.slippage,
        tp_percent=args.tp_percent,
        sl_percent=args.sl_percent
    )

    # Validate month requires year
    if args.month is not None and args.year is None:
        logger.error("--month requires --year to be specified")
        sys.exit(1)

    # Run backtest
    if args.month:
        logger.info(f"Running backtest for {args.year}-{args.month:02d}")
    elif args.year:
        logger.info(f"Running backtest for year: {args.year}")
    else:
        logger.info("Running backtest for all years")

    metrics = engine.run(year=args.year, month=args.month)

    # Print detailed results
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Total Trades:      {metrics.total_trades}")
    print(f"Winning Trades:    {metrics.winning_trades}")
    print(f"Losing Trades:     {metrics.losing_trades}")
    print(f"Win Rate:          {metrics.win_rate:.2f}%")
    print(f"Total PnL:         {metrics.total_pnl:.2f} USDT")
    print(f"Gross Profit:      {metrics.gross_profit:.2f} USDT")
    print(f"Gross Loss:        {metrics.gross_loss:.2f} USDT")
    print(f"Profit Factor:     {metrics.profit_factor:.2f}")
    print(f"Max Drawdown:      {metrics.max_drawdown:.2f}%")
    print(f"Average Win:       {metrics.avg_win:.2f} USDT")
    print(f"Average Loss:      {metrics.avg_loss:.2f} USDT")
    print(f"Largest Win:       {metrics.largest_win:.2f} USDT")
    print(f"Largest Loss:      {metrics.largest_loss:.2f} USDT")
    print("=" * 60)

    # Print trade distribution
    if metrics.total_trades > 0:
        print("\nTRADE DISTRIBUTION")
        print("=" * 60)

        # Count exits by type
        tp_trades = sum(1 for t in engine.trades if t.exit_reason == 'TP')
        sl_trades = sum(1 for t in engine.trades if t.exit_reason == 'SL')
        timeout_trades = sum(1 for t in engine.trades if t.exit_reason == 'TIMEOUT')

        print(f"TP Exits:          {tp_trades} ({tp_trades/metrics.total_trades*100:.1f}%)")
        print(f"SL Exits:          {sl_trades} ({sl_trades/metrics.total_trades*100:.1f}%)")
        print(f"Timeout Exits:     {timeout_trades} ({timeout_trades/metrics.total_trades*100:.1f}%)")
        print("=" * 60)

    logger.info("Backtest completed successfully")


if __name__ == '__main__':
    main()
