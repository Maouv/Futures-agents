"""
commands.py — Handler untuk setiap command yang dikenali Commander.

PENTING: Semua akses PaperTrade attribute HARUS di dalam `with get_session() as db:`
karena SQLAlchemy object tidak bisa diakses setelah session ditutup (DetachedInstanceError).

DESAIN: Tidak ada manual close (/close, /closeall). Trade hanya ditutup oleh
SL/TP (Binance server-side di live mode, SLTPManager di paper mode).
Alasan: "Kalo dah masuk trade, bodo amat mau kena SL atau TP" — biar SL/TP natural.
"""
from datetime import datetime, timezone

from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.kill_switch import create_kill_switch, remove_kill_switch, check_kill_switch
from src.utils.logger import logger


def _get_current_mode() -> str:
    """Return current execution mode tag: 'paper', 'testnet', or 'mainnet'."""
    if settings.EXECUTION_MODE != "live":
        return "paper"
    return "testnet" if settings.USE_TESTNET else "mainnet"


def _cleanup_mode_trades(mode: str) -> int:
    """
    Tutup semua open/pending trades untuk mode tertentu.
    - Paper: cuma update DB (tidak ada order di exchange)
    - Testnet: cancel orders + close position di Binance testnet (uang palsu)
    - Mainnet: TIDAK diizinkan — harus manual close

    Returns jumlah trades yang ditutup.
    """
    closed_count = 0

    with get_session() as db:
        trades = db.query(PaperTrade).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
            PaperTrade.execution_mode == mode,
        ).all()

        if not trades:
            return 0

        if mode == 'mainnet':
            # JANGAN auto-close mainnet — uang asli
            return -1  # Signal bahwa ada trades tapi tidak bisa auto-close

        for trade in trades:
            if mode == 'testnet':
                # Cancel orders di Binance testnet
                try:
                    from src.utils.exchange import get_exchange, cancel_algo_order
                    exchange = get_exchange()
                    close_side = 'sell' if trade.side == 'LONG' else 'buy'

                    # Cancel SL, TP (algo orders — must use cancel_algo_order)
                    if trade.sl_order_id:
                        try:
                            cancel_algo_order(trade.sl_order_id, trade.pair)
                        except Exception:
                            pass
                    if trade.tp_order_id:
                        try:
                            cancel_algo_order(trade.tp_order_id, trade.pair)
                        except Exception:
                            pass
                    # Entry order is a regular limit order — use standard cancel
                    if trade.status == 'PENDING_ENTRY' and trade.exchange_order_id:
                        try:
                            exchange.cancel_order(trade.exchange_order_id, trade.pair)
                        except Exception:
                            pass

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
                            logger.warning(f"Failed to close position for trade {trade.id}: {e}")

                except Exception as e:
                    logger.error(f"Error during testnet cleanup for trade {trade.id}: {e}")

            # Update DB — baik paper maupun testnet
            trade.status = 'CLOSED'
            trade.close_reason = 'MODE_SWITCH'
            trade.close_timestamp = datetime.now(timezone.utc)
            closed_count += 1

    return closed_count


def cmd_menu() -> str:
    """Tampilkan menu + ringkasan cepat (filtered by current mode)."""
    kill_status = "ON" if check_kill_switch() else "OFF"
    mode = "paper" if settings.EXECUTION_MODE != "live" else ("testnet" if settings.USE_TESTNET else "mainnet")
    with get_session() as db:
        open_count = db.query(PaperTrade).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
            PaperTrade.execution_mode == mode,
        ).count()
        closed = db.query(PaperTrade).filter(
            PaperTrade.status == 'CLOSED',
            PaperTrade.execution_mode == mode,
        ).all()
        total_pnl = sum(t.pnl or 0 for t in closed)

    return (
        f"== MENU [{mode.upper()}] ==\n"
        f"Open: {open_count} | PnL: ${total_pnl:.2f} | Kill: {kill_status}\n"
        f"\n"
        f"/status  — Mode, leverage, kill switch\n"
        f"/trades  — Open trades (mode aktif)\n"
        f"/history [paper|testnet|mainnet]\n"
        f"/perf [paper|testnet|mainnet]\n"
        f"/mode paper|testnet|mainnet — Switch\n"
        f"/kill   — Stop buka trade baru\n"
        f"/resume — Boleh buka trade lagi"
    )


def cmd_get_status() -> str:
    mode = settings.EXECUTION_MODE.upper()
    testnet = "TESTNET" if settings.USE_TESTNET else "MAINNET"
    kill = "ON" if check_kill_switch() else "OFF"

    if settings.EXECUTION_MODE == "live":
        return (
            f"Bot: RUNNING\n"
            f"Mode: LIVE ({testnet})\n"
            f"Kill switch: {kill}\n"
            f"Leverage: {settings.FUTURES_DEFAULT_LEVERAGE}x\n"
            f"Max positions/pair: {settings.MAX_OPEN_POSITIONS}"
        )
    return (
        f"Bot: RUNNING\n"
        f"Mode: PAPER\n"
        f"Kill switch: {kill}\n"
        f"Max positions/pair: {settings.MAX_OPEN_POSITIONS}"
    )


