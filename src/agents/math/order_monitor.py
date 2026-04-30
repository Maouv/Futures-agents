# src/agents/math/order_monitor.py
"""
order_monitor.py — Monitor pending LIMIT orders hingga FILLED atau EXPIRED.

Dipanggil setiap cycle oleh main loop (live mode only).
Tanggung jawab:
  - Cek status order di Binance
  - Jika FILLED → pasang SL + TP via Algo API
  - Jika EXPIRED / timeout → cancel dan update DB
"""
import time
from datetime import UTC, datetime

import ccxt

from src.agents.math.base_agent import BaseAgent
from src.agents.math.execution_utils import ExecutionMixin
from src.agents.math.position_manager import calculate_liquidation_price
from src.config.config_loader import load_trading_config
from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.exchange import get_exchange, place_algo_order
from src.utils.mode import get_current_mode
from src.utils.trade_utils import calculate_pnl, close_trade

# ── SL Retry Constants (sama dengan execution_agent.py) ──────────────────────
SL_MAX_RETRIES = 3
SL_RETRY_BACKOFF_BASE = 2  # seconds, exponential


class OrderMonitor(ExecutionMixin, BaseAgent):
    """
    Monitor semua pending LIMIT orders.

    Setiap cycle, cek apakah limit order sudah FILLED, EXPIRED, atau masih waiting.
    Jika FILLED → pasang SL + TP di Binance, update DB ke OPEN.
    Jika EXPIRED → cancel order, update DB ke EXPIRED.

    Tidak bisa berdiri sendiri — biasanya dipanggil lewat ExecutionAgent
    sebagai delegate (untuk backward compatibility).
    """

    def __init__(self, notification_callback=None):
        """
        Args:
            notification_callback: Optional callable untuk kirim Telegram alert.
        """
        super().__init__()
        self._notification_callback = notification_callback

    def run(self, *args, **kwargs):
        """
        Implementasi abstract method dari BaseAgent.
        Untuk OrderMonitor, gunakan check_pending_orders() secara langsung.
        """
        return self.check_pending_orders()

    def check_pending_orders(self) -> list:
        """
        Cek semua PENDING_ENTRY trades — apakah sudah FILLED atau EXPIRED.
        Dipanggil setiap cycle oleh main loop.
        Hanya berjalan di live mode — paper mode tidak punya Binance orders.

        Returns:
            List of dict dengan info aksi yang diambil per trade.
        """
        results: list[dict] = []

        # Paper mode tidak punya pending Binance orders
        if settings.EXECUTION_MODE != "live":
            return results

        mode = get_current_mode()

        with get_session() as db:
            pending_trades = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.status == 'PENDING_ENTRY',
                    PaperTrade.execution_mode == mode,
                )
                .all()
            )

            for trade in pending_trades:
                # Extract ke dict SEBELUM session close untuk menghindari DetachedInstanceError
                trade_data = {
                    'id': trade.id,
                    'pair': trade.pair,
                    'side': trade.side,
                    'entry_price': trade.entry_price,
                    'sl_price': trade.sl_price,
                    'tp_price': trade.tp_price,
                    'size': trade.size,
                    'leverage': trade.leverage,
                    'exchange_order_id': trade.exchange_order_id,
                    'entry_timestamp': trade.entry_timestamp,
                }
                result = self._check_single_pending(trade_data)
                results.append(result)

        return results

    def _check_single_pending(self, trade: dict) -> dict:
        """
        Cek satu pending trade: sudah filled, expired, atau masih menunggu?
        Menerima dict (bukan PaperTrade) untuk menghindari DetachedInstanceError.
        """
        exchange = get_exchange()
        trade_id = trade['id']
        trade_pair = trade['pair']
        trade_exchange_order_id = trade['exchange_order_id']
        result = {"trade_id": trade_id, "pair": trade_pair, "action": "none"}

        try:
            # ── Cek Order Status di Binance ────────────────────────────────
            order = exchange.fetch_order(trade_exchange_order_id, trade_pair)
            order_status = order.get('status', 'unknown')

            if order_status in ('filled', 'closed'):
                result = self._handle_fill(trade, order, exchange)

            elif order_status == 'canceled' or order_status == 'expired':
                # Order di-cancel secara eksternal — update DB
                with get_session() as db:
                    db_trade = db.query(PaperTrade).get(trade_id)
                    if db_trade:
                        db_trade.status = 'EXPIRED'
                        db_trade.close_reason = 'EXPIRED'
                        db_trade.close_timestamp = datetime.now(UTC)

                self._log(f"Order {trade_exchange_order_id} canceled/expired externally")
                result["action"] = "expired"

            elif order_status == 'open':
                # Masih menunggu — cek kadaluarsa
                entry_ts = trade['entry_timestamp']
                # Handle naive datetime dari SQLite
                if entry_ts.tzinfo is None:
                    entry_ts = entry_ts.replace(tzinfo=UTC)
                hours_elapsed = (datetime.now(UTC) - entry_ts).total_seconds() / 3600
                candles_elapsed = hours_elapsed  # 1 candle H1 = 1 jam
                candles_remaining = settings.ORDER_EXPIRY_CANDLES - candles_elapsed

                if candles_elapsed >= settings.ORDER_EXPIRY_CANDLES:
                    # Kadaluarsa — cancel order di Binance
                    try:
                        exchange.cancel_order(trade_exchange_order_id, trade_pair)
                        self._log(
                            f"Limit order EXPIRED after {candles_elapsed:.1f} H1 candles | "
                            f"Trade {trade_id} | Order {trade_exchange_order_id}"
                        )
                    except ccxt.OrderNotFound:
                        self._log(f"Order {trade_exchange_order_id} already gone — treating as expired")
                    except Exception as e:
                        self._log_error(f"Failed to cancel expired order {trade_exchange_order_id}: {e}")

                    with get_session() as db:
                        db_trade = db.query(PaperTrade).get(trade_id)
                        if db_trade:
                            db_trade.status = 'EXPIRED'
                            db_trade.close_reason = 'EXPIRED'
                            db_trade.close_timestamp = datetime.now(UTC)

                    result["action"] = "expired"
                else:
                    self._log(
                        f"Pending order still waiting | Trade {trade_id} | "
                        f"{candles_remaining:.1f} H1 candles remaining"
                    )
                    result["action"] = "waiting"

            else:
                self._log_error(
                    f"Unknown order status '{order_status}' for trade {trade_id}"
                )

        except ccxt.OrderNotFound:
            self._log_error(f"Order {trade_exchange_order_id} not found on exchange")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'EXPIRED'
                    db_trade.close_reason = 'EXPIRED'
                    db_trade.close_timestamp = datetime.now(UTC)
            result["action"] = "expired"

        except Exception as e:
            self._log_error(f"Error checking pending order {trade_id}: {e}")
            result["action"] = "error"

        return result

    def _handle_fill(self, trade: dict, order: dict, exchange) -> dict:
        """
        Limit order sudah FILLED — pasang SL + TP di Binance.
        Ini momen paling kritis: kalau SL gagal setelah retry, emergency close posisi.
        Menerima dict (bukan PaperTrade) untuk menghindari DetachedInstanceError.
        """
        result = {"trade_id": trade['id'], "pair": trade['pair'], "action": "filled"}
        filled_price = float(order.get('average', order.get('price', trade['entry_price'])))
        filled_amount = float(order.get('filled', trade['size']))

        # Extract attributes dari dict
        trade_id = trade['id']
        trade_pair = trade['pair']
        trade_side = trade['side']
        trade_sl_price = trade['sl_price']
        trade_tp_price = trade['tp_price']

        close_side = 'sell' if trade_side == 'LONG' else 'buy'

        # ── Place SL (stop_market) via Algo API with retry ───────────────────
        # Sejak Des 2025, Binance migrasi conditional orders ke Algo Order API.
        # Endpoint: POST /fapi/v1/algoOrder (algoType=CONDITIONAL, type=STOP_MARKET)
        sl_order_id = None
        for attempt in range(1, SL_MAX_RETRIES + 1):
            try:
                sl_result = place_algo_order(
                    symbol=trade_pair,
                    side=close_side,
                    order_type='STOP_MARKET',
                    trigger_price=trade_sl_price,
                    quantity=filled_amount,
                    reduce_only=True,
                )
                sl_order_id = str(sl_result.get('algoId', ''))
                self._log(f"SL algo order placed | ID: {sl_order_id} | Trigger: {trade_sl_price:.2f}")
                break
            except Exception as e:
                self._log_error(
                    f"SL order attempt {attempt}/{SL_MAX_RETRIES} FAILED for trade {trade_id}: {e}"
                )
                if attempt < SL_MAX_RETRIES:
                    backoff = SL_RETRY_BACKOFF_BASE ** attempt
                    self._log(f"Retrying SL in {backoff}s...")
                    time.sleep(backoff)

        # ── SL gagal total → Emergency Market Close ────────────────────────
        if sl_order_id is None:
            self._log_error(
                f"CRITICAL: SL order FAILED after {SL_MAX_RETRIES} retries for trade {trade_id}! "
                f"Emergency closing position to prevent unprotected exposure."
            )
            emergency_close_price = None
            try:
                close_order = exchange.create_order(
                    symbol=trade_pair,
                    type='market',
                    side=close_side,
                    amount=exchange.amount_to_precision(trade_pair, filled_amount),
                    params={'reduceOnly': True}
                )
                emergency_close_price = float(close_order.get('average', close_order.get('price', filled_price)))
                self._log(f"Emergency close executed at {emergency_close_price:.2f}")
            except Exception as e2:
                self._log_error(f"EMERGENCY CLOSE ALSO FAILED: {e2}. Manual intervention required!")
                emergency_close_price = filled_price  # fallback

            # Hitung PnL dari emergency close
            emergency_pnl = calculate_pnl(trade_side, filled_price, emergency_close_price, filled_amount)

            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    close_trade(db_trade, 'EMERGENCY_CLOSE_SL_FAIL', emergency_close_price, emergency_pnl)
                    db_trade.entry_price = filled_price
                    db_trade.size = filled_amount
                    db_trade.exchange_order_id = str(order.get('id', trade.get('exchange_order_id')))

            self._log(
                f"TRADE EMERGENCY CLOSED | ID: {trade_id} | "
                f"{trade_pair} {trade_side} | "
                f"Entry: {filled_price:.2f} | Close: {emergency_close_price:.2f} | "
                f"PnL: ${emergency_pnl:.2f} | Reason: SL_FAIL"
            )
            result["action"] = "emergency_closed"
            return result

        # ── Place TP (take_profit_market) via Algo API with retry ───────────
        tp_order_id = None
        for attempt in range(1, SL_MAX_RETRIES + 1):
            try:
                tp_result = place_algo_order(
                    symbol=trade_pair,
                    side=close_side,
                    order_type='TAKE_PROFIT_MARKET',
                    trigger_price=trade_tp_price,
                    quantity=filled_amount,
                    reduce_only=True,
                )
                tp_order_id = str(tp_result.get('algoId', ''))
                self._log(f"TP algo order placed | ID: {tp_order_id} | Trigger: {trade_tp_price:.2f}")
                break
            except Exception as e:
                self._log_error(
                    f"TP order attempt {attempt}/{SL_MAX_RETRIES} FAILED for trade {trade_id}: {e}"
                )
                if attempt < SL_MAX_RETRIES:
                    backoff = SL_RETRY_BACKOFF_BASE ** attempt
                    self._log(f"Retrying TP in {backoff}s...")
                    time.sleep(backoff)

        if tp_order_id is None:
            self._send_alert(
                f"⚠️ TP GAGAL setelah {SL_MAX_RETRIES} retry | Trade {trade_id} | {trade_pair}\n"
                f"SL @ {trade_sl_price:.4f} masih aktif.\n"
                f"→ Manual TP perlu dipasang di Binance!"
            )

        # ── Update DB ──────────────────────────────────────────────────────
        liq_price = calculate_liquidation_price(filled_price, trade_side, trade.get('leverage', 10))
        taker_fee_rate = load_trading_config().get("taker_fee_rate", 0.0004)
        fee_open_fill = float(order.get('fee', {}).get('cost', 0) or 0) or (
            filled_amount * filled_price * taker_fee_rate
        )

        with get_session() as db:
            db_trade = db.query(PaperTrade).get(trade_id)
            if db_trade:
                db_trade.status = 'OPEN'
                db_trade.entry_price = filled_price
                db_trade.size = filled_amount
                db_trade.sl_order_id = sl_order_id
                db_trade.tp_order_id = tp_order_id
                db_trade.exchange_order_id = str(order.get('id', trade.get('exchange_order_id')))
                db_trade.liq_price = liq_price
                db_trade.actual_entry_price = filled_price
                db_trade.slippage_entry = filled_price - trade.get('entry_price', filled_price)
                db_trade.fee_open = fee_open_fill

        self._log(
            f"LIVE TRADE OPENED | ID: {trade_id} | "
            f"{trade_pair} {trade_side} | "
            f"Entry: {filled_price:.2f} | "
            f"SL: {trade_sl_price:.2f} | TP: {trade_tp_price:.2f} | "
            f"Liq: ${liq_price:.2f} | "
            f"SL_Order: {sl_order_id} | TP_Order: {tp_order_id}"
        )

        return result
