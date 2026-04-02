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
