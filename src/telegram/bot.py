"""
bot.py — Telegram bot interface.
Router: pesan command → CommanderAgent, pesan chat → ConciergeAgent.
"""
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
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
    """Ambil summary trades untuk context Concierge, dipisah per mode."""
    from src.data.storage import PaperTrade, get_session
    with get_session() as db:
        # Paper mode stats
        paper_open = db.query(PaperTrade).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
            PaperTrade.execution_mode == 'paper',
        ).count()
        paper_closed = db.query(PaperTrade).filter(
            PaperTrade.status == 'CLOSED',
            PaperTrade.execution_mode == 'paper',
        ).all()
        paper_pnl = sum(t.pnl or 0 for t in paper_closed)
        paper_wins = sum(1 for t in paper_closed if (t.pnl or 0) > 0)
        paper_wr = (paper_wins / len(paper_closed) * 100) if paper_closed else 0

        # Live mode stats
        live_open = db.query(PaperTrade).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
            PaperTrade.execution_mode == 'live',
        ).count()
        live_closed = db.query(PaperTrade).filter(
            PaperTrade.status == 'CLOSED',
            PaperTrade.execution_mode == 'live',
        ).all()
        live_pnl = sum(t.pnl or 0 for t in live_closed)
        live_wins = sum(1 for t in live_closed if (t.pnl or 0) > 0)
        live_wr = (live_wins / len(live_closed) * 100) if live_closed else 0

    return (
        f"[PAPER] Open: {paper_open} | Closed: {len(paper_closed)} | WR: {paper_wr:.1f}% | PnL: ${paper_pnl:.2f}\n"
        f"[LIVE]  Open: {live_open} | Closed: {len(live_closed)} | WR: {live_wr:.1f}% | PnL: ${live_pnl:.2f}"
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

    # Slash commands
    app.add_handler(CommandHandler("start", _cmd_menu_handler))
    app.add_handler(CommandHandler("menu", _cmd_menu_handler))
    app.add_handler(CommandHandler("status", _cmd_status_handler))
    app.add_handler(CommandHandler("trades", _cmd_trades_handler))
    app.add_handler(CommandHandler("perf", _cmd_perf_handler))
    app.add_handler(CommandHandler("history", _cmd_history_handler))
    app.add_handler(CommandHandler("close", _cmd_close_handler))
    app.add_handler(CommandHandler("closeall", _cmd_closeall_handler))
    app.add_handler(CommandHandler("kill", _cmd_kill_handler))
    app.add_handler(CommandHandler("resume", _cmd_resume_handler))
    app.add_handler(CommandHandler("mode", _cmd_mode_handler))

    # Natural language messages (via Commander/Concierge)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


async def _cmd_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_menu
    await update.message.reply_text(cmd_menu())

async def _cmd_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_get_status
    await update.message.reply_text(cmd_get_status())

async def _cmd_trades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_get_open_trades
    await update.message.reply_text(cmd_get_open_trades())

async def _cmd_perf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_get_performance
    mode = context.args[0] if context.args else ""
    await update.message.reply_text(cmd_get_performance(mode))

async def _cmd_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_get_trade_history
    mode = context.args[0] if context.args else ""
    await update.message.reply_text(cmd_get_trade_history(mode))

async def _cmd_kill_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_kill
    await update.message.reply_text(cmd_kill())

async def _cmd_resume_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_resume
    await update.message.reply_text(cmd_resume())

async def _cmd_close_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_close_trade
    # /close 5 → context.args = ['5']
    trade_id = context.args[0] if context.args else None
    if trade_id is None:
        await update.message.reply_text("Gunakan: /close <trade_id>\nLihat /trades untuk daftar ID.")
        return
    await update.message.reply_text(cmd_close_trade(trade_id))

async def _cmd_closeall_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_close_all_trades
    await update.message.reply_text(cmd_close_all_trades())

async def _cmd_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.telegram.commands import cmd_switch_mode
    mode = context.args[0] if context.args else ""
    await update.message.reply_text(cmd_switch_mode(mode))
