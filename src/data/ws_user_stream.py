"""
ws_user_stream.py — User Data WebSocket untuk Binance Futures.

Mendengarkan event ORDER_TRADE_UPDATE dari Binance untuk:
- Deteksi ketika SL/TP order ter-FILL
- Update PaperTrade di DB (status=CLOSED, pnl, close_price)
- Cancel counter-order (SL hit → cancel TP, dan sebaliknya)
- Send Telegram notification

Berjalan di background thread (daemon), tidak memblokir loop utama.

Features:
- Listen key acquisition + keepalive setiap 30 menit
- Auto-reconnect dengan exponential backoff (5s → 10s → 30s → 60s)
- Thread-safe DB access via get_session()
- Health check: jika tidak ada message selama 5 menit, force reconnect
"""
import asyncio
import json
import threading
import time
from typing import Optional, Callable

import websockets

from src.data.storage import PaperTrade, get_session
from src.utils.exchange import get_exchange, get_ws_base_url, reset_exchange
from src.utils.logger import logger
from src.utils.trade_utils import calculate_pnl, close_trade


# ── Constants ──────────────────────────────────────────────────────────────
KEEPALIVE_INTERVAL_SEC = 30 * 60   # 30 menit (Binance listen key expires 60 menit)
HEALTH_CHECK_INTERVAL_SEC = 5 * 60  # 5 menit — force reconnect jika tidak ada message
RECONNECT_DELAYS = [5, 10, 30, 60]  # Exponential backoff dalam detik, cap di 60


