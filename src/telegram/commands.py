"""
commands.py — Handler untuk setiap command yang dikenali Commander.

PENTING: Semua akses PaperTrade attribute HARUS di dalam `with get_session() as db:`
karena SQLAlchemy object tidak bisa diakses setelah session ditutup (DetachedInstanceError).

DESAIN: Tidak ada manual close (/close, /closeall). Trade hanya ditutup oleh
SL/TP (Binance server-side di live mode, SLTPManager di paper mode).
Alasan: "Kalo dah masuk trade, bodo amat mau kena SL atau TP" — biar SL/TP natural.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.kill_switch import check_kill_switch, create_kill_switch, remove_kill_switch
from src.utils.logger import logger
from src.utils.mode import get_current_mode, get_mode_label
from src.utils.trade_utils import close_trade

# ── Cleanup Result ──────────────────────────────────────────────────────────

@dataclass
class CleanupResult:
    """Result dari mode cleanup — tracks closed trades and cancel errors."""
    closed_count: int = 0
    cancel_errors: list[str] = field(default_factory=list)
    blocked: bool = False


def _cleanup_warning(result: 'CleanupResult') -> str:
    """Build warning string jika ada cancel errors (untuk Telegram message)."""
    if not result.cancel_errors:
        return ""
    errors_preview = "\n".join(f"  • {e}" for e in result.cancel_errors[:5])
    extra = f"\n  ... dan {len(result.cancel_errors) - 5} lainnya" if len(result.cancel_errors) > 5 else ""
    return (
        f"\n\n⚠️ {len(result.cancel_errors)} cancel error(s) — "
        f"orphaned orders mungkin masih aktif di exchange:\n"
        f"{errors_preview}{extra}\n"
        f"Cek manual di Binance dashboard!"
    )


def _cleanup_mode_trades(mode: str) -> CleanupResult:
    """
    Tutup semua open/pending trades untuk mode tertentu.
    - Paper: cuma update DB (tidak ada order di exchange)
    - Testnet: cancel orders + close position di Binance testnet (uang palsu)
    - Mainnet: TIDAK diizinkan — harus manual close

    Returns CleanupResult dengan closed_count, cancel_errors, dan blocked flag.
    """
    result = CleanupResult()

    with get_session() as db:
        trades = db.query(PaperTrade).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
            PaperTrade.execution_mode == mode,
        ).all()

        if not trades:
            return result

        if mode == 'mainnet':
            # JANGAN auto-close mainnet — uang asli
            result.blocked = True
            return result

        for trade in trades:
            if mode == 'testnet':
                # Cancel orders di Binance testnet
                try:
                    from src.utils.exchange import cancel_algo_order, get_exchange
                    exchange = get_exchange()
                    close_side = 'sell' if trade.side == 'LONG' else 'buy'

                    # Cancel SL, TP (algo orders — must use cancel_algo_order)
                    if trade.sl_order_id:
                        try:
                            cancel_algo_order(trade.sl_order_id, trade.pair)
                        except Exception as e:
                            err = f"SL cancel failed: trade {trade.id}, order {trade.sl_order_id}, {trade.pair}: {e}"
                            logger.error(err)
                            result.cancel_errors.append(err)

                    if trade.tp_order_id:
                        try:
                            cancel_algo_order(trade.tp_order_id, trade.pair)
                        except Exception as e:
                            err = f"TP cancel failed: trade {trade.id}, order {trade.tp_order_id}, {trade.pair}: {e}"
                            logger.error(err)
                            result.cancel_errors.append(err)

                    # Entry order is a regular limit order — use standard cancel
                    if trade.status == 'PENDING_ENTRY' and trade.exchange_order_id:
                        try:
                            exchange.cancel_order(trade.exchange_order_id, trade.pair)
                        except Exception as e:
                            err = f"Entry cancel failed: trade {trade.id}, order {trade.exchange_order_id}, {trade.pair}: {e}"
                            logger.error(err)
                            result.cancel_errors.append(err)

                    # Close position jika OPEN (ada posisi aktif)
                    if trade.status == 'OPEN':
                        try:
                            amount = exchange.amount_to_precision(trade.pair, trade.size)
                            exchange.create_order(
                                symbol=trade.pair,
                                type='market',
                                side=close_side,
                                amount=float(amount),
                                params={'reduceOnly': True}
                            )
                        except Exception as e:
                            err = f"Position close failed: trade {trade.id}, {trade.pair}: {e}"
                            logger.error(err)
                            result.cancel_errors.append(err)

                except Exception as e:
                    err = f"Testnet cleanup error for trade {trade.id}: {e}"
                    logger.error(err)
                    result.cancel_errors.append(err)

            # Update DB — baik paper maupun testnet
            close_trade(trade, 'MODE_SWITCH')
            result.closed_count += 1

    return result


def _get_mode_stats(mode: str) -> dict:
    """Get open count, closed count, total_pnl, win_rate for a mode (SQL aggregation)."""
    from sqlalchemy import func

    with get_session() as db:
        open_count = db.query(func.count(PaperTrade.id)).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
            PaperTrade.execution_mode == mode,
        ).scalar() or 0

        closed_count = db.query(func.count(PaperTrade.id)).filter(
            PaperTrade.status == 'CLOSED',
            PaperTrade.execution_mode == mode,
        ).scalar() or 0

        total_pnl = db.query(func.sum(PaperTrade.pnl)).filter(
            PaperTrade.status == 'CLOSED',
            PaperTrade.execution_mode == mode,
        ).scalar() or 0

        wins = db.query(func.count(PaperTrade.id)).filter(
            PaperTrade.status == 'CLOSED',
            PaperTrade.execution_mode == mode,
            PaperTrade.pnl > 0,
        ).scalar() or 0

        win_rate = (wins / closed_count * 100) if closed_count else 0

        return {
            'open_count': open_count,
            'closed_count': closed_count,
            'total_pnl': total_pnl,
            'win_rate': win_rate,
        }


def cmd_menu() -> str:
    """Tampilkan menu + ringkasan cepat (filtered by current mode)."""
    kill_status = "ON" if check_kill_switch() else "OFF"
    mode = get_current_mode()
    stats = _get_mode_stats(mode)

    return (
        f"== MENU [{mode.upper()}] ==\n"
        f"Open: {stats['open_count']} | PnL: ${stats['total_pnl']:.2f} | Kill: {kill_status}\n"
        f"\n"
        f"/status  — Mode, leverage, kill switch\n"
        f"/trades  — Open trades (mode aktif)\n"
        f"/stats   — Stats per mode (net PnL, fee, win rate)\n"
        f"/trade <id> — Detail satu trade\n"
        f"/history [paper|testnet|mainnet]\n"
        f"/perf [paper|testnet|mainnet]\n"
        f"/mode paper|testnet|mainnet — Switch\n"
        f"/kill   — Stop buka trade baru\n"
        f"/resume — Boleh buka trade lagi"
    )


def cmd_get_status() -> str:
    kill = "ON" if check_kill_switch() else "OFF"
    trailing = "ON" if settings.TRAILING_STOP_ENABLED else "OFF"

    if settings.EXECUTION_MODE == "live":
        return (
            f"Bot: RUNNING\n"
            f"Mode: LIVE ({get_mode_label()})\n"
            f"Kill switch: {kill}\n"
            f"Leverage: {settings.FUTURES_DEFAULT_LEVERAGE}x\n"
            f"Max positions/pair: {settings.MAX_OPEN_POSITIONS}\n"
            f"Trailing stop: {trailing}"
        )
    return (
        f"Bot: RUNNING\n"
        f"Mode: PAPER\n"
        f"Kill switch: {kill}\n"
        f"Max positions/pair: {settings.MAX_OPEN_POSITIONS}\n"
        f"Trailing stop: {trailing}"
    )


def cmd_get_open_trades() -> str:
    """Open trades, filtered by current execution mode."""
    mode = get_current_mode()
    mode_label = get_mode_label()

    with get_session() as db:
        trades = db.query(PaperTrade).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
            PaperTrade.execution_mode == mode,
        ).all()
        if not trades:
            return f"Tidak ada open trades [{mode_label}]."
        lines = [f"Open Trades [{mode_label}]:"]
        for t in trades:
            status_tag = " [PENDING]" if t.status == 'PENDING_ENTRY' else ""
            liq_tag = f" | Liq: ${t.liq_price:,.2f}" if t.liq_price else ""
            step_tag = f" | Step: {t.trailing_step}" if t.trailing_step > 0 else ""
            lines.append(
                f"  ID:{t.id} | {t.pair} {t.side}{status_tag} | "
                f"Entry: ${t.entry_price:,.2f} | SL: ${t.sl_price:,.2f} | TP: ${t.tp_price:,.2f}"
                f"{liq_tag}{step_tag}"
            )
    return "\n".join(lines)


def cmd_get_performance(mode: str = "") -> str:
    """Performance stats. /perf = current mode, /perf paper, /perf testnet, /perf mainnet"""
    if mode == "":
        mode = get_current_mode()
    elif mode not in ('paper', 'testnet', 'mainnet'):
        return "Gunakan: /perf [paper|testnet|mainnet]"

    mode_label = mode.upper()
    stats = _get_mode_stats(mode)

    if stats['closed_count'] == 0:
        return f"Belum ada closed trades [{mode_label}]."

    return (
        f"Performance [{mode_label}]:\n"
        f"Total trades: {stats['closed_count']}\n"
        f"Win rate: {stats['win_rate']:.1f}%\n"
        f"Total PnL: ${stats['total_pnl']:.2f}"
    )


def cmd_get_trade_history(mode: str = "") -> str:
    """Trade history. /history = current mode, /history paper, /history testnet, /history mainnet"""
    if mode == "":
        mode = get_current_mode()
    elif mode not in ('paper', 'testnet', 'mainnet'):
        return "Gunakan: /history [paper|testnet|mainnet]"

    mode_label = mode.upper()
    with get_session() as db:
        query = db.query(PaperTrade).filter(PaperTrade.status == 'CLOSED')
        query = query.filter(PaperTrade.execution_mode == mode)

        trades = query.order_by(PaperTrade.close_timestamp.desc()).limit(5).all()
        if not trades:
            return f"Belum ada history [{mode_label}]."
        lines = [f"Last 5 trades [{mode_label}]:"]
        for t in trades:
            emoji = "+" if (t.pnl or 0) > 0 else "-"
            close_p = f" | Close: ${t.close_price:,.2f}" if t.close_price else ""
            lines.append(
                f"{emoji} ID:{t.id} | {t.pair} {t.side} | PnL: ${t.pnl:.2f} | {t.close_reason}{close_p}"
            )
    return "\n".join(lines)


def cmd_kill() -> str:
    """Aktifkan kill switch — bot tidak buka trade baru."""
    create_kill_switch()
    return "KILL SWITCH ON — tidak ada trade baru."


def cmd_resume() -> str:
    """Nonaktifkan kill switch — bot bisa buka trade lagi."""
    remove_kill_switch()
    return "Kill switch OFF — bot bisa buka trade lagi."


def cmd_switch_mode(mode: str = "") -> str:
    """Switch antara paper, testnet, mainnet (runtime only).

    Mode switch akan:
    1. Cek open trades di mode saat ini
    2. Auto-close trades di paper/testnet (tidak ada risiko uang)
    3. Block switch dari mainnet jika masih ada open trades
    4. Reset exchange instance agar API call menggunakan credentials yang benar

    NOTE: WebSocket stream TIDAK di-restart secara otomatis —
    butuh restart bot untuk menerapkan perubahan WS.
    """
    from src.utils.exchange import reset_exchange
    mode = mode.strip().lower()
    current_mode = get_current_mode()

    if mode == "paper":
        if current_mode == "mainnet":
            # Cek apakah ada open mainnet trades
            result = _cleanup_mode_trades("mainnet")
            if result.blocked:
                return (
                    "DITOLAK: Masih ada open trades di MAINNET. "
                    "Tutup manual via Binance dulu — posisi uang asli tidak bisa di-auto-close."
                )

        result = _cleanup_mode_trades(current_mode) if current_mode != "paper" else CleanupResult()
        settings.EXECUTION_MODE = "paper"
        settings.USE_TESTNET = False
        reset_exchange()
        msg = "Mode: PAPER (simulasi lokal). Restart kembali ke .env."
        if result.closed_count > 0:
            msg = f"Mode: PAPER. {result.closed_count} trade(s) di {current_mode.upper()} ditutup (MODE_SWITCH). Restart kembali ke .env."
        return msg + _cleanup_warning(result)

    elif mode == "testnet":
        if current_mode == "mainnet":
            result = _cleanup_mode_trades("mainnet")
            if result.blocked:
                return (
                    "DITOLAK: Masih ada open trades di MAINNET. "
                    "Tutup manual via Binance dulu — posisi uang asli tidak bisa di-auto-close."
                )

        result = _cleanup_mode_trades(current_mode) if current_mode not in ("testnet", "paper") else CleanupResult()
        settings.EXECUTION_MODE = "live"
        settings.USE_TESTNET = True
        reset_exchange()
        msg = "Mode: TESTNET (Binance Futures Testnet). Restart kembali ke .env."
        if result.closed_count > 0:
            msg = f"Mode: TESTNET. {result.closed_count} trade(s) di {current_mode.upper()} ditutup (MODE_SWITCH). Restart kembali ke .env."
        return msg + _cleanup_warning(result)

    elif mode == "mainnet":
        if not settings.CONFIRM_MAINNET:
            return "DITOLAK: CONFIRM_MAINNET=False. Set CONFIRM_MAINNET=True di .env dulu."

        result = _cleanup_mode_trades(current_mode) if current_mode != "mainnet" else CleanupResult()
        if result.blocked:
            return (
                "DITOLAK: Masih ada open trades di MAINNET. "
                "Tutup manual via Binance dulu — posisi uang asli tidak bisa di-auto-close."
            )

        settings.EXECUTION_MODE = "live"
        settings.USE_TESTNET = False
        reset_exchange()
        msg = "Mode: MAINNET (Binance Futures Production — UANG ASLI). Restart kembali ke .env."
        if result.closed_count > 0:
            msg = f"Mode: MAINNET. {result.closed_count} trade(s) di {current_mode.upper()} ditutup (MODE_SWITCH). Restart kembali ke .env."
        return msg + _cleanup_warning(result)

    else:
        current = get_current_mode().upper()
        return (
            f"Mode saat ini: {current}\n"
            f"Gunakan:\n"
            f"  /mode paper — simulasi lokal\n"
            f"  /mode testnet — Binance Testnet\n"
            f"  /mode mainnet — Binance Production"
        )


def cmd_unknown() -> str:
    return "Perintah tidak dikenali. Ketik /menu"


def _build_stats_for_mode(mode: str, days: int = 30) -> str:
    """Build stats string untuk satu mode."""
    from datetime import timedelta
    from sqlalchemy import func

    since = datetime.now(UTC) - timedelta(days=days)
    mode_emoji = {"paper": "📄", "testnet": "🟡", "mainnet": "🟢"}.get(mode, "❓")
    mode_label = mode.upper()

    with get_session() as db:
        closed = db.query(PaperTrade).filter(
            PaperTrade.execution_mode == mode,
            PaperTrade.status == 'CLOSED',
            PaperTrade.entry_timestamp >= since,
        ).all()

        open_count = db.query(PaperTrade).filter(
            PaperTrade.execution_mode == mode,
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
        ).count()

    if not closed:
        return f"{mode_emoji} {mode_label}\nNo closed trades in last {days} days.\n"

    wins = [t for t in closed if (t.net_pnl if t.net_pnl is not None else t.pnl or 0) > 0]
    losses = [t for t in closed if (t.net_pnl if t.net_pnl is not None else t.pnl or 0) <= 0]
    win_rate = len(wins) / len(closed) * 100

    gross_pnl = sum(t.pnl or 0 for t in closed)
    total_fee = sum((t.fee_open or 0) + (t.fee_close or 0) for t in closed)
    net_pnl = sum(t.net_pnl if t.net_pnl is not None else (t.pnl or 0) for t in closed)
    avg_net = net_pnl / len(closed)

    sorted_trades = sorted(closed, key=lambda t: t.net_pnl if t.net_pnl is not None else (t.pnl or 0))
    worst = sorted_trades[0]
    best = sorted_trades[-1]

    paper_note = " (simulated)" if mode == "paper" else ""

    lines = [
        f"{mode_emoji} {mode_label} — Last {days} days",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Closed trades : {len(closed)}",
        f"Win / Loss    : {len(wins)}W / {len(losses)}L",
        f"Win Rate      : {win_rate:.1f}%",
    ]

    if mode != "paper":
        lines += [
            f"Gross PnL     : ${gross_pnl:+.2f}",
            f"Total Fees    : -${total_fee:.4f}",
        ]

    lines += [
        f"Net PnL       : ${net_pnl:+.2f}{paper_note}",
        f"Avg net/trade : ${avg_net:+.2f}",
        f"Best trade    : ${(best.net_pnl if best.net_pnl is not None else best.pnl or 0):+.2f} ({best.pair})",
        f"Worst trade   : ${(worst.net_pnl if worst.net_pnl is not None else worst.pnl or 0):+.2f} ({worst.pair})",
    ]

    if open_count > 0:
        lines.append(f"\nOpen trades   : {open_count}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def cmd_stats(days: int = 30) -> str:
    """Full stats per mode, current mode first."""
    current_mode = get_current_mode()
    msg = "📊 Trading Statistics\n\n"
    msg += _build_stats_for_mode(current_mode, days)
    msg += "\n"
    for mode in ["testnet", "paper", "mainnet"]:
        if mode != current_mode:
            section = _build_stats_for_mode(mode, days)
            if "No closed trades" not in section:
                msg += section + "\n"
    return msg


def cmd_trade_detail(trade_id_str: str) -> str:
    """Detail satu trade by ID."""
    if not trade_id_str.isdigit():
        return "Usage: /trade <id>"

    trade_id = int(trade_id_str)

    with get_session() as db:
        trade = db.query(PaperTrade).get(trade_id)
        if not trade:
            return f"Trade #{trade_id} tidak ditemukan."

        mode_emoji = {"paper": "📄", "testnet": "🟡", "mainnet": "🟢"}.get(
            trade.execution_mode or "paper", "❓"
        )

        duration = ""
        if trade.close_timestamp and trade.entry_timestamp:
            delta = trade.close_timestamp - trade.entry_timestamp
            hours = int(delta.total_seconds() // 3600)
            minutes = int((delta.total_seconds() % 3600) // 60)
            duration = f"~{hours}h {minutes}m"

        fee_open = trade.fee_open or 0
        fee_close = trade.fee_close or 0
        net_pnl = trade.net_pnl if trade.net_pnl is not None else (trade.pnl or 0)
        gross_pnl = trade.pnl or 0

        msg = (
            f"🔍 Trade Detail #{trade.id}\n\n"
            f"Pair    : {trade.pair}\n"
            f"Side    : {trade.side}\n"
            f"Mode    : {mode_emoji} {(trade.execution_mode or 'unknown').upper()}\n"
            f"Status  : {trade.status}"
            f"{' (' + trade.close_reason + ')' if trade.close_reason else ''}\n\n"
        )

        if trade.actual_entry_price:
            slip = trade.slippage_entry
            slip_str = f"+${slip:.4f}" if slip and slip >= 0 else (f"${slip:.4f}" if slip else "N/A")
            msg += (
                f"Entry\n"
                f"  Planned : ${trade.entry_price:,.4f}\n"
                f"  Actual  : ${trade.actual_entry_price:,.4f}\n"
                f"  Slippage: {slip_str}\n\n"
            )

        if trade.actual_close_price:
            planned_close = trade.sl_price if trade.close_reason == 'SL' else trade.tp_price
            slip_c = trade.slippage_close
            slip_c_str = f"+${slip_c:.4f}" if slip_c and slip_c >= 0 else (f"${slip_c:.4f}" if slip_c else "N/A")
            msg += (
                f"Exit\n"
                f"  Planned : ${planned_close:,.4f} ({trade.close_reason})\n"
                f"  Actual  : ${trade.actual_close_price:,.4f}\n"
                f"  Slippage: {slip_c_str}\n\n"
            )

        msg += (
            f"P&L\n"
            f"  Gross    : ${gross_pnl:+.2f}\n"
            f"  Fee open : -${fee_open:.4f}\n"
            f"  Fee close: -${fee_close:.4f}\n"
            f"  Net PnL  : ${net_pnl:+.2f}\n\n"
            f"Opened  : {trade.entry_timestamp.strftime('%Y-%m-%d %H:%M UTC') if trade.entry_timestamp else 'N/A'}\n"
        )

        if trade.close_timestamp:
            msg += f"Closed  : {trade.close_timestamp.strftime('%Y-%m-%d %H:%M UTC')}\n"
        if duration:
            msg += f"Duration: {duration}\n"

        return msg


# Registry
COMMAND_HANDLERS = {
    'get_status': cmd_get_status,
    'get_open_trades': cmd_get_open_trades,
    'get_performance': cmd_get_performance,
    'get_trade_history': cmd_get_trade_history,
    'activate_kill_switch': cmd_kill,
    'deactivate_kill_switch': cmd_resume,
    'show_menu': cmd_menu,
    'switch_mode': cmd_switch_mode,
    'unknown': cmd_unknown,
}
