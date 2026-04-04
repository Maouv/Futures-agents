"""
sltp_manager.py — Cek SL/TP untuk paper trades yang masih OPEN.
HANYA untuk paper mode. Di live mode, SL/TP sudah diserahkan ke Binance server.
"""
from datetime import datetime
from typing import Dict, List

from src.data.storage import PaperTrade, get_session
from src.utils.logger import logger


def check_paper_trades(current_prices: Dict[str, float]) -> List[Dict]:
    """
    Cek semua paper trade OPEN terhadap harga close 15m terbaru.

    Args:
        current_prices: Dictionary pair -> harga terbaru
                        Contoh: {'BTCUSDT': 67500.0, 'ETHUSDT': 3500.0}

    Returns:
        List of closed trades dengan reason 'TP' atau 'SL'.
        Contoh: [{'trade_id': 1, 'pair': 'BTCUSDT', 'side': 'LONG', 'pnl': 50.0, 'reason': 'TP'}]
    """
    closed = []

    with get_session() as db:
        open_trades = db.query(PaperTrade).filter(
            PaperTrade.status == 'OPEN'
        ).all()

        if not open_trades:
            logger.debug("Tidak ada paper trade OPEN")
            return closed

        logger.info(f"Memeriksa {len(open_trades)} paper trade OPEN...")

        for trade in open_trades:
            price = current_prices.get(trade.pair)
            if price is None:
                logger.error(
                    f"CRITICAL: Harga untuk {trade.pair} tidak ditemukan! "
                    f"Trade ID {trade.id} tidak dapat di-monitor. "
                    f"Pairs yang tersedia: {list(current_prices.keys())}"
                )
                continue

            hit_tp = False
            hit_sl = False

            # Cek apakah SL atau TP tersentuh
            if trade.side == 'LONG':
                hit_tp = price >= trade.tp_price
                hit_sl = price <= trade.sl_price
            else:  # SHORT
                hit_tp = price <= trade.tp_price
                hit_sl = price >= trade.sl_price

            if hit_tp or hit_sl:
                close_reason = 'TP' if hit_tp else 'SL'
                close_price = trade.tp_price if hit_tp else trade.sl_price

                # Hitung PnL
                if trade.side == 'LONG':
                    pnl = (close_price - trade.entry_price) * trade.size
                else:  # SHORT
                    pnl = (trade.entry_price - close_price) * trade.size

                # Update trade
                trade.status = 'CLOSED'
                trade.pnl = pnl
                trade.close_reason = close_reason
                trade.close_timestamp = datetime.utcnow()

                closed.append({
                    'trade_id': trade.id,
                    'pair': trade.pair,
                    'side': trade.side,
                    'entry_price': trade.entry_price,
                    'close_price': close_price,
                    'pnl': pnl,
                    'reason': close_reason,
                })

                logger.info(
                    f"🔔 PAPER TRADE CLOSED | ID: {trade.id} | "
                    f"{trade.pair} {trade.side} | "
                    f"Reason: {close_reason} | PnL: ${pnl:.2f}"
                )

    return closed