class UserDataStream:
    """
    User Data Stream manager untuk Binance Futures.

    Usage:
        stream = UserDataStream()
        stream.start()   # Mulai background thread
        stream.stop()    # Stop gracefully
    """

    def __init__(self, notification_callback: Optional[Callable] = None):
        """
        Args:
            notification_callback: Optional callable untuk Telegram notification.
                                   Dipanggil dengan dict: {'event': str, 'trade_id': int, ...}
        """
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._notification_callback = notification_callback
        self._last_message_time = 0.0

    def start(self) -> None:
        """Start User Data Stream di background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("User Data Stream already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="UserDataStream",
            daemon=True,
        )
        self._thread.start()
        logger.info("User Data Stream thread started")

    def stop(self) -> None:
        """Stop User Data Stream gracefully."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("User Data Stream stopped")

    def _run_loop(self) -> None:
        """Main loop yang berjalan di background thread."""
        reconnect_attempt = 0

        while self._running:
            try:
                asyncio.run(self._listen())
                reconnect_attempt = 0  # Reset jika berhasil connect
            except Exception as e:
                if not self._running:
                    break
                logger.error(f"User Data Stream error: {e}")

            if self._running:
                delay = RECONNECT_DELAYS[min(reconnect_attempt, len(RECONNECT_DELAYS) - 1)]
                logger.info(f"Reconnecting in {delay}s (attempt {reconnect_attempt + 1})")
                time.sleep(delay)
                reconnect_attempt += 1

    async def _listen(self) -> None:
        """
        Connect ke User Data Stream, listen for ORDER_TRADE_UPDATE,
        dan handle keepalive.
        """
        exchange = get_exchange()
        ws_base_url = get_ws_base_url()

        # ── Acquire Listen Key ────────────────────────────────────────────
        try:
            response = exchange.fapiPrivatePostListenKey()
            listen_key = response.get('listenKey', '')
            if not listen_key:
                raise ValueError(f"Empty listen key from response: {response}")
        except Exception as e:
            logger.error(f"Failed to acquire listen key: {e}")
            reset_exchange()
            raise

        ws_url = f"{ws_base_url}/{listen_key}"
        logger.info(f"User Data Stream connected to {ws_base_url}")

        # ── WebSocket Loop ─────────────────────────────────────────────────
        self._last_message_time = time.monotonic()

        async with websockets.connect(ws_url) as ws:
            # Start keepalive task
            keepalive_task = asyncio.create_task(
                self._keepalive(exchange, listen_key)
            )
            # Start health check task
            health_task = asyncio.create_task(
                self._health_check(ws)
            )

            try:
                async for raw_message in ws:
                    if not self._running:
                        break

                    self._last_message_time = time.monotonic()

                    try:
                        data = json.loads(raw_message)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from WS: {raw_message[:200]}")
                        continue

                    event = data.get('e', '')

                    if event == 'ORDER_TRADE_UPDATE':
                        await self._handle_order_update(data.get('o', {}))
                    elif event == 'listenKeyExpired':
                        logger.warning("Listen key expired — will reconnect")
                        break
                    # Ignore other events (ACCOUNT_UPDATE, etc.)

            finally:
                keepalive_task.cancel()
                health_task.cancel()

    async def _keepalive(self, exchange, listen_key: str) -> None:
        """Kirim keepalive PUT setiap 30 menit untuk mencegah listen key expired."""
        while self._running:
            await asyncio.sleep(KEEPALIVE_INTERVAL_SEC)
            if not self._running:
                break
            try:
                exchange.fapiPrivatePutListenKey(params={'listenKey': listen_key})
                logger.debug("Listen key keepalive sent")
            except Exception as e:
                logger.error(f"Listen key keepalive failed: {e}")

    async def _health_check(self, ws) -> None:
        """Jika tidak ada message selama 5 menit, force reconnect."""
        while self._running:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL_SEC)
            if not self._running:
                break
            elapsed = time.monotonic() - self._last_message_time
            if elapsed > HEALTH_CHECK_INTERVAL_SEC:
                logger.warning(
                    f"No WS message for {elapsed:.0f}s — forcing reconnect"
                )
                await ws.close()
                return

    async def _handle_order_update(self, order_data: dict) -> None:
        """
        Parse ORDER_TRADE_UPDATE dan update DB jika SL/TP ter-FILL.

        Binance ORDER_TRADE_UPDATE fields:
        - 's': symbol (e.g., 'BTCUSDT')
        - 'c': client order id
        - 'i': order id
        - 'o': order type (LIMIT, STOP_MARKET, TAKE_PROFIT_MARKET, etc.)
        - 'X': order status (NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED)
        - 'ap': average price
        - 'z': cumulative filled amount
        - 'S': side (BUY, SELL)
        """
        symbol = order_data.get('s', '')
        order_id = str(order_data.get('i', ''))
        order_type = order_data.get('o', '')
        order_status = order_data.get('X', '')
        avg_price = float(order_data.get('ap', 0))
        side = order_data.get('S', '')

        logger.debug(
            f"ORDER_TRADE_UPDATE | {symbol} | Type: {order_type} | "
            f"Status: {order_status} | ID: {order_id} | Price: {avg_price}"
        )

        # Hanya proses FILLED orders
        if order_status != 'FILLED':
            return

        # ── Cari trade di DB berdasarkan order ID ──────────────────────────
        # NOTE: SL/TP orders are placed via Algo API (place_algo_order), which
        # returns an 'algoId'. When the algo order triggers, Binance creates a
        # new order with a different orderId. The ORDER_TRADE_UPDATE event
        # contains this new orderId, NOT the algoId. So matching by
        # sl_order_id/tp_order_id (which store algoId) will fail for algo orders.
        # Fallback: match by symbol + order type for SL/TP fills.
        with get_session() as db:
            # Cek apakah ini SL, TP, atau entry order
            trade = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.status == 'OPEN',
                    (PaperTrade.sl_order_id == order_id) |
                    (PaperTrade.tp_order_id == order_id) |
                    (PaperTrade.exchange_order_id == order_id)
                )
                .first()
            )

            if trade is None and order_type in ('STOP_MARKET', 'STOP', 'TAKE_PROFIT_MARKET', 'TAKE_PROFIT'):
                # Algo order triggered — match by symbol + side inference
                # SL/TP are reduce_only: LONG trade has SELL SL/TP, SHORT trade has BUY SL/TP
                expected_trade_side = 'SHORT' if side == 'BUY' else 'LONG'
                trade = (
                    db.query(PaperTrade)
                    .filter(
                        PaperTrade.status == 'OPEN',
                        PaperTrade.pair == symbol,
                        PaperTrade.side == expected_trade_side,
                    )
                    .first()
                )
                if trade:
                    logger.info(
                        f"Matched algo order by symbol+side | Order {order_id} -> Trade {trade.id} ({symbol})"
                    )

            if trade is None:
                logger.debug(f"No matching OPEN trade for order {order_id}")
                return

            # ── Determine close reason ─────────────────────────────────────
            if order_type in ('STOP_MARKET', 'STOP'):
                close_reason = 'SL'
                counter_order_id = trade.tp_order_id
            elif order_type in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT'):
                close_reason = 'TP'
                counter_order_id = trade.sl_order_id
            else:
                # Entry order fill — place SL/TP langsung tanpa tunggu 15 menit
                trade_id_copy = trade.id
                pair_copy = trade.pair
                logger.info(
                    f"Entry order fill detected via WS for trade {trade_id_copy} ({pair_copy}) "
                    f"— triggering immediate SL/TP placement"
                )
                threading.Thread(
                    target=self._handle_entry_fill_async,
                    args=(trade_id_copy, pair_copy),
                    daemon=True,
                ).start()
                return

            # ── Race condition guard ───────────────────────────────────────────
            # Re-read dari DB sebelum modify — mencegah double-close jika
            # SLTPManager (paper mode) sudah menutup trade yang sama
            db.refresh(trade)
            if trade.status != 'OPEN':
                logger.debug(f"Trade {trade.id} already closed. Skipping WS update.")
                return

            # ── Calculate PnL ──────────────────────────────────────────────
            close_price = avg_price if avg_price > 0 else (
                trade.sl_price if close_reason == 'SL' else trade.tp_price
            )

            pnl = calculate_pnl(trade.side, trade.entry_price, close_price, trade.size)

            # ── Update Trade di DB ──────────────────────────────────────────
            close_trade(trade, close_reason, close_price, pnl)

            # ── Extract attributes sebelum session close ────────────────────
            # Mencegah DetachedInstanceError saat akses di luar `with` block
            trade_id = trade.id
            trade_pair = trade.pair
            trade_side = trade.side
            counter_order_id_copy = counter_order_id

        logger.info(
            f"LIVE TRADE CLOSED | ID: {trade_id} | "
            f"{trade_pair} {trade_side} | "
            f"Reason: {close_reason} | Close: {close_price:.2f} | PnL: ${pnl:.2f}"
        )

        # ── Cancel Counter-Order ───────────────────────────────────────────
        if counter_order_id_copy:
            self._cancel_counter_order(counter_order_id_copy, trade_pair, close_reason)

        # ── Send Notification ───────────────────────────────────────────────
        if self._notification_callback:
            try:
                self._notification_callback({
                    'event': 'trade_closed',
                    'trade_id': trade_id,
                    'pair': trade_pair,
                    'side': trade_side,
                    'close_reason': close_reason,
                    'close_price': close_price,
                    'pnl': pnl,
                })
            except Exception as e:
                logger.error(f"Notification callback error: {e}")

    def _cancel_counter_order(self, order_id: str, symbol: str, reason: str) -> None:
        """
        Cancel counter-order (SL hit → cancel TP, TP hit → cancel SL).
        Strategi: fetch open algo orders by symbol, cancel yang tipe berlawanan.
        Tidak bergantung pada kecocokan ID — lebih robust dari cancel by algoId.
        """
        try:
            from src.utils.exchange import get_open_algo_orders, cancel_algo_order

            # SL hit → cancel TAKE_PROFIT_MARKET yang tersisa
            # TP hit → cancel STOP_MARKET yang tersisa
            cancel_type = 'TAKE_PROFIT_MARKET' if reason == 'SL' else 'STOP_MARKET'

            open_orders = get_open_algo_orders(symbol)

            if not open_orders:
                logger.debug(
                    f"No open algo orders for {symbol} — counter-order already gone"
                )
                return

            cancelled = False
            for o in open_orders:
                order_type = o.get('type', o.get('algoType', ''))
                if order_type == cancel_type:
                    algo_id = str(o.get('algoId', ''))
                    if algo_id:
                        cancel_algo_order(algo_id, symbol)
                        logger.info(
                            f"Counter-order cancelled | algoId: {algo_id} | "
                            f"Type: {cancel_type} | Symbol: {symbol} | "
                            f"Reason: {reason} was hit"
                        )
                        cancelled = True
                        break

            if not cancelled:
                logger.debug(
                    f"No {cancel_type} algo order found for {symbol} — already gone"
                )

        except Exception as e:
            logger.error(
                f"CRITICAL: Failed to cancel counter-order for {symbol}! "
                f"Manual cancel required in Binance dashboard. Error: {e}"
            )

    def _handle_entry_fill_async(self, trade_id: int, pair: str) -> None:
        """
        Dipanggil dari background thread saat entry order fill terdeteksi via WS.
        Trigger check_pending_orders() untuk place SL/TP tanpa tunggu 15 menit.
        """
        try:
            from src.agents.math.execution_agent import ExecutionAgent
            agent = ExecutionAgent()
            results = agent.check_pending_orders()

            for r in results:
                if r.get('trade_id') == trade_id and r.get('action') == 'filled':
                    logger.info(
                        f"SL/TP placed immediately via WS fill handler | "
                        f"Trade {trade_id} | {pair}"
                    )
                    if self._notification_callback:
                        self._notification_callback({
                            'event': 'trade_filled',
                            'trade_id': trade_id,
                            'pair': pair,
                        })
                    break

        except Exception as e:
            logger.error(
                f"WS entry fill handler failed for trade {trade_id} ({pair}): {e} "
                f"— SL/TP will be placed at next 15min cycle"
            )
