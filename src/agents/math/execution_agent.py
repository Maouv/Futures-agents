"""
execution_agent.py — Eksekusi trade (PAPER + LIVE mode).

PAPER MODE:
- Langsung INSERT ke DB dengan status='OPEN'
- SL/TP di-monitor oleh SLTPManager

LIVE MODE:
- Place LIMIT order di OB midpoint
- Store di DB dengan status='PENDING_ENTRY'
- Setiap cycle, cek apakah limit order sudah FILLED
- Jika FILLED → pasang SL + TP, update status='OPEN'
- Jika EXPIRED (ORDER_EXPIRY_CANDLES tercapai) → cancel order, status='EXPIRED'
"""
import ccxt
import time
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional

from src.agents.math.base_agent import BaseAgent
from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.agents.math.risk_agent import RiskResult
from src.agents.math.reversal_agent import ReversalResult
from src.agents.math.trend_agent import TrendResult
from src.utils.exchange import get_exchange, reset_exchange, place_algo_order
from src.utils.kill_switch import check_kill_switch
from src.utils.logger import logger
from src.utils.mode import get_current_mode
from src.utils.trade_utils import calculate_pnl, close_trade
from src.agents.math.position_manager import calculate_liquidation_price

# ── SL Retry Constants ────────────────────────────────────────────────────
SL_MAX_RETRIES = 3
SL_RETRY_BACKOFF_BASE = 2  # seconds, exponential


class ExecutionResult(BaseModel):
    """Output dari ExecutionAgent."""
    action: str         # 'OPEN', 'SKIP', 'PENDING'
    reason: str
    trade_id: Optional[int] = None  # ID dari paper_trades


