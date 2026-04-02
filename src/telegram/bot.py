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
