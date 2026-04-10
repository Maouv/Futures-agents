"""
sltp_manager.py — Cek SL/TP untuk paper trades yang masih OPEN.
HANYA untuk paper mode. Di live mode, SL/TP sudah diserahkan ke Binance server.

Exit detection menggunakan candle HIGH/LOW (bukan close) untuk menghindari
look-ahead bias. Di Binance real, stop_market trigger berdasarkan high/low,
bukan close — jadi paper mode harus mensimulasikan hal yang sama.
"""
from datetime import datetime, timezone
from typing import Dict, List

from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.logger import logger


def check_paper_trades(current_prices: Dict[str, Dict]) -> List[Dict]:
    """
    Cek semua paper trade OPEN terhadap harga high/low/close 15m terbaru.

    Args:
        current_prices: Dictionary pair -> {high, low, close}
                        Contoh: {'BTCUSDT': {'high': 67800, 'low': 67200, 'close': 67500}}

    Returns:
        List of closed trades dengan reason 'TP' atau 'SL'.
        Contoh: [{'trade_id': 1, 'pair': 'BTCUSDT', 'side': 'LONG', 'pnl': 50.0, 'reason': 'TP'}]
    """
    # ── Live Mode Guard ────────────────────────────────────────────────────
    # Di live mode, SL/TP di-handle oleh Binance server-side + WebSocket.
    # SLTPManager hanya dipakai di paper mode.
    if settings.EXECUTION_MODE == "live":
        logger.debug("Live mode — SL/TP managed by Binance, skipping paper SLTP check")
        return []

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
            candle = current_prices.get(trade.pair)
            if candle is None:
                logger.error(
                    f"CRITICAL: Harga untuk {trade.pair} tidak ditemukan! "
                    f"Trade ID {trade.id} tidak dapat di-monitor. "
                    f"Pairs yang tersedia: {list(current_prices.keys())}"
                )
                continue

            high = candle['high']
            low = candle['low']

            hit_tp = False
            hit_sl = False

            # Cek SL/TP menggunakan high/low candle (bukan close)
            # Ini mensimulasikan cara Binance trigger stop_market:
            # - TP LONG ter-trigger saat harga NAIK menyentuh TP → cek HIGH
            # - SL LONG ter-trigger saat harga TURUN menyentuh SL → cek LOW
            # - SHORT: kebalikan
            if trade.side == 'LONG':
                hit_tp = high >= trade.tp_price
                hit_sl = low <= trade.sl_price
            else:  # SHORT
                hit_tp = low <= trade.tp_price
                hit_sl = high >= trade.sl_price

            if hit_tp or hit_sl:
                # Race condition guard: re-read dari DB sebelum modify
                # Mencegah double-close jika WS handler sudah menutup trade yang sama
                db.refresh(trade)
                if trade.status != 'OPEN':
                    logger.debug(f"Trade {trade.id} already closed by another thread. Skipping.")
                    continue
                close_reason = 'TP' if hit_tp else 'SL'
                close_price = trade.tp_price if hit_tp else trade.sl_price

                # Hitung PnL
                if trade.side == 'LONG':
                    pnl = (close_price - trade.entry_price) * trade.size
                else:  # SHORT
                    pnl = (trade.entry_price - close_price) * trade.size

                # Update trade
                trade.status = 'CLOSED'
                trade.close_price = close_price
                trade.pnl = pnl
                trade.close_reason = close_reason
                trade.close_timestamp = datetime.now(timezone.utc)

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
                    f"PAPER TRADE CLOSED | ID: {trade.id} | "
                    f"{trade.pair} {trade.side} | "
                    f"Reason: {close_reason} | PnL: ${pnl:.2f}"
                )

    return closed