class ExecutionAgent(BaseAgent):
    """
    Eksekusi trade berdasarkan hasil analisis.

    PAPER MODE: INSERT ke database paper_trades (status='OPEN')
    LIVE MODE: LIMIT order di OB midpoint, lalu monitor hingga FILLED
    """

    def __init__(self, notification_callback=None):
        """
        Args:
            notification_callback: Optional callable untuk kirim Telegram alert.
                                   Dipanggil dengan string message.
        """
        super().__init__()
        self._notification_callback = notification_callback

    def _send_alert(self, message: str) -> None:
        """Kirim alert via callback kalau tersedia, selalu log juga."""
        self._log_error(message)
        if self._notification_callback:
            try:
                self._notification_callback(message)
            except Exception as e:
                logger.error(f"Failed to send alert notification: {e}")

    def run(
        self,
        symbol: str,
        risk_result: RiskResult,
        reversal_result: ReversalResult,
        trend_result: TrendResult,
        confirmation_confirmed: bool
    ) -> ExecutionResult:
        """
        Jalankan eksekusi trade.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            risk_result: Output dari RiskAgent
            reversal_result: Output dari ReversalAgent
            trend_result: Output dari TrendAgent
            confirmation_confirmed: Hasil konfirmasi dari ConfirmationAgent

        Returns:
            ExecutionResult dengan action dan trade_id
        """
        # ── Shared Validation ─────────────────────────────────────────────
        validation = self._validate_signal(
            reversal_result, trend_result, confirmation_confirmed
        )
        if validation is not None:
            return validation

        # ── Kill Switch Check ─────────────────────────────────────────────
        if check_kill_switch():
            self._log_error("KILL SWITCH aktif — trade dibatalkan.")
            return ExecutionResult(action="SKIP", reason="Kill switch aktif")

        # ── Max Open Positions Per Pair Check ──────────────────────────────
        if self._count_open_positions(symbol) >= settings.MAX_OPEN_POSITIONS:
            return ExecutionResult(
                action="SKIP",
                reason=f"Max open positions tercapai untuk {symbol} ({settings.MAX_OPEN_POSITIONS}/pair)"
            )

        # ── Route by Mode ─────────────────────────────────────────────────
        if settings.EXECUTION_MODE == "live":
            return self._execute_live(symbol, risk_result, reversal_result)
        else:
            return self._execute_paper(symbol, risk_result, reversal_result)

    # _current_mode removed — use get_current_mode() from src.utils.mode

    def _validate_signal(
        self,
        reversal_result: ReversalResult,
        trend_result: TrendResult,
        confirmation_confirmed: bool
    ) -> Optional[ExecutionResult]:
        """
        Validasi signal sebelum eksekusi. Dipakai oleh paper dan live mode.
        Return ExecutionResult(SKIP) jika tidak valid, None jika valid.
        """
        # 1. Trend harus searah dengan signal
        if reversal_result.signal == "LONG" and trend_result.bias != 1:
            return ExecutionResult(
                action="SKIP",
                reason=f"Trend tidak searah (H4={trend_result.bias_label}, signal=LONG)"
            )

        if reversal_result.signal == "SHORT" and trend_result.bias != -1:
            return ExecutionResult(
                action="SKIP",
                reason=f"Trend tidak searah (H4={trend_result.bias_label}, signal=SHORT)"
            )

        # 2. Confidence minimal 60
        if reversal_result.confidence < 60:
            return ExecutionResult(
                action="SKIP",
                reason=f"Confidence terlalu rendah ({reversal_result.confidence}%)"
            )

        # 3. Konfirmasi 15m harus positif
        if not confirmation_confirmed:
            return ExecutionResult(
                action="SKIP",
                reason="Tidak ada konfirmasi di timeframe 15m"
            )

        # 4. Signal harus valid
        if reversal_result.signal not in ["LONG", "SHORT"]:
            return ExecutionResult(
                action="SKIP",
                reason=f"Signal tidak valid: {reversal_result.signal}"
            )

        return None  # Valid

    def _execute_paper(
        self,
        symbol: str,
        risk_result: RiskResult,
        reversal_result: ReversalResult
    ) -> ExecutionResult:
        """Paper mode: langsung INSERT ke DB dengan status='OPEN'."""
        try:
            with get_session() as db:
                # State 1/2 (entry_adjusted=False) → PENDING_ENTRY, tunggu harga sentuh limit
                # State 3   (entry_adjusted=True)  → OPEN langsung (market order simulation)
                is_market = risk_result.entry_adjusted
                status = 'OPEN' if is_market else 'PENDING_ENTRY'

                trade = PaperTrade(
                    pair=symbol,
                    side=reversal_result.signal,
                    entry_price=risk_result.entry_price,
                    sl_price=risk_result.sl_price,
                    tp_price=risk_result.tp_price,
                    size=risk_result.position_size,
                    leverage=risk_result.leverage,
                    status=status,
                    entry_timestamp=datetime.now(timezone.utc),
                    execution_mode=get_current_mode(),
                )
                db.add(trade)
                db.flush()
                trade_id = trade.id

            action_label = "OPENED" if is_market else "PENDING"
            self._log(
                f"PAPER TRADE {action_label} | ID: {trade_id} | "
                f"{symbol} {reversal_result.signal} | "
                f"Entry: {risk_result.entry_price:.2f} | "
                f"SL: {risk_result.sl_price:.2f} | TP: {risk_result.tp_price:.2f}"
            )

            return ExecutionResult(
                action='OPEN' if is_market else 'PENDING',
                reason=f"Trade {'opened' if is_market else 'pending'} in PAPER mode",
                trade_id=trade_id
            )

        except Exception as e:
            self._log_error(f"Gagal menyimpan paper trade: {e}")
            return ExecutionResult(action="SKIP", reason=f"Error: {str(e)}")

    def _execute_live(
        self,
        symbol: str,
        risk_result: RiskResult,
        reversal_result: ReversalResult
    ) -> ExecutionResult:
        """
        Live mode: Place order dan store di DB.

        Jika entry_adjusted (harga sudah lewat midpoint):
          → Market order (langsung fill) + langsung pasang SL/TP
        Jika entry di midpoint (normal):
          → Limit order + PENDING_ENTRY, SL/TP setelah fill
        """
        exchange = get_exchange()

        try:
            # ── Set Leverage & Margin Mode ─────────────────────────────────
            self._set_account_params(exchange, symbol, risk_result.leverage)

            # ── Balance Check ───────────────────────────────────────────────
            balance = exchange.fetch_balance()
            available_margin = float(balance.get('USDT', {}).get('free', 0))
            margin_with_buffer = risk_result.margin_required * 1.1

            if available_margin < margin_with_buffer:
                self._log_error(
                    f"Insufficient margin: available={available_margin:.2f} USDT, "
                    f"required={margin_with_buffer:.2f} USDT (with 10% buffer)"
                )
                return ExecutionResult(action="SKIP", reason="Insufficient margin")

            # ── Determine Order Type ────────────────────────────────────────
            # Jika entry di-adjust (harga sudah lewat midpoint), pakai market order
            # karena limit di current_price akan langsung trigger anyway
            if risk_result.entry_adjusted:
                return self._execute_live_market(symbol, risk_result, reversal_result, exchange)

            # ── Place LIMIT Order at OB Midpoint (normal path) ────────────
            return self._execute_live_limit(symbol, risk_result, reversal_result, exchange)

        except ccxt.InsufficientFunds:
            self._log_error("Insufficient funds during live execution")
            return ExecutionResult(action="SKIP", reason="Insufficient funds")
        except ccxt.InvalidOrder as e:
            self._log_error(f"Invalid order during live execution: {e}")
            return ExecutionResult(action="SKIP", reason=f"Invalid order: {str(e)}")
        except ccxt.NetworkError:
            self._log_error("Network error during live execution — resetting exchange")
            reset_exchange()
            return ExecutionResult(action="SKIP", reason="Network error, exchange reset")
        except ccxt.ExchangeError as e:
            self._log_error(f"Exchange error during live execution: {e}")
            return ExecutionResult(action="SKIP", reason=f"Exchange error: {str(e)}")
        except Exception as e:
            return self._handle_ccxt_error(e, "live execution")

    def _execute_live_limit(
        self,
        symbol: str,
        risk_result: RiskResult,
        reversal_result: ReversalResult,
        exchange
    ) -> ExecutionResult:
        """
        Live mode (normal path): Place LIMIT order di OB midpoint, store PENDING_ENTRY di DB.
        SL/TP dipasang SETELAH limit order FILL (di check_pending_orders).

        WRITE-THEN-EXCHANGE PATTERN:
        1. INSERT PENDING_SUBMIT dulu (tanpa order_id)
        2. Panggil exchange.create_order()
        3. Jika sukses → UPDATE ke PENDING_ENTRY dengan order_id
        4. Jika gagal → UPDATE ke FAILED
        """
        entry_price = risk_result.entry_price
        side = 'buy' if reversal_result.signal == "LONG" else 'sell'
        amount = exchange.amount_to_precision(symbol, risk_result.position_size)
        price = exchange.price_to_precision(symbol, entry_price)

        # ── Step 1: INSERT PENDING_SUBMIT dulu ─────────────────────────────
        with get_session() as db:
            trade = PaperTrade(
                pair=symbol,
                side=reversal_result.signal,
                entry_price=risk_result.entry_price,
                sl_price=risk_result.sl_price,
                tp_price=risk_result.tp_price,
                size=float(amount),
                leverage=risk_result.leverage,
                status='PENDING_SUBMIT',
                entry_timestamp=datetime.now(timezone.utc),
                execution_mode=get_current_mode(),
                exchange_order_id=None,  # Belum ada
            )
            db.add(trade)
            db.flush()
            trade_id = trade.id

        self._log(
            f"PENDING_SUBMIT | Trade {trade_id} | {symbol} {side.upper()} @ {price}"
        )

        # ── Step 2: Place order di exchange ───────────────────────────────
        try:
            self._log(
                f"Placing LIMIT {side.upper()} | {symbol} | "
                f"Price: {price} | Amount: {amount}"
            )

            order = exchange.create_order(
                symbol=symbol,
                type='limit',
                side=side,
                amount=float(amount),
                price=float(price),
                params={
                    'timeInForce': 'GTC',
                }
            )

            exchange_order_id = str(order['id'])

            self._log(
                f"LIMIT order placed | ID: {exchange_order_id} | "
                f"{symbol} {side.upper()} @ {price}"
            )

        except ccxt.InsufficientFunds:
            self._log_error(f"Insufficient funds for trade {trade_id}")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'FAILED'
                    db_trade.close_reason = 'EXCHANGE_ERROR'
                    db_trade.close_timestamp = datetime.now(timezone.utc)
            return ExecutionResult(action="SKIP", reason="Insufficient funds")
        except ccxt.InvalidOrder as e:
            self._log_error(f"Invalid order for trade {trade_id}: {e}")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'FAILED'
                    db_trade.close_reason = 'EXCHANGE_ERROR'
                    db_trade.close_timestamp = datetime.now(timezone.utc)
            return ExecutionResult(action="SKIP", reason=f"Invalid order: {str(e)}")
        except ccxt.NetworkError:
            self._log_error(f"Network error for trade {trade_id} — resetting exchange")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'FAILED'
                    db_trade.close_reason = 'EXCHANGE_ERROR'
                    db_trade.close_timestamp = datetime.now(timezone.utc)
            reset_exchange()
            return ExecutionResult(action="SKIP", reason="Network error, exchange reset")
        except ccxt.ExchangeError as e:
            self._log_error(f"Exchange error for trade {trade_id}: {e}")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'FAILED'
                    db_trade.close_reason = 'EXCHANGE_ERROR'
                    db_trade.close_timestamp = datetime.now(timezone.utc)
            return ExecutionResult(action="SKIP", reason=f"Exchange error: {str(e)}")
        except Exception as e:
            self._log_error(f"Unexpected error for trade {trade_id}: {e}")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'FAILED'
                    db_trade.close_reason = 'EXCHANGE_ERROR'
                    db_trade.close_timestamp = datetime.now(timezone.utc)
            return self._handle_ccxt_error(e, "live limit execution")

        # ── Step 3: UPDATE ke PENDING_ENTRY — TERPISAH dari Step 2 ────────
        # Order sudah ada di exchange. Kalau step ini gagal, jangan
        # mark FAILED — order-nya valid, hanya DB yang bermasalah.
        try:
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'PENDING_ENTRY'
                    db_trade.exchange_order_id = exchange_order_id

        except Exception as db_err:
            # KRITIS: order sudah ada di Binance tapi DB gagal update
            # Log exchange_order_id agar bisa recovery manual
            logger.critical(
                f"CRITICAL DB WRITE FAILED | Trade {trade_id} | {symbol} | "
                f"Order ALREADY ON BINANCE with ID: {exchange_order_id} | "
                f"Error: {db_err} | "
                f"→ Manual: update DB trade {trade_id} status=PENDING_ENTRY "
                f"exchange_order_id={exchange_order_id}"
            )
            # Jangan raise — bot tidak perlu crash, order di exchange tetap valid

        return ExecutionResult(
            action="PENDING",
            reason=f"Limit order placed, waiting for fill. Order ID: {exchange_order_id}",
            trade_id=trade_id
        )

    def _execute_live_market(
        self,
        symbol: str,
        risk_result: RiskResult,
        reversal_result: ReversalResult,
        exchange
    ) -> ExecutionResult:
        """
        Live mode (overlap path): Place MARKET order karena harga sudah lewat midpoint.
        Langsung pasang SL/TP setelah fill — tidak perlu PENDING_ENTRY.
        """
        try:
            side = 'buy' if reversal_result.signal == "LONG" else 'sell'
            amount = exchange.amount_to_precision(symbol, risk_result.position_size)

            self._log(
                f"Placing MARKET {side.upper()} | {symbol} | "
                f"Amount: {amount} | Reason: OB midpoint overlap"
            )

            order = exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=float(amount),
                params={'reduceOnly': False}
            )

            filled_price = float(order.get('average', order.get('price', risk_result.entry_price)))
            filled_amount = float(order.get('filled', risk_result.position_size))
            exchange_order_id = str(order.get('id', ''))

            self._log(
                f"MARKET order filled | ID: {exchange_order_id} | "
                f"{symbol} {side.upper()} @ ~{filled_price:.2f}"
            )

            # ── Place SL + TP Algo Orders ──────────────────────────────────
            close_side = 'sell' if reversal_result.signal == "LONG" else 'buy'
            sl_order_id = None
            tp_order_id = None

            # SL with retry
            for attempt in range(1, SL_MAX_RETRIES + 1):
                try:
                    sl_result = place_algo_order(
                        symbol=symbol,
                        side=close_side,
                        order_type='STOP_MARKET',
                        trigger_price=risk_result.sl_price,
                        quantity=filled_amount,
                        reduce_only=True,
                    )
                    sl_order_id = str(sl_result.get('algoId', ''))
                    self._log(f"SL algo placed | ID: {sl_order_id} | Trigger: {risk_result.sl_price:.2f}")
                    break
                except Exception as e:
                    self._log_error(
                        f"SL attempt {attempt}/{SL_MAX_RETRIES} FAILED: {e}"
                    )
                    if attempt < SL_MAX_RETRIES:
                        backoff = SL_RETRY_BACKOFF_BASE ** attempt
                        time.sleep(backoff)

            # TP
            try:
                tp_result = place_algo_order(
                    symbol=symbol,
                    side=close_side,
                    order_type='TAKE_PROFIT_MARKET',
                    trigger_price=risk_result.tp_price,
                    quantity=filled_amount,
                    reduce_only=True,
                )
                tp_order_id = str(tp_result.get('algoId', ''))
                self._log(f"TP algo placed | ID: {tp_order_id} | Trigger: {risk_result.tp_price:.2f}")
            except Exception as e:
                self._send_alert(
                    f"⚠️ TP GAGAL | Order {exchange_order_id} | {symbol}\n"
                    f"SL @ {risk_result.sl_price:.4f} masih aktif.\n"
                    f"Error: {e}\n"
                    f"→ Manual TP perlu dipasang di Binance!"
                )

            # ── Store OPEN di DB ───────────────────────────────────────────
            liq_price = calculate_liquidation_price(filled_price, reversal_result.signal, risk_result.leverage)

            with get_session() as db:
                trade = PaperTrade(
                    pair=symbol,
                    side=reversal_result.signal,
                    entry_price=filled_price,
                    sl_price=risk_result.sl_price,
                    tp_price=risk_result.tp_price,
                    size=filled_amount,
                    leverage=risk_result.leverage,
                    status='OPEN',
                    entry_timestamp=datetime.now(timezone.utc),
                    execution_mode=get_current_mode(),
                    exchange_order_id=exchange_order_id,
                    sl_order_id=sl_order_id,
                    tp_order_id=tp_order_id,
                    liq_price=liq_price,
                )
                db.add(trade)
                db.flush()
                trade_id = trade.id

            sl_status = "OK" if sl_order_id else "FAILED"
            tp_status = "OK" if tp_order_id else "FAILED"

            self._log(
                f"LIVE TRADE OPENED (overlap) | ID: {trade_id} | "
                f"{symbol} {reversal_result.signal} | "
                f"Entry: {filled_price:.2f} | "
                f"SL: {risk_result.sl_price:.2f} ({sl_status}) | "
                f"TP: {risk_result.tp_price:.2f} ({tp_status}) | "
                f"Liq: ${liq_price:.2f} | "
                f"SL_Order: {sl_order_id} | TP_Order: {tp_order_id}"
            )

            return ExecutionResult(
                action="OPEN",
                reason=f"Market order filled (overlap). SL: {sl_status}, TP: {tp_status}",
                trade_id=trade_id
            )

        except ccxt.InsufficientFunds:
            self._log_error("Insufficient funds during live market execution")
            return ExecutionResult(action="SKIP", reason="Insufficient funds")
        except ccxt.InvalidOrder as e:
            self._log_error(f"Invalid order during live market execution: {e}")
            return ExecutionResult(action="SKIP", reason=f"Invalid order: {str(e)}")
        except ccxt.NetworkError:
            self._log_error("Network error during live market execution — resetting exchange")
            reset_exchange()
            return ExecutionResult(action="SKIP", reason="Network error, exchange reset")
        except ccxt.ExchangeError as e:
            self._log_error(f"Exchange error during live market execution: {e}")
            return ExecutionResult(action="SKIP", reason=f"Exchange error: {str(e)}")
        except Exception as e:
            return self._handle_ccxt_error(e, "live market execution")

    def check_pending_orders(self) -> list:
        """
        Cek semua PENDING_ENTRY trades — apakah sudah FILLED atau EXPIRED.
        Dipanggil setiap cycle oleh main loop.
        Hanya berjalan di live mode — paper mode tidak punya Binance orders.

        Returns:
            List of dict dengan info aksi yang diambil per trade.
        """
        results = []

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
                        db_trade.close_timestamp = datetime.now(timezone.utc)

                self._log(f"Order {trade_exchange_order_id} canceled/expired externally")
                result["action"] = "expired"

            elif order_status == 'open':
                # Masih menunggu — cek kadaluarsa
                entry_ts = trade['entry_timestamp']
                # Handle naive datetime dari SQLite
                if entry_ts.tzinfo is None:
                    entry_ts = entry_ts.replace(tzinfo=timezone.utc)
                hours_elapsed = (datetime.now(timezone.utc) - entry_ts).total_seconds() / 3600
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
                            db_trade.close_timestamp = datetime.now(timezone.utc)

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
                    db_trade.close_timestamp = datetime.now(timezone.utc)
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

        self._log(
            f"LIVE TRADE OPENED | ID: {trade_id} | "
            f"{trade_pair} {trade_side} | "
            f"Entry: {filled_price:.2f} | "
            f"SL: {trade_sl_price:.2f} | TP: {trade_tp_price:.2f} | "
            f"Liq: ${liq_price:.2f} | "
            f"SL_Order: {sl_order_id} | TP_Order: {tp_order_id}"
        )

        return result

    def _handle_ccxt_error(self, e: Exception, context: str = "execution") -> ExecutionResult:
        """Unified ccxt error handler — returns SKIP ExecutionResult."""
        if isinstance(e, ccxt.InsufficientFunds):
            self._log_error(f"Insufficient funds: {e}")
            return ExecutionResult(action="SKIP", reason="Insufficient funds")
        if isinstance(e, ccxt.InvalidOrder):
            self._log_error(f"Invalid order: {e}")
            return ExecutionResult(action="SKIP", reason=f"Invalid order: {str(e)}")
        if isinstance(e, ccxt.NetworkError):
            self._log_error(f"Network error: {e}")
            reset_exchange()
            return ExecutionResult(action="SKIP", reason="Network error, exchange reset")
        if isinstance(e, ccxt.ExchangeError):
            self._log_error(f"Exchange error: {e}")
            return ExecutionResult(action="SKIP", reason=f"Exchange error: {str(e)}")
        self._log_error(f"Unexpected error in {context}: {e}")
        return ExecutionResult(action="SKIP", reason=f"Error: {str(e)}")

    def _set_account_params(self, exchange, symbol: str, leverage: int) -> None:
        """Set leverage dan margin mode untuk symbol. Error ditoleransi (sudah diset sebelumnya)."""
        try:
            exchange.set_leverage(leverage, symbol)
            self._log(f"Leverage set to {leverage}x for {symbol}")
        except ccxt.ExchangeError as e:
            # Biasanya karena sudah diset — toleransi
            if "No need to change leverage" in str(e) or "leverage not changed" in str(e).lower():
                self._log(f"Leverage already {leverage}x for {symbol}")
            else:
                self._log_error(f"Failed to set leverage: {e}")
                raise

        try:
            exchange.set_margin_mode(settings.FUTURES_MARGIN_TYPE, symbol)
        except ccxt.ExchangeError as e:
            if "No need to change margin type" in str(e) or "margin type not changed" in str(e).lower():
                self._log(f"Margin mode already {settings.FUTURES_MARGIN_TYPE} for {symbol}")
            else:
                self._log_error(f"Failed to set margin mode: {e}")
                raise

    def _count_open_positions(self, symbol: str) -> int:
        """Hitung jumlah posisi yang sedang terbuka untuk satu pair (OPEN + PENDING_ENTRY), filtered by current mode."""
        mode = get_current_mode()
        with get_session() as db:
            count = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.pair == symbol,
                    PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
                    PaperTrade.execution_mode == mode,
                )
                .count()
            )
        return count
