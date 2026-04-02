# 🤖 PHASE 5 MASTER PROMPT — Paper Execution, Telegram & Main Orchestrator
# Untuk: Claude Code
# Prasyarat: Phase 3 dan Phase 4 selesai

---

## BRIEFING PHASE 5

Menyatukan semua agent menjadi satu siklus 15 menit di `main.py`.
Menambahkan Telegram interface untuk monitoring dan perintah.
Setelah phase ini bot sudah bisa jalan paper trading 24/7.

**WAJIB BACA:**
- `CLAUDE.md` section 1 (Prime Directive — paper mode default)
- `PRD.md` FR-4 (Paper Execution) dan FR-5 (Telegram)
- `src/agents/math/` — semua output models Phase 3
- `src/agents/llm/` — semua output Phase 4

---

## ⚠️ ATURAN KRITIS PHASE 5

1. **EXECUTION_MODE=paper by default** — guard clause wajib ada di setiap fungsi eksekusi
2. **APScheduler** untuk loop 15 menit — bukan `while True` + `time.sleep()`
3. **Threading** — Telegram bot dan loop utama harus di thread terpisah
4. **DILARANG WebSocket market data** — semua data via REST ccxt
5. **Notifikasi Telegram** — kirim saat: entry, TP hit, SL hit, error kritis

---

## 📦 TASK LIST PHASE 5

### Task 5.1 — `src/data/ohlcv_fetcher.py` (update)

Pastikan fetch limit per timeframe sesuai:
```python
FETCH_LIMITS = {
    '15m': 200,
    '1h':  500,
    '4h':  300,
}

def fetch_ohlcv(symbol: str, timeframe: str) -> pd.DataFrame | None:
    """
    Fetch OHLCV dari Binance Futures via ccxt REST.
    Return None jika gap terdeteksi atau error.
    Attach skip_trade flag jika di luar session.
    """
```

---

### Task 5.2 — `src/telegram/bot.py`

```python
"""
bot.py — Telegram bot interface.
Router: pesan command → CommanderAgent, pesan chat → ConciergeAgent.
"""
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from src.config.settings import settings
from src.agents.llm.commander_agent import run_commander
from src.agents.llm.concierge_agent import run_concierge
from src.utils.logger import logger


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route pesan ke Commander atau Concierge."""
    message = update.message.text
    chat_id = str(update.effective_chat.id)

    # Hanya proses dari chat ID yang diizinkan
    if chat_id != settings.TELEGRAM_CHAT_ID:
        return

    logger.info(f"[Telegram] Message: {message[:50]}")

    # Deteksi command vs chat
    is_command = message.startswith('/') or any(
        kw in message.lower()
        for kw in ['status', 'trades', 'history', 'performance', 'pause', 'resume', 'close all']
    )

    if is_command:
        result = run_commander(message)
        response = await _execute_command(result)
    else:
        # Ambil context trade untuk Concierge
        trade_context = _get_trade_context()
        response = run_concierge(message, trade_context)

    await update.message.reply_text(response)


async def _execute_command(result) -> str:
    """Eksekusi fungsi berdasarkan CommanderResult."""
    from src.telegram.commands import COMMAND_HANDLERS
    handler = COMMAND_HANDLERS.get(result.function_name)
    if handler:
        return handler()
    return f"❓ Perintah tidak dikenali: {result.original_message}"


def _get_trade_context() -> str:
    """Ambil summary paper trades untuk context Concierge."""
    from src.data.storage import PaperTrade, get_session
    with get_session() as db:
        open_trades = db.query(PaperTrade).filter(
            PaperTrade.status == 'OPEN'
        ).count()
        closed_trades = db.query(PaperTrade).filter(
            PaperTrade.status == 'CLOSED'
        ).all()
        total_pnl = sum(t.pnl or 0 for t in closed_trades)
        wins = sum(1 for t in closed_trades if (t.pnl or 0) > 0)
        wr = (wins / len(closed_trades) * 100) if closed_trades else 0

    return (
        f"Open trades: {open_trades}\n"
        f"Closed trades: {len(closed_trades)}\n"
        f"Win rate: {wr:.1f}%\n"
        f"Total PnL: ${total_pnl:.2f}"
    )


async def send_notification(text: str):
    """Kirim notifikasi ke Telegram. Panggil dari main loop."""
    from telegram import Bot
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())
    await bot.send_message(chat_id=settings.TELEGRAM_CHAT_ID, text=text)


def create_bot_app() -> Application:
    app = Application.builder().token(
        settings.TELEGRAM_BOT_TOKEN.get_secret_value()
    ).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app
```

---

### Task 5.3 — `src/telegram/commands.py`