def cmd_get_open_trades() -> str:
    """Open trades, filtered by current execution mode."""
    if settings.EXECUTION_MODE != "live":
        mode = "paper"
    else:
        mode = "testnet" if settings.USE_TESTNET else "mainnet"
    mode_label = mode.upper()

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
            lines.append(
                f"  ID:{t.id} | {t.pair} {t.side}{status_tag} | "
                f"Entry: ${t.entry_price:,.2f} | SL: ${t.sl_price:,.2f} | TP: ${t.tp_price:,.2f}"
            )
    return "\n".join(lines)


def cmd_get_performance(mode: str = "") -> str:
    """Performance stats. /perf = current mode, /perf paper, /perf testnet, /perf mainnet"""
    if mode == "":
        # Default ke mode aktif saat ini
        if settings.EXECUTION_MODE != "live":
            mode = "paper"
        else:
            mode = "testnet" if settings.USE_TESTNET else "mainnet"
    elif mode not in ('paper', 'testnet', 'mainnet'):
        return "Gunakan: /perf [paper|testnet|mainnet]"

    mode_label = mode.upper()
    with get_session() as db:
        query = db.query(PaperTrade).filter(PaperTrade.status == 'CLOSED')
        query = query.filter(PaperTrade.execution_mode == mode)

        closed = query.all()
        if not closed:
            return f"Belum ada closed trades [{mode_label}]."
        total_pnl = sum(t.pnl or 0 for t in closed)
        wins = sum(1 for t in closed if (t.pnl or 0) > 0)
        wr = wins / len(closed) * 100
    return (
        f"Performance [{mode_label}]:\n"
        f"Total trades: {len(closed)}\n"
        f"Win rate: {wr:.1f}%\n"
        f"Total PnL: ${total_pnl:.2f}"
    )


def cmd_get_trade_history(mode: str = "") -> str:
    """Trade history. /history = current mode, /history paper, /history testnet, /history mainnet"""
    if mode == "":
        if settings.EXECUTION_MODE != "live":
            mode = "paper"
        else:
            mode = "testnet" if settings.USE_TESTNET else "mainnet"
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
    current_mode = _get_current_mode()

    if mode == "paper":
        if current_mode == "mainnet":
            # Cek apakah ada open mainnet trades
            closed = _cleanup_mode_trades("mainnet")
            if closed == -1:
                return (
                    "DITOLAK: Masih ada open trades di MAINNET. "
                    "Tutup manual via Binance dulu — posisi uang asli tidak bisa di-auto-close."
                )

        closed = _cleanup_mode_trades(current_mode) if current_mode != "paper" else 0
        settings.EXECUTION_MODE = "paper"
        settings.USE_TESTNET = False
        reset_exchange()
        msg = "Mode: PAPER (simulasi lokal). Restart kembali ke .env."
        if closed > 0:
            msg = f"Mode: PAPER. {closed} trade(s) di {current_mode.upper()} ditutup (MODE_SWITCH). Restart kembali ke .env."
        return msg

    elif mode == "testnet":
        if current_mode == "mainnet":
            closed = _cleanup_mode_trades("mainnet")
            if closed == -1:
                return (
                    "DITOLAK: Masih ada open trades di MAINNET. "
                    "Tutup manual via Binance dulu — posisi uang asli tidak bisa di-auto-close."
                )

        closed = _cleanup_mode_trades(current_mode) if current_mode not in ("testnet", "paper") else 0
        settings.EXECUTION_MODE = "live"
        settings.USE_TESTNET = True
        reset_exchange()
        msg = "Mode: TESTNET (Binance Futures Testnet). Restart kembali ke .env."
        if closed > 0:
            msg = f"Mode: TESTNET. {closed} trade(s) di {current_mode.upper()} ditutup (MODE_SWITCH). Restart kembali ke .env."
        return msg

    elif mode == "mainnet":
        if not settings.CONFIRM_MAINNET:
            return "DITOLAK: CONFIRM_MAINNET=False. Set CONFIRM_MAINNET=True di .env dulu."

        closed = _cleanup_mode_trades(current_mode) if current_mode != "mainnet" else 0
        if closed == -1:
            return (
                "DITOLAK: Masih ada open trades di MAINNET. "
                "Tutup manual via Binance dulu — posisi uang asli tidak bisa di-auto-close."
            )

        settings.EXECUTION_MODE = "live"
        settings.USE_TESTNET = False
        reset_exchange()
        msg = "Mode: MAINNET (Binance Futures Production — UANG ASLI). Restart kembali ke .env."
        if closed > 0:
            msg = f"Mode: MAINNET. {closed} trade(s) di {current_mode.upper()} ditutup (MODE_SWITCH). Restart kembali ke .env."
        return msg

    else:
        current = _get_current_mode().upper()
        return (
            f"Mode saat ini: {current}\n"
            f"Gunakan:\n"
            f"  /mode paper — simulasi lokal\n"
            f"  /mode testnet — Binance Testnet\n"
            f"  /mode mainnet — Binance Production"
        )


def cmd_unknown() -> str:
    return "Perintah tidak dikenali. Ketik /menu"


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
