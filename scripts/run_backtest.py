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
from src.backtest.metrics import TradeResult, calculate_metrics


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
    parser.add_argument(
        '--use-confirmation',
        action='store_true',
        help='Enable 15m confirmation filter (requires 15m data)'
    )
    parser.add_argument(
        '--pairs',
        type=str,
        default='BTCUSDT',
        help='Trading pairs comma-separated (default: BTCUSDT). Example: BTCUSDT,ETHUSDT,SOLUSDT'
    )
    args = parser.parse_args()

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(',')]

    # Validate month requires year
    if args.month is not None and args.year is None:
        logger.error("--month requires --year to be specified")
        sys.exit(1)

    project_root = Path(__file__).parent.parent

    # Collect all trades from all pairs
    all_trades: list[TradeResult] = []

    # Run backtest for each pair sequentially
    for pair in pairs:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing pair: {pair}")
        logger.info(f"{'='*60}")

        # Paths to data for this pair
        h4_csv = project_root / 'data' / 'historical' / f'{pair}-4h-full.csv'
        h1_csv = project_root / 'data' / 'historical' / f'{pair}-1h-full.csv'
        m15_csv = project_root / 'data' / 'historical' / f'{pair}-15m-full.csv'

        # Check files exist
        if not h4_csv.exists():
            logger.error(f"H4 data not found: {h4_csv}")
            logger.error(f"Skipping pair: {pair}")
            continue

        if not h1_csv.exists():
            logger.error(f"H1 data not found: {h1_csv}")
            logger.error(f"Skipping pair: {pair}")
            continue

        # Check 15m data if confirmation enabled
        if args.use_confirmation:
            if not m15_csv.exists():
                logger.error(f"15m data not found: {m15_csv}")
                logger.error(f"Skipping pair: {pair}")
                continue

        # Initialize engine for this pair
        engine = BacktestEngine(
            h4_csv_path=str(h4_csv),
            h1_csv_path=str(h1_csv),
            m15_csv_path=str(m15_csv) if args.use_confirmation else None,
            initial_balance=args.initial_balance,
            risk_per_trade=args.risk_per_trade,
            fee_rate=args.fee_rate,
            slippage=args.slippage,
            tp_percent=args.tp_percent,
            sl_percent=args.sl_percent,
            use_confirmation=args.use_confirmation,
        )

        # Run backtest for this pair
        if args.month:
            logger.info(f"Running backtest for {pair} - {args.year}-{args.month:02d}")
        elif args.year:
            logger.info(f"Running backtest for {pair} - year: {args.year}")
        else:
            logger.info(f"Running backtest for {pair} - all years")

        metrics = engine.run(year=args.year, month=args.month)

        # Print results for this pair
        print(f"\n{'='*60}")
        print(f"BACKTEST RESULTS - {pair}")
        print(f"{'='*60}")
        print(f"Total Trades:      {metrics.total_trades}")
        print(f"Win Rate:          {metrics.win_rate:.2f}%")
        print(f"Total PnL:         {metrics.total_pnl:.2f} USDT")
        print(f"Profit Factor:     {metrics.profit_factor:.2f}")
        print(f"Max Drawdown:      {metrics.max_drawdown:.2f}%")
        print(f"{'='*60}")

        # Collect trades from this pair
        all_trades.extend(engine.trades)

    # After all pairs processed, calculate combined metrics
    if all_trades:
        # Sort all trades by entry time
        all_trades.sort(key=lambda t: t.entry_time)

        # Calculate combined metrics
        combined_metrics = calculate_metrics(all_trades, initial_balance=args.initial_balance)

        # Print combined results
        print(f"\n{'='*60}")
        print("COMBINED PORTFOLIO RESULTS")
        print(f"{'='*60}")
        print(f"Total Pairs:       {len(pairs)}")
        print(f"Total Trades:      {combined_metrics.total_trades}")
        print(f"Winning Trades:    {combined_metrics.winning_trades}")
        print(f"Losing Trades:     {combined_metrics.losing_trades}")
        print(f"Win Rate:          {combined_metrics.win_rate:.2f}%")
        print(f"Total PnL:         {combined_metrics.total_pnl:.2f} USDT")
        print(f"Gross Profit:      {combined_metrics.gross_profit:.2f} USDT")
        print(f"Gross Loss:        {combined_metrics.gross_loss:.2f} USDT")
        print(f"Profit Factor:     {combined_metrics.profit_factor:.2f}")
        print(f"Max Drawdown:      {combined_metrics.max_drawdown:.2f}%")
        print(f"Average Win:       {combined_metrics.avg_win:.2f} USDT")
        print(f"Average Loss:      {combined_metrics.avg_loss:.2f} USDT")
        print(f"Largest Win:       {combined_metrics.largest_win:.2f} USDT")
        print(f"Largest Loss:      {combined_metrics.largest_loss:.2f} USDT")
        print(f"{'='*60}")

        # Print trade distribution
        print("\nTRADE DISTRIBUTION")
        print(f"{'='*60}")
        tp_trades = sum(1 for t in all_trades if t.exit_reason == 'TP')
        sl_trades = sum(1 for t in all_trades if t.exit_reason == 'SL')
        timeout_trades = sum(1 for t in all_trades if t.exit_reason == 'TIMEOUT')

        print(f"TP Exits:          {tp_trades} ({tp_trades/combined_metrics.total_trades*100:.1f}%)")
        print(f"SL Exits:          {sl_trades} ({sl_trades/combined_metrics.total_trades*100:.1f}%)")
        print(f"Timeout Exits:     {timeout_trades} ({timeout_trades/combined_metrics.total_trades*100:.1f}%)")
        print(f"{'='*60}")

    logger.info("\nBacktest completed successfully for all pairs")


if __name__ == '__main__':
    main()