```python
"""
commands.py — Handler untuk setiap command yang dikenali Commander.
"""
from src.data.storage import PaperTrade, get_session
from src.utils.logger import logger


def cmd_get_status() -> str:
    return "🤖 Bot status: RUNNING\nMode: PAPER TRADING"


def cmd_get_open_trades() -> str:
    with get_session() as db:
        trades = db.query(PaperTrade).filter(PaperTrade.status == 'OPEN').all()
    if not trades:
        return "📭 Tidak ada open trades saat ini."
    lines = ["📊 Open Trades:"]
    for t in trades:
        lines.append(f"• {t.pair} {t.side} | Entry: ${t.entry_price:,.2f} | SL: ${t.sl_price:,.2f} | TP: ${t.tp_price:,.2f}")
    return "\n".join(lines)


def cmd_get_performance() -> str:
    with get_session() as db:
        closed = db.query(PaperTrade).filter(PaperTrade.status == 'CLOSED').all()
    if not closed:
        return "📭 Belum ada closed trades."
    total_pnl = sum(t.pnl or 0 for t in closed)
    wins = sum(1 for t in closed if (t.pnl or 0) > 0)
    wr = wins / len(closed) * 100
    return (
        f"📈 Performance:\n"
        f"Total trades: {len(closed)}\n"
        f"Win rate: {wr:.1f}%\n"
        f"Total PnL: ${total_pnl:.2f}"
    )


def cmd_get_trade_history() -> str:
    with get_session() as db:
        trades = db.query(PaperTrade).filter(
            PaperTrade.status == 'CLOSED'
        ).order_by(PaperTrade.close_timestamp.desc()).limit(5).all()
    if not trades:
        return "📭 Belum ada history."
    lines = ["📜 Last 5 trades:"]
    for t in trades:
        emoji = "✅" if (t.pnl or 0) > 0 else "❌"
        lines.append(f"{emoji} {t.pair} {t.side} | PnL: ${t.pnl:.2f} | {t.close_reason}")
    return "\n".join(lines)


def cmd_unknown() -> str:
    return "❓ Perintah tidak dikenali. Coba: status, trades, history, performance"


# Registry — tambah fungsi baru di sini
COMMAND_HANDLERS = {
    'get_status': cmd_get_status,
    'get_open_trades': cmd_get_open_trades,
    'get_performance': cmd_get_performance,
    'get_trade_history': cmd_get_trade_history,
    'pause_trading': lambda: "⏸ Pause belum diimplementasi.",
    'resume_trading': lambda: "▶️ Resume belum diimplementasi.",
    'close_all_trades': lambda: "🔒 Close all belum diimplementasi.",
    'unknown': cmd_unknown,
}
```

---

### Task 5.4 — `src/main.py` (The Orchestrator)

```python
"""
main.py — Entry point dan orchestrator utama.
Loop 15 menit via APScheduler.
Telegram bot di thread terpisah.
"""
import asyncio
import threading
import os
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
        reversal     = ReversalAgent().run(df_h1)
        confirmation = ConfirmationAgent().run(df_15m, reversal)

        logger.info(f"Trend: {trend.bias_label} | Signal: {reversal.signal} | Confirmed: {confirmation.confirmed}")

        # ── 4. LLM Analyst ─────────────────────────────────────────────
        decision = run_analyst(trend, reversal, confirmation, current_price)
        logger.info(f"Analyst: {decision.action} (confidence: {decision.confidence}) [{decision.source}]")

        # ── 5. Risk & Execution ────────────────────────────────────────
        if decision.action in ('LONG', 'SHORT') and decision.confidence >= 60:
            if reversal.ob is not None:
                risk = RiskAgent().run(decision.action, reversal.ob, df_h1)
                result = ExecutionAgent().run(SYMBOL, decision.action, risk)

                if result.action == 'OPEN':
                    asyncio.run(send_notification(
                        f"🔔 Paper {decision.action}\n"
                        f"Entry: ${risk.entry_price:,.2f}\n"
                        f"SL: ${risk.sl_price:,.2f} | TP: ${risk.tp_price:,.2f}\n"
                        f"Risk: ${risk.risk_usd:.2f} | RR: 1:{settings.RISK_REWARD_RATIO}"
                    ))
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
        asyncio.run(send_notification(
            f"{emoji} {trade['reason']} Hit\n"
            f"{trade['pair']} {trade['side']}\n"
            f"PnL: ${trade['pnl']:.2f}"
        ))


def main():
    setup_logger()
    logger.info(f"Starting Futures Agent | Mode: {settings.EXECUTION_MODE.upper()}")

    # Init DB
    init_db()

    # Scheduler — jalankan di menit ke-00 setiap 15 menit
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

    # Telegram bot di thread terpisah
    def run_telegram():
        app = create_bot_app()
        app.run_polling(drop_pending_updates=True)

    telegram_thread = threading.Thread(target=run_telegram, daemon=True)
    telegram_thread.start()
    logger.info("Telegram bot started.")

    # Keep main thread alive
    try:
        while True:
            import time
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
```

---

### Task 5.5 — Stress Test (24 jam lokal)

Sebelum deploy ke VPS, jalankan:

```bash
# Jalankan bot
python3 src/main.py

# Di terminal lain, pantau RAM setiap 5 menit
watch -n 300 'ps aux | grep main.py | grep -v grep'
```

Pastikan:
- RAM tidak naik terus (memory leak)
- Tidak crash setelah beberapa cycle
- Telegram bot merespons perintah

---

## ✅ CHECKLIST PHASE 5

```bash
# Test imports
python3 -c "from src.telegram.bot import create_bot_app; print('✅ Bot OK')"
python3 -c "from src.telegram.commands import COMMAND_HANDLERS; print('✅ Commands OK')"
python3 -c "from src.main import run_trading_cycle; print('✅ Main OK')"

# Test run (Ctrl+C untuk stop)
python3 src/main.py
```

- [ ] `ohlcv_fetcher.py` — FETCH_LIMITS per timeframe
- [ ] `bot.py` — router command vs chat, send_notification
- [ ] `commands.py` — semua handler + COMMAND_HANDLERS registry
- [ ] `main.py` — scheduler 15 menit, telegram thread, SLTP check
- [ ] Semua import test PASS
- [ ] Bot jalan minimal 1 jam tanpa crash
- [ ] Telegram bot merespons `/status` atau pesan "status"

**Semua checklist hijau → commit → lanjut Phase 6 (VPS Deployment).**

---
*Phase 5 Master Prompt — Versi 1.0*

