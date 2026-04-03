"""
main.py — Entry point dan orchestrator utama.
Loop 15 menit via APScheduler (background thread).
Telegram bot di main thread.
"""
import asyncio
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.settings import settings
from src.data.storage import init_db
from src.data.ohlcv_fetcher import fetch_ohlcv
from src.agents.math.trend_agent import TrendAgent
from src.agents.math.reversal_agent import ReversalAgent
from src.agents.math.confirmation_agent import ConfirmationAgent
from src.agents.math.risk_agent import RiskAgent
from src.agents.math.execution_agent import ExecutionAgent
from src.agents.math.sltp_manager import check_paper_trades
from src.agents.llm.analyst_agent import run_analyst
from src.telegram.bot import create_bot_app, send_notification
from src.utils.logger import logger, setup_logger

SYMBOL = "BTCUSDT"

# Global event loop reference untuk background thread
_event_loop = None


def _send_notification_sync(message: str):
    """
    Helper untuk mengirim notifikasi dari background thread.
    Menggunakan asyncio.run_coroutine_threadsafe untuk schedule coroutine ke main event loop.
    """
    global _event_loop
    if _event_loop is None:
        logger.error("Event loop not initialized. Cannot send notification.")
        return

    try:
        # Schedule coroutine ke main event loop
        future = asyncio.run_coroutine_threadsafe(
            send_notification(message),
            _event_loop
        )
        # Wait hingga selesai (timeout 10 detik)
        future.result(timeout=10)
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


def run_trading_cycle():
    """
    Siklus utama 15 menit:
    Fetch Data → Math Agents → LLM Analyst → Risk → Execution → SLTP Check
    """
    logger.info(f"=== CYCLE START {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")

    try:
        # ── 1. Fetch Data ──────────────────────────────────────────────
        df_h4  = fetch_ohlcv(SYMBOL, '4h')
        df_h1  = fetch_ohlcv(SYMBOL, '1h')
        df_15m = fetch_ohlcv(SYMBOL, '15m')

        if df_h4 is None or df_h1 is None or df_15m is None:
            logger.warning("Data fetch failed or gap detected. Skipping cycle.")
            return

        # ── 2. Session Filter ──────────────────────────────────────────
        if df_15m.attrs.get('skip_trade', False):
            logger.info("Outside trading session. Checking SLTP only.")
            _run_sltp_check(df_15m)
            return

        current_price = float(df_15m['close'].iloc[-1])

        # ── 3. Math Agents ─────────────────────────────────────────────
        trend        = TrendAgent().run(df_h4)
        reversal     = ReversalAgent().run(df_h1, swing_size=3)
        confirmation = ConfirmationAgent().run(df_15m, reversal.signal)

        logger.info(f"Trend: {trend.bias_label} | Signal: {reversal.signal} | Confirmed: {confirmation.confirmed}")

        # ── 4. LLM Analyst ─────────────────────────────────────────────
        decision = run_analyst(trend, reversal, confirmation, current_price)
        logger.info(f"Analyst: {decision.action} (confidence: {decision.confidence}) [{decision.source}]")

        # ── 5. Risk & Execution ────────────────────────────────────────
        if decision.action in ('LONG', 'SHORT') and decision.confidence >= 60:
            if reversal.ob is not None:
                risk = RiskAgent().run(decision.action, reversal.ob, df_h1)
                result = ExecutionAgent().run(
                    symbol=SYMBOL,
                    risk_result=risk,
                    reversal_result=reversal,
                    trend_result=trend,
                    confirmation_confirmed=confirmation.confirmed,
                )

                if result.action == 'OPEN':
                    _send_notification_sync(
                        f"🔔 Paper {decision.action}\n"
                        f"Entry: ${risk.entry_price:,.2f}\n"
                        f"SL: ${risk.sl_price:,.2f} | TP: ${risk.tp_price:,.2f}\n"
                        f"Risk: ${risk.risk_usd:.2f} | RR: 1:{settings.RISK_REWARD_RATIO}"
                    )
            else:
                logger.info("No OB available for entry. Skipping.")
        else:
            logger.info(f"SKIP — {decision.reasoning}")

        # ── 6. SLTP Check ──────────────────────────────────────────────
        _run_sltp_check(df_15m)

    except Exception as e:
        logger.error(f"Cycle error: {e}", exc_info=True)


def _run_sltp_check(df_15m):
    """Cek SL/TP paper trades dengan harga close 15m terbaru."""
    current_price = float(df_15m['close'].iloc[-1])
    closed = check_paper_trades({SYMBOL: current_price})

    for trade in closed:
        emoji = "✅" if trade['pnl'] > 0 else "❌"
        _send_notification_sync(
            f"{emoji} {trade['reason']} Hit\n"
            f"{trade['pair']} {trade['side']}\n"
            f"PnL: ${trade['pnl']:.2f}"
        )


def main():
    global _event_loop
    setup_logger()
    logger.info(f"Starting Futures Agent | Mode: {settings.EXECUTION_MODE.upper()}")

    # Init DB
    init_db()

    # Buat event loop untuk main thread
    _event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_event_loop)

    # Scheduler — jalankan di background thread
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_trading_cycle,
        CronTrigger(minute='0,15,30,45'),
        id='trading_cycle',
        max_instances=1,  # Jangan overlap
        misfire_grace_time=60,
    )
    scheduler.start()
    logger.info("Scheduler started. Trading cycle every 15 minutes.")

    # Telegram bot di main thread
    app = create_bot_app()
    logger.info("Telegram bot started.")

    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
