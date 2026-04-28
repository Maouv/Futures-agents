"""
position_manager.py — Trailing stop + liquidation price management.
HANYA untuk live/testnet mode. Paper mode SL/TP di-handle oleh sltp_manager.

Trailing stop: step-based SL adjustment saat unrealized profit mencapai threshold.
Liquidation price: estimasi harga likuidasi (simplified formula).
"""

from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.exchange import cancel_algo_order, place_algo_order
from src.utils.logger import logger
from src.utils.trade_utils import calculate_pnl, close_trade


def calculate_liquidation_price(entry_price: float, side: str, leverage: int) -> float:
    """
    Estimasi harga likuidasi (isolated margin, simplified).

    LONG:  liq_price = entry * (1 - 1/leverage)
    SHORT: liq_price = entry * (1 + 1/leverage)

    Simplified — tidak memperhitungkan Binance tier-based maintenance margin.
    Untuk awareness di Telegram, estimasi ini cukup. Bisa di-refine nanti
    dengan /fapi/v1/leverageBracket API.
    """
    if leverage <= 0:
        raise ValueError(f"Invalid leverage: {leverage}")

    if side == "LONG":
        return entry_price * (1 - 1 / leverage)
    elif side == "SHORT":
        return entry_price * (1 + 1 / leverage)
    else:
        raise ValueError(f"Invalid side: {side}")


