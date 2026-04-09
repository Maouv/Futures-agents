"""
commands.py — Handler untuk setiap command yang dikenali Commander.

PENTING: Semua akses PaperTrade attribute HARUS di dalam `with get_session() as db:`
karena SQLAlchemy object tidak bisa diakses setelah session ditutup (DetachedInstanceError).
"""
from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.kill_switch import create_kill_switch, remove_kill_switch, check_kill_switch
from src.utils.logger import logger


# ── Two-step confirmation state ─────────────────────────────────────────────
import threading
import time

_pending_confirmations: dict[int, float] = {}  # {chat_id: timestamp}
_CONFIRM_TIMEOUT_SEC = 30  # Konfirmasi hangus setelah 30 detik
_pending_lock = threading.Lock()


def cmd_menu() -> str:
    """Tampilkan menu + ringkasan cepat."""
    kill_status = "ON" if check_kill_switch() else "OFF"
    with get_session() as db:
        open_count = db.query(PaperTrade).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY'])
        ).count()
        closed = db.query(PaperTrade).filter(PaperTrade.status == 'CLOSED').all()
        total_pnl = sum(t.pnl or 0 for t in closed)

    return (
        f"== MENU ==\n"
        f"Open: {open_count} | PnL: ${total_pnl:.2f} | Kill: {kill_status}\n"
        f"\n"
        f"/status  — Mode, leverage, kill switch\n"
        f"/trades  — Open trades (mode aktif)\n"
        f"/history [paper|testnet|mainnet]\n"
        f"/perf [paper|testnet|mainnet]\n"
        f"/close <id> — Close 1 trade by ID\n"
        f"/closeall   — Close SEMUA trade\n"
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


def cmd_close_trade(trade_id: str) -> str:
    try:
        tid = int(trade_id)
    except ValueError:
        return f"Trade ID tidak valid: {trade_id}"

    with get_session() as db:
        trade = db.query(PaperTrade).get(tid)
        if trade is None:
            return f"Trade {tid} tidak ditemukan."
        if trade.status not in ('OPEN', 'PENDING_ENTRY'):
            return f"Trade {tid} status={trade.status}, tidak bisa di-close."

        # ── Paper mode ────────────────────────────────────────────────
        if settings.EXECUTION_MODE != "live":
            trade.status = 'CLOSED'
            trade.close_reason = 'MANUAL'
            trade.close_timestamp = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
            return f"Trade {tid} closed (PAPER mode)."

    # ── Live mode ─────────────────────────────────────────────────────
    return _close_live_trade(tid)


def _close_live_trade(trade_id: int) -> str:
    """Close live trade: cancel SL/TP + close position at market."""
    from src.utils.exchange import get_exchange
    exchange = get_exchange()

    with get_session() as db:
        trade = db.query(PaperTrade).get(trade_id)
        if trade is None:
            return f"Trade {trade_id} tidak ditemukan."

        symbol = trade.pair
        close_side = 'sell' if trade.side == 'LONG' else 'buy'
        current_status = trade.status

        try:
            # Cancel SL order jika ada
            if trade.sl_order_id:
                try:
                    exchange.cancel_order(trade.sl_order_id, symbol)
                except Exception:
                    pass

            # Cancel TP order jika ada
            if trade.tp_order_id:
                try:
                    exchange.cancel_order(trade.tp_order_id, symbol)
                except Exception:
                    pass

            # Cancel pending entry order jika ada
            if current_status == 'PENDING_ENTRY' and trade.exchange_order_id:
                try:
                    exchange.cancel_order(trade.exchange_order_id, symbol)
                except Exception:
                    pass

            # Close position at market (jika posisi masih terbuka)
            if current_status == 'OPEN':
                close_order = exchange.create_order(
                    symbol=symbol,
                    type='market',
                    side=close_side,
                    amount=None,
                    params={'reduceOnly': True},
                )
                close_price = float(close_order.get('average', 0))

                if trade.side == 'LONG':
                    pnl = (close_price - trade.entry_price) * trade.size
                else:
                    pnl = (trade.entry_price - close_price) * trade.size

                trade.close_price = close_price
                trade.pnl = pnl
            else:
                pnl = 0

            trade.status = 'CLOSED'
            trade.close_reason = 'MANUAL'
            trade.close_timestamp = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)

            return f"Trade {trade_id} closed (LIVE). PnL: ${pnl:.2f}"

        except Exception as e:
            logger.error(f"Failed to close live trade {trade_id}: {e}")
            return f"ERROR closing trade {trade_id}: {e}"


