# Phase 2 — Observability & Telegram Report
**Target: KR2 | Timeline: Minggu 2-3**
**Dependency: Phase 1 harus selesai dulu**

---

## Goal Phase Ini
Setelah phase ini selesai, kamu bisa jawab pertanyaan berikut hanya dari Telegram:
- "Berapa win rate testnet saya minggu ini?"
- "Berapa net PnL setelah fee?"
- "Trade mana yang paper, mana yang testnet?"

---

## Step 1 — Pisahkan Label di Setiap Trade Notification

**File:** `src/main.py`
**Estimasi waktu:** 30 menit
**Risk:** Low

### Sekarang (semua sama)
```
🟢 LIVE LONG | BTCUSDT
Entry: $77,400
SL: $76,800 | TP: $78,600
```

### Target (ada label mode jelas)
```
🟡 [TESTNET] LONG | BTCUSDT
Entry: $77,400.00
SL: $76,800.00 | TP: $78,600.00
Risk: $5.00 | RR: 1:3
```

### Implementasi

Buat helper function di `src/utils/mode.py`:

```python
def get_mode_emoji() -> str:
    """Return emoji label per mode untuk Telegram notification."""
    mode = get_current_mode()
    return {
        "paper": "📄",
        "testnet": "🟡",
        "mainnet": "🟢",
    }.get(mode, "❓")

def get_mode_tag() -> str:
    """Return text tag per mode."""
    mode = get_current_mode()
    return {
        "paper": "[PAPER]",
        "testnet": "[TESTNET]",
        "mainnet": "[MAINNET]",
    }.get(mode, "[UNKNOWN]")
```

Lalu update semua `send_notification_sync()` di `main.py`:

```python
# SEBELUM
f"{get_mode_label()} {decision.action} | {symbol}\n"

# SESUDAH
f"{get_mode_emoji()} {get_mode_tag()} {decision.action} | {symbol}\n"
```

---

## Step 2 — Update Trade Close Notification (pakai net_pnl)

**File:** `src/main.py` → `_ws_notification_handler()`
**File:** `src/main.py` → `_run_sltp_check()`
**Estimasi waktu:** 30 menit
**Risk:** Low

### Target format trade close notification

```
✅ [TESTNET] TP Hit
XRPUSDT LONG
Entry: $1.4230 → Close: $1.5100
Gross PnL: +$3.64
Fee: -$0.12
Net PnL: +$3.52
```

### Implementasi di `_ws_notification_handler()`

```python
def _ws_notification_handler(self, data: dict) -> None:
    if data.get('event') == 'trade_closed':
        trade = data
        pnl = trade.get('pnl', 0)
        net_pnl = trade.get('net_pnl', pnl)  # fallback ke gross kalau net belum ada
        fee_total = trade.get('fee_open', 0) + trade.get('fee_close', 0)
        emoji = "✅" if net_pnl > 0 else "❌"
        mode_tag = get_mode_tag()

        fee_line = f"Fee: -${fee_total:.4f}\n" if fee_total > 0 else ""

        self.send_notification_sync(
            f"{emoji} {mode_tag} {trade['close_reason']} Hit\n"
            f"{trade['pair']} {trade['side']}\n"
            f"Close: ${trade.get('close_price', 0):,.4f}\n"
            f"Gross PnL: ${pnl:+.2f}\n"
            f"{fee_line}"
            f"Net PnL: ${net_pnl:+.2f}"
        )
```

> **Note:** Untuk WS handler, `net_pnl` perlu di-pass lewat notification callback dict.
> Update `_handle_order_update()` di `ws_user_stream.py` untuk include `net_pnl`, `fee_open`, `fee_close` di dict yang dikirim ke callback.

---

## Step 3 — Command `/stats` yang Proper

**File:** `src/telegram/commands.py`
**Estimasi waktu:** 2-3 jam
**Risk:** Low

### Format output target

```
📊 Trading Statistics

🟡 TESTNET — Last 30 days
━━━━━━━━━━━━━━━━━━━━
Closed trades : 12
Win / Loss    : 7W / 5L
Win Rate      : 58.3%
Gross PnL     : +$8.40
Total Fees    : -$0.96
Net PnL       : +$7.44
Avg net/trade : +$0.62
Best trade    : +$3.52 (XRPUSDT)
Worst trade   : -$5.02 (ETHUSDT)

Open trades   : 3
━━━━━━━━━━━━━━━━━━━━

📄 PAPER — Last 30 days
━━━━━━━━━━━━━━━━━━━━
Closed trades : 8
Win Rate      : 62.5%
Net PnL       : +$12.30 (simulated)
━━━━━━━━━━━━━━━━━━━━
```

### Implementasi

