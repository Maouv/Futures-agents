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

Pending order monitoring di-delegate ke OrderMonitor.
Shared utilities (send_alert, set_account_params, count_open_positions) via ExecutionMixin.
"""
import time
from datetime import UTC, datetime

import ccxt
from pydantic import BaseModel

from src.agents.math.base_agent import BaseAgent
from src.agents.math.execution_utils import ExecutionMixin
from src.agents.math.position_manager import calculate_liquidation_price
from src.agents.math.reversal_agent import ReversalResult
from src.agents.math.risk_agent import RiskResult
from src.agents.math.trend_agent import TrendResult
from src.config.config_loader import load_trading_config
from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.exchange import get_exchange, place_algo_order, reset_exchange
from src.utils.kill_switch import check_kill_switch
from src.utils.logger import logger
from src.utils.mode import get_current_mode

# ── SL Retry Constants ────────────────────────────────────────────────────
SL_MAX_RETRIES = 3
SL_RETRY_BACKOFF_BASE = 2  # seconds, exponential


class ExecutionResult(BaseModel):
    """Output dari ExecutionAgent."""
    action: str         # 'OPEN', 'SKIP', 'PENDING'
    reason: str
    trade_id: int | None = None  # ID dari paper_trades


class ExecutionAgent(ExecutionMixin, BaseAgent):
    """
    Eksekusi trade berdasarkan hasil analisis.

    PAPER MODE: INSERT ke database paper_trades (status='OPEN')
    LIVE MODE: LIMIT order di OB midpoint, lalu monitor hingga FILLED

    Shared utilities (send_alert, set_account_params, count_open_positions)
    disediakan oleh ExecutionMixin.
    Pending order monitoring di-delegate ke OrderMonitor.
    """

    def __init__(self, notification_callback=None):
        """
        Args:
            notification_callback: Optional callable untuk kirim Telegram alert.
                                   Dipanggil dengan string message.
        """
        super().__init__()
        self._notification_callback = notification_callback
        # Lazy-init OrderMonitor — dibuat saat pertama kali check_pending_orders dipanggil
        self._order_monitor = None

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
    ) -> ExecutionResult | None:
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

                # Paper mode: actual = planned (no slippage), fee estimated
                taker_fee_rate = load_trading_config().get("taker_fee_rate", 0.0004)
                paper_fee_open = risk_result.position_size * risk_result.entry_price * taker_fee_rate

                trade = PaperTrade(
                    pair=symbol,
                    side=reversal_result.signal,
                    entry_price=risk_result.entry_price,
                    sl_price=risk_result.sl_price,
                    tp_price=risk_result.tp_price,
                    size=risk_result.position_size,
                    leverage=risk_result.leverage,
                    status=status,
                    entry_timestamp=datetime.now(UTC),
                    execution_mode=get_current_mode(),
                    actual_entry_price=risk_result.entry_price,  # paper = planned, no slippage
                    slippage_entry=0.0,
                    fee_open=paper_fee_open,
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
                entry_timestamp=datetime.now(UTC),
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
                    db_trade.close_timestamp = datetime.now(UTC)
            return ExecutionResult(action="SKIP", reason="Insufficient funds")
        except ccxt.InvalidOrder as e:
            self._log_error(f"Invalid order for trade {trade_id}: {e}")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'FAILED'
                    db_trade.close_reason = 'EXCHANGE_ERROR'
                    db_trade.close_timestamp = datetime.now(UTC)
            return ExecutionResult(action="SKIP", reason=f"Invalid order: {str(e)}")
        except ccxt.NetworkError:
            self._log_error(f"Network error for trade {trade_id} — resetting exchange")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'FAILED'
                    db_trade.close_reason = 'EXCHANGE_ERROR'
                    db_trade.close_timestamp = datetime.now(UTC)
            reset_exchange()
            return ExecutionResult(action="SKIP", reason="Network error, exchange reset")
        except ccxt.ExchangeError as e:
            self._log_error(f"Exchange error for trade {trade_id}: {e}")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'FAILED'
                    db_trade.close_reason = 'EXCHANGE_ERROR'
                    db_trade.close_timestamp = datetime.now(UTC)
            return ExecutionResult(action="SKIP", reason=f"Exchange error: {str(e)}")
        except Exception as e:
            self._log_error(f"Unexpected error for trade {trade_id}: {e}")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade_id)
                if db_trade:
                    db_trade.status = 'FAILED'
                    db_trade.close_reason = 'EXCHANGE_ERROR'
                    db_trade.close_timestamp = datetime.now(UTC)
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
            taker_fee_rate = load_trading_config().get("taker_fee_rate", 0.0004)
            fee_open_live = float(order.get('fee', {}).get('cost', 0) or 0) or (
                filled_amount * filled_price * taker_fee_rate
            )

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
                    entry_timestamp=datetime.now(UTC),
                    execution_mode=get_current_mode(),
                    exchange_order_id=exchange_order_id,
                    sl_order_id=sl_order_id,
                    tp_order_id=tp_order_id,
                    liq_price=liq_price,
                    actual_entry_price=filled_price,
                    slippage_entry=filled_price - risk_result.entry_price,
                    fee_open=fee_open_live,
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
        Delegate ke OrderMonitor.check_pending_orders().

        Backward-compatible: semua caller (main.py, ws_user_stream.py) tetap
        memanggil method ini di ExecutionAgent tanpa perlu diubah.
        """
        from src.agents.math.order_monitor import OrderMonitor  # noqa: PLC0415
        if self._order_monitor is None:
            self._order_monitor = OrderMonitor(
                notification_callback=self._notification_callback
            )
        return self._order_monitor.check_pending_orders()

    def _handle_ccxt_error(self, e: Exception, context: str = "execution") -> "ExecutionResult":
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

