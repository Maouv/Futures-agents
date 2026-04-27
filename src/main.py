"""
main.py — Entry point dan orchestrator utama.
Loop 15 menit via APScheduler (background thread).
Telegram bot di main thread.
"""
import asyncio
import time
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.settings import settings
from src.data.storage import (
    init_db, migrate_db, PaperTrade, get_session,
    check_db_integrity, backup_db, cleanup_stranded_trades
)
from src.data.ohlcv_fetcher import fetch_ohlcv, log_weight_summary
from src.config.config_loader import load_pairs
from src.agents.math.trend_agent import TrendAgent
from src.agents.math.reversal_agent import ReversalAgent
from src.agents.math.confirmation_agent import ConfirmationAgent
from src.agents.math.risk_agent import RiskAgent, OverlapSkipError
from src.agents.math.execution_agent import ExecutionAgent
from src.agents.math.sltp_manager import check_paper_trades, check_paper_pending
from src.agents.math.position_manager import check_trailing_stop
from src.agents.llm.analyst_agent import run_analyst
from src.telegram.bot import create_bot_app, send_notification
from src.utils.logger import logger, setup_logger
from src.utils.kill_switch import check_kill_switch
from src.utils.mode import init_mode, get_current_mode, get_mode_label
from src.utils.trade_utils import calculate_pnl, close_trade