```python
from datetime import UTC, datetime, timedelta
from sqlalchemy import func
from src.data.storage import PaperTrade, get_session

def build_stats_for_mode(mode: str, days: int = 30) -> str:
    """Build stats string untuk satu mode."""
    since = datetime.now(UTC) - timedelta(days=days)
    mode_emoji = {"paper": "📄", "testnet": "🟡", "mainnet": "🟢"}.get(mode, "❓")
    mode_label = mode.upper()

    with get_session() as db:
        closed = db.query(PaperTrade).filter(
            PaperTrade.execution_mode == mode,
            PaperTrade.status == 'CLOSED',
            PaperTrade.entry_timestamp >= since,
        ).all()

        open_trades = db.query(PaperTrade).filter(
            PaperTrade.execution_mode == mode,
            PaperTrade.status == 'OPEN',
        ).count()

    if not closed:
        return f"{mode_emoji} {mode_label}\nNo closed trades in last {days} days.\n"

    wins = [t for t in closed if (t.net_pnl or t.pnl or 0) > 0]
    losses = [t for t in closed if (t.net_pnl or t.pnl or 0) <= 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0

    gross_pnl = sum(t.pnl or 0 for t in closed)
    total_fee = sum((t.fee_open or 0) + (t.fee_close or 0) for t in closed)
    net_pnl = sum(t.net_pnl or t.pnl or 0 for t in closed)
    avg_net = net_pnl / len(closed) if closed else 0

    # Best and worst by net_pnl
    sorted_trades = sorted(closed, key=lambda t: t.net_pnl or t.pnl or 0)
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
        f"Best trade    : ${(best.net_pnl or best.pnl or 0):+.2f} ({best.pair})",
        f"Worst trade   : ${(worst.net_pnl or worst.pnl or 0):+.2f} ({worst.pair})",
    ]

    if open_trades > 0:
        lines.append(f"\nOpen trades   : {open_trades}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


async def stats_command(update, context):
    """Handler untuk /stats command."""
    msg = "📊 Trading Statistics\n\n"

    current_mode = get_current_mode()

    # Selalu tampilkan mode yang sedang aktif dulu
    msg += build_stats_for_mode(current_mode)
    msg += "\n"

    # Tampilkan mode lain kalau ada data
    for mode in ["testnet", "paper", "mainnet"]:
        if mode != current_mode:
            section = build_stats_for_mode(mode)
            if "No closed trades" not in section:
                msg += section + "\n"

    await update.message.reply_text(msg)
```

### Register command di bot

Di `src/telegram/bot.py`, tambah:
```python
from src.telegram.commands import stats_command
app.add_handler(CommandHandler("stats", stats_command))
```

---

## Step 4 — Command `/trade <id>` untuk Detail Per Trade

**File:** `src/telegram/commands.py`
**Estimasi waktu:** 1 jam
**Risk:** Low

### Format output target

```
🔍 Trade Detail #23

Pair    : XRPUSDT
Side    : LONG
Mode    : 🟡 TESTNET
Status  : CLOSED (TP)

Entry
  Planned : $1.4230
  Actual  : $1.4235
  Slippage: +$0.0005

Exit
  Planned : $1.5100 (TP)
  Actual  : $1.5098
  Slippage: -$0.0002

P&L
  Gross   : +$3.64
  Fee open: -$0.06
  Fee close: -$0.06
  Net PnL : +$3.52

Opened  : 2026-04-26 20:03 UTC
Closed  : 2026-04-27 02:15 UTC
Duration: ~6h 12m
```

### Implementasi

```python
async def trade_detail_command(update, context):
    """Handler untuk /trade <id>."""
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /trade <id>")
        return

    trade_id = int(args[0])

    with get_session() as db:
        trade = db.query(PaperTrade).get(trade_id)
        if not trade:
            await update.message.reply_text(f"Trade #{trade_id} tidak ditemukan.")
            return

        mode_emoji = {"paper": "📄", "testnet": "🟡", "mainnet": "🟢"}.get(
            trade.execution_mode, "❓"
        )

        duration = ""
        if trade.close_timestamp and trade.entry_timestamp:
            delta = trade.close_timestamp - trade.entry_timestamp
            hours = int(delta.total_seconds() // 3600)
            minutes = int((delta.total_seconds() % 3600) // 60)
            duration = f"~{hours}h {minutes}m"

        slippage_entry = trade.slippage_entry
        slippage_close = trade.slippage_close
        fee_open = trade.fee_open or 0
        fee_close = trade.fee_close or 0
        net_pnl = trade.net_pnl or trade.pnl or 0
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
            slippage_str = f"+${slippage_entry:.4f}" if slippage_entry and slippage_entry >= 0 else f"${slippage_entry:.4f}" if slippage_entry else "N/A"
            msg += (
                f"Entry\n"
                f"  Planned : ${trade.entry_price:,.4f}\n"
                f"  Actual  : ${trade.actual_entry_price:,.4f}\n"
                f"  Slippage: {slippage_str}\n\n"
            )

        if trade.actual_close_price:
            planned_close = trade.sl_price if trade.close_reason == 'SL' else trade.tp_price
            slippage_close_str = f"+${slippage_close:.4f}" if slippage_close and slippage_close >= 0 else f"${slippage_close:.4f}" if slippage_close else "N/A"
            msg += (
                f"Exit\n"
                f"  Planned : ${planned_close:,.4f} ({trade.close_reason})\n"
                f"  Actual  : ${trade.actual_close_price:,.4f}\n"
                f"  Slippage: {slippage_close_str}\n\n"
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

        await update.message.reply_text(msg)
```

---

## Checklist KR2

- [ ] Mode emoji + tag di semua trade open notifications
- [ ] Trade close notification tampilkan gross PnL, fee, net PnL
- [ ] `/stats` command live dan tampilkan per mode
- [ ] `/trade <id>` command live dengan detail lengkap
- [ ] Paper dan testnet/mainnet stats tidak tercampur
- [ ] Net PnL yang ditampilkan sudah pakai `net_pnl` kolom (bukan `pnl`)