def cmd_close_all_trades(chat_id: int = 0) -> str:
    """Two-step close all trades dengan per-chat confirmation + timeout."""
    now = time.time()

    with _pending_lock:
        # Bersihkan konfirmasi yang sudah expired
        expired_keys = [k for k, ts in _pending_confirmations.items() if now - ts > _CONFIRM_TIMEOUT_SEC]
        for k in expired_keys:
            del _pending_confirmations[k]

        is_pending = chat_id in _pending_confirmations

    if not is_pending:
        with get_session() as db:
            count = db.query(PaperTrade).filter(
                PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY'])
            ).count()

        if count == 0:
            return "Tidak ada open/pending trades untuk di-close."

        with _pending_lock:
            _pending_confirmations[chat_id] = now
        return (
            f"Ada {count} open/pending trades.\n"
            f"Kirim 'CONFIRM CLOSE ALL' dalam {_CONFIRM_TIMEOUT_SEC} detik untuk menutup SEMUA trade.\n"
            f"Tindakan ini TIDAK bisa dibatalkan."
        )

    # Step 2: Execute — hapus konfirmasi dulu
    with _pending_lock:
        _pending_confirmations.pop(chat_id, None)

    closed_count = 0
    errors = 0

    with get_session() as db:
        trade_ids = [t.id for t in db.query(PaperTrade).filter(
            PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY'])
        ).all()]

    for tid in trade_ids:
        result = cmd_close_trade(str(tid))
        if "ERROR" in result:
            errors += 1
        else:
            closed_count += 1

    return f"Closed {closed_count} trades. Errors: {errors}."


def cmd_kill() -> str:
    """Aktifkan kill switch — bot tidak buka trade baru."""
    create_kill_switch()
    return "KILL SWITCH ON — tidak ada trade baru."


def cmd_resume() -> str:
    """Nonaktifkan kill switch — bot bisa buka trade lagi."""
    remove_kill_switch()
    return "Kill switch OFF — bot bisa buka trade lagi."


def cmd_switch_mode(mode: str = "") -> str:
    """Switch antara paper, testnet, mainnet (runtime only)."""
    mode = mode.strip().lower()

    if mode == "paper":
        settings.EXECUTION_MODE = "paper"
        settings.USE_TESTNET = False
        return "Mode: PAPER (simulasi lokal). Restart kembali ke .env."

    elif mode == "testnet":
        settings.EXECUTION_MODE = "live"
        settings.USE_TESTNET = True
        return "Mode: TESTNET (Binance Futures Testnet). Restart kembali ke .env."

    elif mode == "mainnet":
        if not settings.CONFIRM_MAINNET:
            return "DITOLAK: CONFIRM_MAINNET=False. Set CONFIRM_MAINNET=True di .env dulu."
        settings.EXECUTION_MODE = "live"
        settings.USE_TESTNET = False
        return "Mode: MAINNET (Binance Futures Production — UANG ASLI). Restart kembali ke .env."

    else:
        current = "PAPER" if settings.EXECUTION_MODE != "live" else ("TESTNET" if settings.USE_TESTNET else "MAINNET")
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
    'close_trade': cmd_close_trade,
    'close_all_trades': cmd_close_all_trades,
    'activate_kill_switch': cmd_kill,
    'deactivate_kill_switch': cmd_resume,
    'show_menu': cmd_menu,
    'switch_mode': cmd_switch_mode,
    'unknown': cmd_unknown,
}
