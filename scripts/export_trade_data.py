"""
export_trade_data.py — Export closed trades ke CSV untuk RL training.

Usage:
    python scripts/export_trade_data.py
    python scripts/export_trade_data.py --pairs BTCUSDT,ETHUSDT
    python scripts/export_trade_data.py --mode testnet
    python scripts/export_trade_data.py --from 2026-01-01 --to 2026-04-01

Output: data/rl_training/trades_<timestamp>.csv
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.storage import PaperTrade, get_session
from src.utils.logger import logger, setup_logger


def export_trades(
    pairs: list = None,
    mode: str = None,
    from_date: str = None,
    to_date: str = None,
) -> str:
    """
    Export closed trades ke CSV.

    Args:
        pairs: Filter by pairs (None = semua)
        mode: Filter by execution_mode ('paper', 'testnet', atau 'mainnet')
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)

    Returns:
        Path ke CSV file yang dihasilkan
    """
    with get_session() as db:
        query = db.query(PaperTrade).filter(PaperTrade.status == 'CLOSED')

        if pairs:
            query = query.filter(PaperTrade.pair.in_(pairs))
        if mode:
            query = query.filter(PaperTrade.execution_mode == mode)
        if from_date:
            start = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            query = query.filter(PaperTrade.close_timestamp >= start)
        if to_date:
            end = datetime.strptime(to_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            query = query.filter(PaperTrade.close_timestamp <= end)

        trades = query.order_by(PaperTrade.close_timestamp.asc()).all()

    if not trades:
        logger.warning("Tidak ada closed trades yang cocok dengan filter.")
        return None

    # Convert ke list of dict
    rows = []
    for t in trades:
        rows.append({
            'trade_id': t.id,
            'pair': t.pair,
            'side': t.side,
            'entry_price': t.entry_price,
            'close_price': t.close_price if t.close_price else (
                t.sl_price if t.close_reason == 'SL' else t.tp_price
            ),
            'sl_price': t.sl_price,
            'tp_price': t.tp_price,
            'size': t.size,
            'leverage': t.leverage,
            'pnl': t.pnl,
            'close_reason': t.close_reason,
            'execution_mode': t.execution_mode or 'paper',
            'entry_timestamp': t.entry_timestamp.isoformat() if t.entry_timestamp else '',
            'close_timestamp': t.close_timestamp.isoformat() if t.close_timestamp else '',
        })

    df = pd.DataFrame(rows)

    # Output
    os.makedirs("data/rl_training", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"data/rl_training/trades_{timestamp}.csv"
    df.to_csv(filepath, index=False)

    # Summary
    wins = sum(1 for r in rows if (r['pnl'] or 0) > 0)
    total = len(rows)
    total_pnl = sum(r['pnl'] or 0 for r in rows)

    logger.info(f"Exported {total} trades to {filepath}")
    logger.info(f"Win rate: {wins/total*100:.1f}% | Total PnL: ${total_pnl:.2f}")

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Export trade data for RL training")
    parser.add_argument("--pairs", type=str, default=None, help="Comma-separated pairs (e.g., BTCUSDT,ETHUSDT). Default: dari pairs.json")
    parser.add_argument("--mode", type=str, default=None, choices=['paper', 'testnet', 'mainnet'], help="Filter by execution mode (must match DB values)")
    parser.add_argument("--from", dest='from_date', type=str, default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest='to_date', type=str, default=None, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    setup_logger()

    # Default ke pairs.json kalau --pairs tidak diisi
    if args.pairs:
        pairs = args.pairs.split(',')
    else:
        from src.config.pairs import load_pairs
        pairs = load_pairs()

    filepath = export_trades(
        pairs=pairs,
        mode=args.mode,
        from_date=args.from_date,
        to_date=args.to_date,
    )

    if filepath:
        print(f"\nCSV saved to: {filepath}")
        print("Next steps for RL training:")
        print("  1. Upload this CSV to Google Colab")
        print("  2. Upload src/rl/ directory to Colab")
        print("  3. Run DQNTrainer in Colab")
        print("  4. Download best_model.onnx")
        print("  5. Upload to VPS: data/rl_models/best_model.onnx")
    else:
        print("No trades exported.")


if __name__ == "__main__":
    main()
