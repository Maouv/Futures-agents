"""
sltp_manager.py — Cek SL/TP untuk paper trades yang masih OPEN.
HANYA untuk paper mode. Di live mode, SL/TP sudah diserahkan ke Binance server.

Exit detection menggunakan candle HIGH/LOW (bukan close) untuk menghindari
look-ahead bias. Di Binance real, stop_market trigger berdasarkan high/low,
bukan close — jadi paper mode harus mensimulasikan hal yang sama.
"""
from datetime import UTC, datetime

from src.config.config_loader import load_trading_config
from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.logger import logger
from src.utils.trade_utils import calculate_pnl, close_trade


def check_paper_trades(current_prices: dict[str, dict]) -> list[dict]:
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

    closed: list[dict] = []

    with get_session() as db:
        open_trades = db.query(PaperTrade).filter(
            PaperTrade.status == 'OPEN',
            PaperTrade.execution_mode == 'paper',
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
                # Conservative: jika candle menembus SL DAN TP, SL prioritas
                # (sama dengan backtest engine dan Binance real behavior)
                close_reason = 'SL' if hit_sl else 'TP'
                close_price = trade.sl_price if hit_sl else trade.tp_price

                # Hitung PnL
                pnl = calculate_pnl(trade.side, trade.entry_price, close_price, trade.size)

                # Fee tracking (paper mode: estimated)
                taker_fee_rate = load_trading_config().get("taker_fee_rate", 0.0004)
                fee_close = trade.size * close_price * taker_fee_rate
                fee_open_val = trade.fee_open or 0
                net_pnl_val = pnl - fee_open_val - fee_close

                # Update trade
                close_trade(trade, close_reason, close_price, pnl)
                trade.actual_close_price = close_price  # paper = planned, no slippage
                trade.slippage_close = 0.0
                trade.fee_close = fee_close
                trade.net_pnl = net_pnl_val

                closed.append({
                    'trade_id': trade.id,
                    'pair': trade.pair,
                    'side': trade.side,
                    'entry_price': trade.entry_price,
                    'close_price': close_price,
                    'pnl': pnl,
                    'net_pnl': net_pnl_val,
                    'fee_open': fee_open_val,
                    'fee_close': fee_close,
                    'reason': close_reason,
                })

                logger.info(
                    f"PAPER TRADE CLOSED | ID: {trade.id} | "
                    f"{trade.pair} {trade.side} | "
                    f"Reason: {close_reason} | PnL: ${pnl:.2f}"
                )

    return closed


def check_paper_pending(current_prices: dict[str, dict]) -> list[dict]:
    """
    Cek PENDING_ENTRY paper trades — apakah sudah 'filled' atau expired.
    Paper mode simulation untuk limit order fills (State 1/2).

    Fill condition (menggunakan candle low/high):
    - LONG: low <= entry_price (harga turun menyentuh limit)
    - SHORT: high >= entry_price (harga naik menyentuh limit)

    Expired: jika ORDER_EXPIRY_CANDLES H1 candles tercapai sebelum fill.

    Args:
        current_prices: Dictionary pair -> {high, low, close}

    Returns:
        List of dicts with fill/expired info per trade.
    """
    if settings.EXECUTION_MODE == "live":
        return []

    results: list[dict] = []

    with get_session() as db:
        pending_trades = db.query(PaperTrade).filter(
            PaperTrade.status == 'PENDING_ENTRY',
            PaperTrade.execution_mode == 'paper',
        ).all()

        if not pending_trades:
            return results

        logger.info(f"Memeriksa {len(pending_trades)} paper PENDING_ENTRY trade...")

        for trade in pending_trades:
            candle = current_prices.get(trade.pair)
            if candle is None:
                logger.warning(
                    f"Harga untuk {trade.pair} tidak ditemukan, "
                    f"skip pending check untuk trade {trade.id}"
                )
                continue

            low = candle['low']
            high = candle['high']

            # ── Check Fill ────────────────────────────────────────────────
            filled = False
            if trade.side == 'LONG' and low <= trade.entry_price:
                filled = True
            elif trade.side == 'SHORT' and high >= trade.entry_price:
                filled = True

            if filled:
                db.refresh(trade)
                if trade.status != 'PENDING_ENTRY':
                    logger.debug(f"Trade {trade.id} already handled. Skipping.")
                    continue

                trade.status = 'OPEN'
                results.append({
                    'trade_id': trade.id,
                    'pair': trade.pair,
                    'side': trade.side,
                    'action': 'filled',
                    'entry_price': trade.entry_price,
                })
                logger.info(
                    f"PAPER PENDING FILLED | ID: {trade.id} | "
                    f"{trade.pair} {trade.side} @ {trade.entry_price:.2f}"
                )
                continue

            # ── Check Expiry ──────────────────────────────────────────────
            if trade.entry_timestamp:
                entry_ts = trade.entry_timestamp
                if entry_ts.tzinfo is None:
                    entry_ts = entry_ts.replace(tzinfo=UTC)
                hours_elapsed = (datetime.now(UTC) - entry_ts).total_seconds() / 3600
                candles_elapsed = hours_elapsed  # 1 candle H1 = 1 jam

                if candles_elapsed >= settings.ORDER_EXPIRY_CANDLES:
                    db.refresh(trade)
                    if trade.status != 'PENDING_ENTRY':
                        continue

                    trade.status = 'EXPIRED'
                    trade.close_reason = 'EXPIRED'
                    trade.close_timestamp = datetime.now(UTC)
                    results.append({
                        'trade_id': trade.id,
                        'pair': trade.pair,
                        'side': trade.side,
                        'action': 'expired',
                    })
                    logger.info(
                        f"PAPER PENDING EXPIRED | ID: {trade.id} | "
                        f"{trade.pair} {trade.side} | Elapsed: {candles_elapsed:.1f} H1 candles"
                    )

    return results
