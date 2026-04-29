"""
bot.py — Telegram bot interface.
Router: pesan command → CommanderAgent, pesan chat → ConciergeAgent.
"""
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.agents.llm.commander_agent import run_commander
from src.agents.llm.concierge_agent import run_concierge
from src.config.settings import settings
from src.utils.logger import logger
from telegram import Update


# Ini dap
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route pesan ke Commander atau Concierge."""
    if not update.message or not update.effective_chat:
      return
    message = update.message.text
    if not message:
      return
    chat_id = str(update.effective_chat.id)

    # Hanya proses dari chat ID yang diizinkan
    if chat_id != settings.TELEGRAM_CHAT_ID:
        return

    logger.info(f"[Telegram] Message: {message[:50]}")

    # Deteksi command vs chat
    is_command = message.startswith('/') or any(
        kw in message.lower()
        for kw in ['status', 'trades', 'history', 'performance', 'kill', 'resume', 'mode', 'menu']
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
        # Hanya pass 'mode' param yang dikenali oleh get_performance dan get_trade_history
        mode = result.params.get('mode', '')
        if mode:
            return handler(mode)  # type: ignore[call-arg]
        return handler()
    return f"❓ Perintah tidak dikenali: {result.original_message}"


def _get_trade_context() -> str:
    """Ambil summary trades untuk context Concierge, dipisah per mode."""
    from sqlalchemy import func

    from src.data.storage import PaperTrade, get_session
    from src.telegram.commands import _get_mode_stats

    paper = _get_mode_stats('paper')

    # Live = testnet + mainnet (aggregate)
    with get_session() as db:
        live_open = db.query(func.count(PaperTrade.id)).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
            PaperTrade.execution_mode.in_(['testnet', 'mainnet']),
        ).scalar() or 0
        live_closed_count = db.query(func.count(PaperTrade.id)).filter(
            PaperTrade.status == 'CLOSED',
            PaperTrade.execution_mode.in_(['testnet', 'mainnet']),
        ).scalar() or 0
        live_pnl = db.query(func.sum(PaperTrade.pnl)).filter(
            PaperTrade.status == 'CLOSED',
            PaperTrade.execution_mode.in_(['testnet', 'mainnet']),
        ).scalar() or 0
        live_wins = db.query(func.count(PaperTrade.id)).filter(
            PaperTrade.status == 'CLOSED',
            PaperTrade.execution_mode.in_(['testnet', 'mainnet']),
            PaperTrade.pnl > 0,
        ).scalar() or 0
        live_wr = (live_wins / live_closed_count * 100) if live_closed_count else 0

    return (
        f"[PAPER] Open: {paper['open_count']} | Closed: {paper['closed_count']} | WR: {paper['win_rate']:.1f}% | PnL: ${paper['total_pnl']:.2f}\n"
        f"[LIVE]  Open: {live_open} | Closed: {live_closed_count} | WR: {live_wr:.1f}% | PnL: ${live_pnl:.2f}"
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
    app.add_handler(CommandHandler("kill", _cmd_kill_handler))
    app.add_handler(CommandHandler("resume", _cmd_resume_handler))
    app.add_handler(CommandHandler("mode", _cmd_mode_handler))
    app.add_handler(CommandHandler("stats", _cmd_stats_handler))
    app.add_handler(CommandHandler("trade", _cmd_trade_detail_handler))

    # Natural language messages (via Commander/Concierge)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


async def _cmd_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_menu
    if not update.message:
      return
    await update.message.reply_text(cmd_menu())

async def _cmd_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_get_status
    if not update.message:
      return
    await update.message.reply_text(cmd_get_status())

async def _cmd_trades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_get_open_trades
    if not update.message:
      return
    await update.message.reply_text(cmd_get_open_trades())

async def _cmd_perf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_get_performance
    if not update.message:
      return
    mode = context.args[0] if context.args else ""
    await update.message.reply_text(cmd_get_performance(mode))

async def _cmd_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_get_trade_history
    if not update.message:
      return
    mode = context.args[0] if context.args else ""
    await update.message.reply_text(cmd_get_trade_history(mode))

async def _cmd_kill_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_kill
    if not update.message:
      return
    await update.message.reply_text(cmd_kill())

async def _cmd_resume_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_resume
    if not update.message:
      return
    await update.message.reply_text(cmd_resume())

async def _cmd_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_switch_mode
    if not update.message:
      return
    mode = context.args[0] if context.args else ""
    await update.message.reply_text(cmd_switch_mode(mode))

async def _cmd_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_stats
    if not update.message:
        return
    await update.message.reply_text(cmd_stats())

async def _cmd_trade_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.telegram.commands import cmd_trade_detail
    if not update.message:
        return
    trade_id = context.args[0] if context.args else ""
    await update.message.reply_text(cmd_trade_detail(trade_id))