class TradingBot:
    """
    Orchestrator utama dengan proper encapsulation.
    Multi-pair sequential loop — pairs di-load dari config.json.
    """

    def __init__(self):
        self.event_loop = None
        self.scheduler = None
        self.pairs = load_pairs()
        self._ws_stream = None  # User Data Stream (live mode only)
        self._execution_agent = ExecutionAgent()  # Reusable instance

    def send_notification_sync(self, message: str):
        """
        Helper untuk mengirim notifikasi dari background thread.
        Menggunakan asyncio.run_coroutine_threadsafe untuk schedule coroutine ke main event loop.
        """
        if self.event_loop is None:
            logger.error("Event loop not initialized. Cannot send notification.")
            return

        try:
            # Schedule coroutine ke main event loop
            future = asyncio.run_coroutine_threadsafe(
                send_notification(message),
                self.event_loop
            )
            # Wait hingga selesai (timeout 10 detik)
            future.result(timeout=10)
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    def run_trading_cycle(self):
        """
        Siklus utama 15 menit (multi-pair sequential):
        Untuk setiap pair: Fetch Data → Math Agents → LLM Analyst → Risk → Execution
        Lalu: SLTP Check untuk semua pair sekaligus.
        """
        logger.info(f"=== CYCLE START {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
        logger.info(f"Processing {len(self.pairs)} pairs: {', '.join(self.pairs)}")

        # ── Kill Switch Check ──────────────────────────────────────────────
        if check_kill_switch():
            logger.critical("KILL SWITCH AKTIF — cycle dilewati")
            return

        # ── Check Pending Orders (live mode) ───────────────────────────────
        if settings.EXECUTION_MODE == "live":
            pending_results = self._execution_agent.check_pending_orders()
            for r in pending_results:
                if r.get('action') == 'filled':
                    self.send_notification_sync(
                        f"LIVE order FILLED → SL/TP placed\n"
                        f"Trade {r['trade_id']} | {r['pair']}"
                    )

        # Kumpulkan harga terbaru dari setiap pair untuk SLTP check
        current_prices = {}

        try:
            for symbol in self.pairs:
                logger.info(f"--- {symbol} ---")

                # ── 1. Fetch Data ──────────────────────────────────────────
                df_h4  = fetch_ohlcv(symbol, '4h')
                df_h1  = fetch_ohlcv(symbol, '1h')
                df_15m = fetch_ohlcv(symbol, '15m')

                if df_h4 is None or df_h1 is None or df_15m is None:
                    logger.warning(f"{symbol}: Data fetch failed or gap detected. Skipping.")
                    continue

                # Simpan harga untuk SLTP check (high/low/close)
                current_prices[symbol] = {
                    'high': float(df_15m['high'].iloc[-1]),
                    'low': float(df_15m['low'].iloc[-1]),
                    'close': float(df_15m['close'].iloc[-1]),
                }

                # ── 2. Session Filter ──────────────────────────────────────
                if df_15m.attrs.get('skip_trade', False):
                    logger.info(f"{symbol}: Outside trading session. Skipping signal generation.")
                    continue

                # ── 3. Math Agents ─────────────────────────────────────────
                trend        = TrendAgent().run(df_h4)
                reversal     = ReversalAgent().run(df_h1, swing_size=3)
                confirmation = ConfirmationAgent().run(df_15m, reversal.signal)

                logger.info(f"{symbol}: Trend={trend.bias_label} | Signal={reversal.signal} | Confirmed={confirmation.confirmed}")

                # ── 4. LLM Analyst ─────────────────────────────────────────
                current_price = float(df_15m['close'].iloc[-1])
                decision = run_analyst(trend, reversal, confirmation, current_price, symbol)
                logger.info(f"{symbol}: Analyst={decision.action} (confidence: {decision.confidence}) [{decision.source}]")

                # ── 5. Risk & Execution ────────────────────────────────────
                if decision.action in ('LONG', 'SHORT') and decision.confidence >= 60:
                    if reversal.ob is not None:
                        try:
                            risk = RiskAgent().run(decision.action, reversal.ob, df_h1, current_price=current_price)
                        except OverlapSkipError as e:
                            logger.info(f"{symbol}: SKIP (overlap) — {e}")
                            continue
                        except ValueError as e:
                            logger.warning(f"{symbol}: RiskAgent validation failed: {e}")
                            continue
                        result = self._execution_agent.run(
                            symbol=symbol,
                            risk_result=risk,
                            reversal_result=reversal,
                            trend_result=trend,
                            confirmation_confirmed=confirmation.confirmed,
                        )

                        if result.action == 'OPEN':
                            overlap_tag = " [OVERLAP]" if risk.entry_adjusted else ""
                            self.send_notification_sync(
                                f"{get_mode_label()} {decision.action} | {symbol}{overlap_tag}\n"
                                f"Entry: ${risk.entry_price:,.2f}\n"
                                f"SL: ${risk.sl_price:,.2f} | TP: ${risk.tp_price:,.2f}\n"
                                f"Risk: ${risk.risk_usd:.2f} | RR: 1:{settings.RISK_REWARD_RATIO}"
                            )
                        elif result.action == 'PENDING':
                            self.send_notification_sync(
                                f"{get_mode_label()} {decision.action} PENDING | {symbol}\n"
                                f"Limit @ ${risk.entry_price:,.2f}\n"
                                f"SL: ${risk.sl_price:,.2f} | TP: ${risk.tp_price:,.2f}\n"
                                f"Waiting for fill..."
                            )
                    else:
                        logger.info(f"{symbol}: No OB available for entry. Skipping.")
                else:
                    logger.info(f"{symbol}: SKIP — {decision.reasoning}")

            # ── 6. Paper Pending Fill Check ─────────────────────────────────
            if current_prices:
                self._run_paper_pending_check(current_prices)

            # ── 7. SLTP Check (semua pair sekaligus) ────────────────────────
            if current_prices:
                self._run_sltp_check(current_prices)

            # ── 8. Trailing Stop Check (live mode only) ────────────────────
            if current_prices:
                self._run_trailing_stop_check(current_prices)

        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)

    def _run_sltp_check(self, current_prices: dict):
        """Cek SL/TP paper trades dengan harga terbaru dari semua pair."""
        closed = check_paper_trades(current_prices)

        for trade in closed:
            emoji = "✅" if trade['pnl'] > 0 else "❌"
            self.send_notification_sync(
                f"{emoji} {trade['reason']} Hit\n"
                f"{trade['pair']} {trade['side']}\n"
                f"PnL: ${trade['pnl']:.2f}"
            )

    def _run_paper_pending_check(self, current_prices: dict):
        """Cek PENDING_ENTRY paper trades untuk fill/expiry (paper mode only)."""
        results = check_paper_pending(current_prices)

        for r in results:
            if r['action'] == 'filled':
                self.send_notification_sync(
                    f"📄 PAPER Order FILLED\n"
                    f"{r['pair']} {r['side']}\n"
                    f"Entry: ${r['entry_price']:,.2f}"
                )
            elif r['action'] == 'expired':
                self.send_notification_sync(
                    f"📄 PAPER Order EXPIRED\n"
                    f"{r['pair']} {r['side']}"
                )

    def _run_trailing_stop_check(self, current_prices: dict):
        """Cek trailing stop untuk live trades (hanya live/testnet mode)."""
        updated = check_trailing_stop(current_prices)

        for trade in updated:
            if trade.get('emergency'):
                self.send_notification_sync(
                    f"EMERGENCY CLOSE (trailing SL fail)\n"
                    f"{trade['pair']} {trade['side']}\n"
                    f"Old SL: ${trade['old_sl']:.2f} — new SL placement failed"
                )
            else:
                self.send_notification_sync(
                    f"Trailing SL Updated\n"
                    f"{trade['pair']} {trade['side']}\n"
                    f"SL: ${trade['old_sl']:.2f} → ${trade['new_sl']:.2f}\n"
                    f"Step: {trade['step_index']}"
                )

    def run(self):
        """Entry point utama."""
        setup_logger()
        logger.info(f"Starting Futures Agent | Mode: {settings.EXECUTION_MODE.upper()}")

        # ── Startup Safety Checks ──────────────────────────────────────────
        if settings.EXECUTION_MODE == "live":
            if not settings.USE_TESTNET and not settings.CONFIRM_MAINNET:
                logger.critical(
                    "FATAL: EXECUTION_MODE=live, USE_TESTNET=False, tapi CONFIRM_MAINNET tidak True. "
                    "Tambahkan CONFIRM_MAINNET=True di .env untuk konfirmasi mainnet."
                )
                return

            logger.warning(f"LIVE MODE AKTIF — {get_mode_label()} — uang sungguhan terlibat!")

        logger.info(f"Pairs: {', '.join(self.pairs)}")

        # Init DB + Migration
        init_db()
        migrate_db()

        # ── DB Integrity Check ───────────────────────────────────────────
        if not check_db_integrity():
            logger.critical("DB CORRUPT — stopping bot. Manual intervention required!")
            return

        # ── Cleanup Stranded Trades ───────────────────────────────────────
        cleanup_count = cleanup_stranded_trades()
        if cleanup_count > 0:
            self.send_notification_sync(
                f"⚠️ Startup Cleanup: {cleanup_count} stranded trades marked FAILED"
            )

        # ── Auto-Backup ───────────────────────────────────────────────────
        backup_db()

        # Log weight estimate (sekali saat startup)
        log_weight_summary(len(self.pairs))

        # ── Position Reconciliation (live mode) ────────────────────────────
        if settings.EXECUTION_MODE == "live":
            self._reconcile_positions()

        # ── Mode Switch Alert ─────────────────────────────────────────────
        self._check_mode_switch_trades()

        # ── Start User Data Stream (live mode) ─────────────────────────────
        if settings.EXECUTION_MODE == "live":
            from src.data.ws_user_stream import UserDataStream
            self._ws_stream = UserDataStream(
                notification_callback=self._ws_notification_handler
            )
            self._ws_stream.start()

        # Buat event loop untuk main thread
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)

        # Scheduler — jalankan di background thread
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(
            self.run_trading_cycle,
            CronTrigger(minute='0,15,30,45'),
            id='trading_cycle',
            max_instances=1,  # Jangan overlap
            misfire_grace_time=60,
        )
        self.scheduler.start()
        logger.info("Scheduler started. Trading cycle every 15 minutes.")

        # Telegram bot di main thread
        app = create_bot_app()
        logger.info("Telegram bot started.")

        try:
            app.run_polling(drop_pending_updates=True)
        except KeyboardInterrupt:
            if self._ws_stream:
                self._ws_stream.stop()
            self.scheduler.shutdown()
            logger.info("Bot stopped.")

    def _ws_notification_handler(self, data: dict) -> None:
        """Handle notification dari WS thread — bridge ke Telegram."""
        if data.get('event') == 'trade_closed':
            trade = data
            emoji = "+" if trade.get('pnl', 0) > 0 else "-"
            self.send_notification_sync(
                f"{emoji} LIVE {trade['close_reason']} Hit\n"
                f"{trade['pair']} {trade['side']}\n"
                f"Close: ${trade.get('close_price', 0):,.2f} | PnL: ${trade.get('pnl', 0):.2f}"
            )

    @staticmethod
    def _pair_to_ccxt_symbol(pair: str) -> str:
        """Convert 'BTCUSDT' to 'BTC/USDT:USDT' for ccxt."""
        if pair.endswith('USDT'):
            base = pair[:-4]
            return f"{base}/USDT:USDT"
        return pair

    def _get_close_price_for_trade(self, trade, exchange) -> float | None:
        """
        Attempt to get actual close price for a reconciled trade.
        Priority: SL/TP order fill price → current market price.
        """
        symbol = self._pair_to_ccxt_symbol(trade.pair)

        # Try fetching SL/TP order to get actual fill price
        for order_id_field in ('sl_order_id', 'tp_order_id'):
            order_id = getattr(trade, order_id_field, None)
            if order_id:
                try:
                    order = exchange.fetch_order(order_id, symbol)
                    if order and order.get('status') == 'closed':
                        fill_price = float(order.get('average', 0) or order.get('price', 0) or 0)
                        if fill_price > 0:
                            return fill_price
                except Exception as e:
                    logger.warning(f"Could not fetch {order_id_field}={order_id}: {e}")

        # Fallback: current market price
        try:
            ticker = exchange.fetch_ticker(symbol)
            return float(ticker['last'])
        except Exception as e:
            logger.warning(f"Could not fetch ticker for {symbol}: {e}")
            return None

    def _reconcile_positions(self) -> None:
        """
        Reconcile DB state dengan Binance actual positions saat startup.
        Mencegah orphan positions setelah crash/restart.

        OPEN trades    → dicek via fetch_positions() (posisi aktif yang sudah fill)
        PENDING_ENTRY  → dicek via fetch_open_orders() (limit orders yang belum fill)
        Keduanya HARUS dicek dengan cara berbeda — fetch_positions() tidak akan
        pernah return limit order yang belum fill, sehingga PENDING_ENTRY yang valid
        akan salah dikira orphan kalau dicek dengan cara yang sama.
        """
        from src.utils.exchange import get_exchange

        logger.info("Reconciling positions with Binance...")
        exchange = get_exchange()

        try:
            # ── 1. Fetch active positions (untuk cek OPEN trades) ──────────
            positions = exchange.fetch_positions()
            active_pairs = set()
            for pos in positions:
                amt = float(pos.get('contracts', pos.get('positionAmt', 0)))
                if abs(amt) > 0:
                    symbol = pos.get('info', {}).get('symbol', '')
                    if not symbol:
                        unified = pos.get('symbol', '')
                        if '/' in unified:
                            base_quote = unified.split(':')[0]
                            symbol = base_quote.replace('/', '')
                        else:
                            symbol = unified
                    active_pairs.add(symbol)

            # ── 2. Fetch open limit orders (untuk cek PENDING_ENTRY trades) ─
            # Fetch per-symbol (bukan semua sekaligus) untuk hindari rate limit.
            # fetch_open_orders() tanpa symbol dibatasi 1 call per 352 detik oleh Binance.
            active_order_ids = set()
            for pair in self.pairs:
                try:
                    ccxt_sym = self._pair_to_ccxt_symbol(pair)
                    orders = exchange.fetch_open_orders(ccxt_sym)
                    for o in orders:
                        oid = str(o.get('id', ''))
                        if oid:
                            active_order_ids.add(oid)
                except Exception as e:
                    logger.warning(f"Could not fetch open orders for {pair}: {e}")

            logger.info(
                f"Binance state: {len(active_pairs)} active positions, "
                f"{len(active_order_ids)} open orders"
            )

            # ── 3. Reconcile DB trades ─────────────────────────────────────
            with get_session() as db:
                open_trades = db.query(PaperTrade).filter(
                    PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
                    PaperTrade.execution_mode.in_(['testnet', 'mainnet']),
                ).all()

                for trade in open_trades:
                    if trade.status == 'OPEN':
                        # OPEN = posisi aktif — cek via fetch_positions()
                        if trade.pair not in active_pairs:
                            close_price = self._get_close_price_for_trade(trade, exchange)
                            pnl = (
                                calculate_pnl(trade.side, trade.entry_price, close_price, trade.size)
                                if close_price else None
                            )
                            close_trade(trade, 'RECONCILED', close_price=close_price, pnl=pnl)
                            price_info = (
                                f" | Close: ${close_price:,.2f} | PnL: ${pnl:.2f}"
                                if close_price else " | Close price unavailable"
                            )
                            logger.warning(
                                f"Reconciled OPEN: Trade {trade.id} ({trade.pair}) — "
                                f"no position on Binance{price_info}"
                            )

                    elif trade.status == 'PENDING_ENTRY':
                        # PENDING_ENTRY = limit order belum fill — cek via fetch_open_orders()
                        order_id = trade.exchange_order_id
                        if not order_id:
                            # Tidak ada order_id sama sekali — orphan pasti
                            close_trade(trade, 'RECONCILED', close_price=None, pnl=None)
                            logger.warning(
                                f"Reconciled PENDING_ENTRY: Trade {trade.id} ({trade.pair}) — "
                                f"no exchange_order_id in DB"
                            )
                        elif order_id not in active_order_ids:
                            # Order sudah tidak ada di Binance (filled/cancelled/expired)
                            # Cek apakah sudah fill dengan fetch_order langsung
                            try:
                                ccxt_symbol = self._pair_to_ccxt_symbol(trade.pair)
                                order = exchange.fetch_order(order_id, ccxt_symbol)
                                order_status = order.get('status', '')
                                if order_status in ('filled', 'closed'):
                                    # Order fill tapi DB belum update — akan dihandle
                                    # di check_pending_orders() cycle berikutnya
                                    logger.info(
                                        f"PENDING_ENTRY Trade {trade.id} ({trade.pair}) — "
                                        f"order {order_id} filled, will be handled next cycle"
                                    )
                                else:
                                    # Order cancelled/expired di luar bot
                                    close_trade(trade, 'RECONCILED', close_price=None, pnl=None)
                                    logger.warning(
                                        f"Reconciled PENDING_ENTRY: Trade {trade.id} ({trade.pair}) — "
                                        f"order {order_id} status={order_status} on Binance"
                                    )
                            except Exception as e:
                                logger.warning(
                                    f"Could not verify PENDING_ENTRY Trade {trade.id} "
                                    f"order {order_id}: {e} — leaving as PENDING_ENTRY"
                                )
                        else:
                            # Order masih ada di Binance — biarkan, sudah valid
                            logger.info(
                                f"PENDING_ENTRY Trade {trade.id} ({trade.pair}) — "
                                f"order {order_id} still open on Binance, OK"
                            )

            logger.info(f"Position reconciliation complete.")

        except Exception as e:
            logger.error(f"Position reconciliation failed: {e}")
            logger.warning("Proceeding without reconciliation — monitor manually!")

    def _check_mode_switch_trades(self) -> None:
        """
        Deteksi trades dari mode berbeda saat startup.
        Alert jika ada trades yang mungkin orphan akibat mode switch.
        """
        current_mode = get_current_mode()

        with get_session() as db:
            other_mode_trades = db.query(PaperTrade).filter(
                PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
                PaperTrade.execution_mode != current_mode,
                PaperTrade.execution_mode.isnot(None),
            ).all()

            if other_mode_trades:
                trade_info = [
                    f"  - Trade {t.id}: {t.pair} {t.side} ({t.execution_mode})"
                    for t in other_mode_trades
                ]
                msg = (
                    f"⚠️ MODE SWITCH WARNING\n"
                    f"Current mode: {current_mode.upper()}\n"
                    f"Found {len(other_mode_trades)} trades from other modes:\n"
                    + "\n".join(trade_info)
                )
                logger.warning(msg)
                self.send_notification_sync(msg)


def main():
    """Wrapper untuk backward compatibility."""
    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
