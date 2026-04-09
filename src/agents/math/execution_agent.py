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
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional

from src.agents.math.base_agent import BaseAgent
from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.agents.math.risk_agent import RiskResult
from src.agents.math.reversal_agent import ReversalResult
from src.agents.math.trend_agent import TrendResult
from src.utils.exchange import get_exchange, reset_exchange
from src.utils.kill_switch import check_kill_switch
from src.utils.logger import logger


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

    @staticmethod
    def _current_mode() -> str:
        """Return execution mode tag: 'paper', 'testnet', or 'mainnet'."""
        if settings.EXECUTION_MODE != "live":
            return "paper"
        return "testnet" if settings.USE_TESTNET else "mainnet"

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
                trade = PaperTrade(
                    pair=symbol,
                    side=reversal_result.signal,
                    entry_price=risk_result.entry_price,
                    sl_price=risk_result.sl_price,
                    tp_price=risk_result.tp_price,
                    size=risk_result.position_size,
                    leverage=risk_result.leverage,
                    status='OPEN',
                    entry_timestamp=datetime.now(timezone.utc),
                    execution_mode=self._current_mode(),
                )
                db.add(trade)
                db.flush()
                trade_id = trade.id

            self._log(
                f"PAPER TRADE OPENED | ID: {trade_id} | "
                f"{symbol} {reversal_result.signal} | "
                f"Entry: {risk_result.entry_price:.2f} | "
                f"SL: {risk_result.sl_price:.2f} | TP: {risk_result.tp_price:.2f}"
            )

            return ExecutionResult(
                action="OPEN",
                reason=f"Trade opened in PAPER mode",
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
        Live mode: Place LIMIT order di OB midpoint, store PENDING_ENTRY di DB.
        SL/TP dipasang SETELAH limit order FILL (di check_pending_orders).
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

            # ── Place LIMIT Order at OB Midpoint ──────────────────────────
            entry_price = risk_result.entry_price
            side = 'buy' if reversal_result.signal == "LONG" else 'sell'
            amount = exchange.amount_to_precision(symbol, risk_result.position_size)
            price = exchange.price_to_precision(symbol, entry_price)

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
                    'timeInForce': 'GTC',  # Good Till Cancelled — kita cancel manual saat kadaluarsa
                }
            )

            exchange_order_id = str(order['id'])

            self._log(
                f"LIMIT order placed | ID: {exchange_order_id} | "
                f"{symbol} {side.upper()} @ {price}"
            )

            # ── Store PENDING_ENTRY di DB ─────────────────────────────────
            with get_session() as db:
                trade = PaperTrade(
                    pair=symbol,
                    side=reversal_result.signal,
                    entry_price=risk_result.entry_price,
                    sl_price=risk_result.sl_price,
                    tp_price=risk_result.tp_price,
                    size=float(amount),
                    leverage=risk_result.leverage,
                    status='PENDING_ENTRY',
                    entry_timestamp=datetime.now(timezone.utc),
                    execution_mode=self._current_mode(),
                    exchange_order_id=exchange_order_id,
                )
                db.add(trade)
                db.flush()
                trade_id = trade.id

            return ExecutionResult(
                action="PENDING",
                reason=f"Limit order placed, waiting for fill. Order ID: {exchange_order_id}",
                trade_id=trade_id
            )

        except ccxt.InsufficientFunds as e:
            self._log_error(f"Insufficient funds: {e}")
            return ExecutionResult(action="SKIP", reason="Insufficient funds")
        except ccxt.InvalidOrder as e:
            self._log_error(f"Invalid order: {e}")
            return ExecutionResult(action="SKIP", reason=f"Invalid order: {str(e)}")
        except ccxt.NetworkError as e:
            self._log_error(f"Network error: {e}")
            reset_exchange()
            return ExecutionResult(action="SKIP", reason="Network error, exchange reset")
        except ccxt.ExchangeError as e:
            self._log_error(f"Exchange error: {e}")
            return ExecutionResult(action="SKIP", reason=f"Exchange error: {str(e)}")
        except Exception as e:
            self._log_error(f"Unexpected error in live execution: {e}")
            return ExecutionResult(action="SKIP", reason=f"Error: {str(e)}")

    def check_pending_orders(self) -> list:
        """
        Cek semua PENDING_ENTRY trades — apakah sudah FILLED atau EXPIRED.
        Dipanggil setiap cycle oleh main loop.

        Returns:
            List of dict dengan info aksi yang diambil per trade.
        """
        results = []

        with get_session() as db:
            pending_trades = (
                db.query(PaperTrade)
                .filter(PaperTrade.status == 'PENDING_ENTRY')
                .all()
            )

        for trade in pending_trades:
            result = self._check_single_pending(trade)
            results.append(result)

        return results

    def _check_single_pending(self, trade: PaperTrade) -> dict:
        """
        Cek satu pending trade: sudah filled, expired, atau masih menunggu?
        """
        exchange = get_exchange()
        result = {"trade_id": trade.id, "pair": trade.pair, "action": "none"}

        try:
            # ── Cek Order Status di Binance ────────────────────────────────
            order = exchange.fetch_order(trade.exchange_order_id, trade.pair)
            order_status = order.get('status', 'unknown')

            if order_status == 'filled':
                result = self._handle_fill(trade, order, exchange)

            elif order_status == 'canceled' or order_status == 'expired':
                # Order di-cancel secara eksternal — update DB
                with get_session() as db:
                    db_trade = db.query(PaperTrade).get(trade.id)
                    if db_trade:
                        db_trade.status = 'EXPIRED'
                        db_trade.close_reason = 'EXPIRED'
                        db_trade.close_timestamp = datetime.now(timezone.utc)

                self._log(f"Order {trade.exchange_order_id} canceled/expired externally")
                result["action"] = "expired"

            elif order_status == 'open':
                # Masih menunggu — cek kadaluarsa
                hours_elapsed = (datetime.now(timezone.utc) - trade.entry_timestamp).total_seconds() / 3600
                candles_elapsed = hours_elapsed  # 1 candle H1 = 1 jam
                candles_remaining = settings.ORDER_EXPIRY_CANDLES - candles_elapsed

                if candles_elapsed >= settings.ORDER_EXPIRY_CANDLES:
                    # Kadaluarsa — cancel order di Binance
                    try:
                        exchange.cancel_order(trade.exchange_order_id, trade.pair)
                        self._log(
                            f"Limit order EXPIRED after {candles_elapsed:.1f} H1 candles | "
                            f"Trade {trade.id} | Order {trade.exchange_order_id}"
                        )
                    except ccxt.OrderNotFound:
                        self._log(f"Order {trade.exchange_order_id} already gone — treating as expired")
                    except Exception as e:
                        self._log_error(f"Failed to cancel expired order {trade.exchange_order_id}: {e}")

                    with get_session() as db:
                        db_trade = db.query(PaperTrade).get(trade.id)
                        if db_trade:
                            db_trade.status = 'EXPIRED'
                            db_trade.close_reason = 'EXPIRED'
                            db_trade.close_timestamp = datetime.now(timezone.utc)

                    result["action"] = "expired"
                else:
                    self._log(
                        f"Pending order still waiting | Trade {trade.id} | "
                        f"{candles_remaining:.1f} H1 candles remaining"
                    )
                    result["action"] = "waiting"

            else:
                self._log_error(
                    f"Unknown order status '{order_status}' for trade {trade.id}"
                )

        except ccxt.OrderNotFound:
            self._log_error(f"Order {trade.exchange_order_id} not found on exchange")
            with get_session() as db:
                db_trade = db.query(PaperTrade).get(trade.id)
                if db_trade:
                    db_trade.status = 'EXPIRED'
                    db_trade.close_reason = 'EXPIRED'
                    db_trade.close_timestamp = datetime.now(timezone.utc)
            result["action"] = "expired"

        except Exception as e:
            self._log_error(f"Error checking pending order {trade.id}: {e}")
            result["action"] = "error"

        return result

    def _handle_fill(self, trade: PaperTrade, order: dict, exchange) -> dict:
        """
        Limit order sudah FILLED — pasang SL + TP di Binance.
        Ini momen paling kritis: kalau SL/TP gagal, posisi TIDAK terproteksi.
        """
        result = {"trade_id": trade.id, "pair": trade.pair, "action": "filled"}
        filled_price = float(order.get('average', order.get('price', trade.entry_price)))
        filled_amount = float(order.get('filled', trade.size))

        # Update entry_price dengan actual fill price
        close_side = 'sell' if trade.side == 'LONG' else 'buy'

        # ── Place SL (stop_market) ────────────────────────────────────────
        sl_order_id = None
        try:
            sl_order = exchange.create_order(
                symbol=trade.pair,
                type='stop_market',
                side=close_side,
                amount=filled_amount,
                params={
                    'stopPrice': exchange.price_to_precision(trade.pair, trade.sl_price),
                    'closePosition': True,
                    'reduceOnly': True,
                }
            )
            sl_order_id = str(sl_order['id'])
            self._log(f"SL order placed | ID: {sl_order_id} | Stop: {trade.sl_price:.2f}")
        except Exception as e:
            self._log_error(
                f"CRITICAL: SL order FAILED for trade {trade.id}! "
                f"Position is UNPROTECTED. Error: {e}"
            )
            # TODO: Send Telegram CRITICAL alert
            # For now, log is enough — WS handler or manual intervention needed

        # ── Place TP (take_profit_market) ─────────────────────────────────
        tp_order_id = None
        try:
            tp_order = exchange.create_order(
                symbol=trade.pair,
                type='take_profit_market',
                side=close_side,
                amount=filled_amount,
                params={
                    'stopPrice': exchange.price_to_precision(trade.pair, trade.tp_price),
                    'closePosition': True,
                    'reduceOnly': True,
                }
            )
            tp_order_id = str(tp_order['id'])
            self._log(f"TP order placed | ID: {tp_order_id} | Stop: {trade.tp_price:.2f}")
        except Exception as e:
            self._log_error(
                f"ERROR: TP order FAILED for trade {trade.id}. "
                f"SL still protects capital. Error: {e}"
            )

        # ── Update DB ──────────────────────────────────────────────────────
        with get_session() as db:
            db_trade = db.query(PaperTrade).get(trade.id)
            if db_trade:
                db_trade.status = 'OPEN'
                db_trade.entry_price = filled_price
                db_trade.size = filled_amount
                db_trade.sl_order_id = sl_order_id
                db_trade.tp_order_id = tp_order_id
                db_trade.exchange_order_id = str(order.get('id', trade.exchange_order_id))

        self._log(
            f"LIVE TRADE OPENED | ID: {trade.id} | "
            f"{trade.pair} {trade.side} | "
            f"Entry: {filled_price:.2f} | "
            f"SL: {trade.sl_price:.2f} | TP: {trade.tp_price:.2f} | "
            f"SL_Order: {sl_order_id} | TP_Order: {tp_order_id}"
        )

        return result

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
        """Hitung jumlah posisi yang sedang terbuka untuk satu pair (OPEN + PENDING_ENTRY)."""
        with get_session() as db:
            count = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.pair == symbol,
                    PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
                )
                .count()
            )
        return count