def check_trailing_stop(current_prices: dict[str, dict]) -> list[dict]:
    """
    Cek semua OPEN live trades, apply trailing stop steps jika profit threshold tercapai.

    Args:
        current_prices: Dictionary pair -> {high, low, close}
                        Contoh: {'BTCUSDT': {'high': 67800, 'low': 67200, 'close': 67500}}

    Returns:
        List of updated trades: [{trade_id, pair, side, old_sl, new_sl, step_index}]
    """
    # ── Guards ─────────────────────────────────────────────────────────────
    if not settings.TRAILING_STOP_ENABLED:
        return []

    if settings.EXECUTION_MODE == "paper":
        return []

    steps = settings.TRAILING_STOP_STEPS
    if not steps:
        return []

    # Validate step schema — skip malformed entries instead of crashing
    _required_keys = {'profit_pct', 'new_sl_pct'}
    valid_steps = []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            logger.warning(f"Trailing stop: step[{idx}] is not a dict, skipping — {step!r}")
            continue
        missing = _required_keys - step.keys()
        if missing:
            logger.warning(f"Trailing stop: step[{idx}] missing keys {missing}, skipping — {step!r}")
            continue
        valid_steps.append((idx, step))

    if not valid_steps:
        logger.warning("Trailing stop: no valid steps after validation, aborting check")
        return []

    updated = []

    with get_session() as db:
        open_trades = db.query(PaperTrade).filter(
            PaperTrade.status == 'OPEN',
            PaperTrade.execution_mode.in_(['mainnet', 'testnet']),
        ).all()

        if not open_trades:
            return []

        logger.info(f"Trailing stop: checking {len(open_trades)} live trades...")

        for trade in open_trades:
            # Skip jika tidak ada SL order (SL belum di-place)
            if not trade.sl_order_id:
                logger.debug(f"Trade {trade.id}: no sl_order_id, skipping trailing")
                continue

            candle = current_prices.get(trade.pair)
            if candle is None:
                logger.warning(f"Trailing stop: no price for {trade.pair}, skipping trade {trade.id}")
                continue

            current_price = candle['close']

            # Hitung unrealized profit %
            if trade.side == 'LONG':
                profit_pct = (current_price - trade.entry_price) / trade.entry_price * 100
            else:  # SHORT
                profit_pct = (trade.entry_price - current_price) / trade.entry_price * 100

            # Cari step tertinggi yang tercapai DAN step_index > trade.trailing_step
            matched_step = None
            matched_index = None
            for i, step in valid_steps:
                if i <= trade.trailing_step:
                    continue  # Sudah di-apply sebelumnya
                if profit_pct >= step['profit_pct']:
                    matched_step = step
                    matched_index = i

            if matched_step is None:
                continue  # Tidak ada step baru yang tercapai

            # Hitung new SL
            new_sl_pct = matched_step['new_sl_pct']
            if trade.side == 'LONG':
                new_sl = trade.entry_price * (1 + new_sl_pct / 100)
            else:  # SHORT
                new_sl = trade.entry_price * (1 - new_sl_pct / 100)

            # Validate: new SL harus lebih baik dari current SL
            if trade.side == 'LONG' and new_sl <= trade.sl_price:
                logger.debug(f"Trade {trade.id}: new SL {new_sl:.2f} not better than current {trade.sl_price:.2f}")
                continue
            if trade.side == 'SHORT' and new_sl >= trade.sl_price:
                logger.debug(f"Trade {trade.id}: new SL {new_sl:.2f} not better than current {trade.sl_price:.2f}")
                continue

            # ── Execute trailing: cancel old SL, place new SL ──────────────
            old_sl = trade.sl_price
            close_side = 'sell' if trade.side == 'LONG' else 'buy'
            old_sl_order_id = trade.sl_order_id

            logger.info(
                f"Trailing stop: Trade {trade.id} {trade.pair} {trade.side} | "
                f"Profit: {profit_pct:.2f}% → Step {matched_index} | "
                f"SL: {old_sl:.2f} → {new_sl:.2f}"
            )

            # Cancel old SL
            try:
                cancel_algo_order(old_sl_order_id, trade.pair)
                logger.info(f"Old SL algo cancelled | ID: {old_sl_order_id}")
            except Exception as e:
                logger.error(f"Failed to cancel old SL {old_sl_order_id}: {e}. Keeping current SL.")
                continue

            # Place new SL
            new_sl_order_id = None
            try:
                sl_result = place_algo_order(
                    symbol=trade.pair,
                    side=close_side,
                    order_type='STOP_MARKET',
                    trigger_price=new_sl,
                    quantity=trade.size,
                    reduce_only=True,
                )
                new_sl_order_id = str(sl_result.get('algoId', ''))
                logger.info(f"New SL algo placed | ID: {new_sl_order_id} | Trigger: {new_sl:.2f}")
            except Exception as e:
                # CRITICAL: posisi tanpa SL — emergency market close
                logger.error(
                    f"CRITICAL: New SL FAILED after cancel for trade {trade.id}! "
                    f"Emergency closing position. Error: {e}"
                )
                _emergency_close(trade, db)
                updated.append({
                    'trade_id': trade.id,
                    'pair': trade.pair,
                    'side': trade.side,
                    'old_sl': old_sl,
                    'new_sl': None,
                    'step_index': matched_index,
                    'emergency': True,
                })
                continue

            # Update DB
            db.refresh(trade)
            if trade.status != 'OPEN':
                logger.debug(f"Trade {trade.id} closed during trailing stop execution. Skipping DB update.")
                continue

            trade.sl_price = new_sl
            trade.sl_order_id = new_sl_order_id
            trade.trailing_step = matched_index

            updated.append({
                'trade_id': trade.id,
                'pair': trade.pair,
                'side': trade.side,
                'old_sl': old_sl,
                'new_sl': new_sl,
                'step_index': matched_index,
                'emergency': False,
            })

            logger.info(
                f"TRAILING SL UPDATED | Trade {trade.id} | "
                f"{trade.pair} {trade.side} | "
                f"SL: ${old_sl:.2f} → ${new_sl:.2f} | Step: {matched_index}"
            )

    return updated


def _emergency_close(trade: PaperTrade, db) -> None:
    """
    Emergency market close untuk posisi tanpa SL.
    Dipanggil ketika cancel_algo_order berhasil tapi place_algo_order gagal.
    """
    from src.utils.exchange import get_exchange

    try:
        exchange = get_exchange()
        close_side = 'sell' if trade.side == 'LONG' else 'buy'
        close_order = exchange.create_order(
            symbol=trade.pair,
            type='market',
            side=close_side,
            amount=exchange.amount_to_precision(trade.pair, trade.size),
            params={'reduceOnly': True}
        )
        close_price = float(close_order.get('average', close_order.get('price', trade.entry_price)))

        pnl = calculate_pnl(trade.side, trade.entry_price, close_price, trade.size)

        close_trade(trade, 'EMERGENCY_CLOSE_SL_FAIL', close_price, pnl)

        logger.info(
            f"EMERGENCY CLOSE (trailing) | Trade {trade.id} | "
            f"{trade.pair} {trade.side} | PnL: ${pnl:.2f}"
        )
    except Exception as e:
        logger.error(f"EMERGENCY CLOSE ALSO FAILED for trade {trade.id}: {e}. Manual intervention required!")
