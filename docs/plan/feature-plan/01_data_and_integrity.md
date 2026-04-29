# Phase 1 — Data Integrity & Schema Fix
**Target: KR1 | Timeline: Minggu 1-2**

---

## Goal Phase Ini
Setelah phase ini selesai, setiap trade yang masuk DB harus punya data lengkap:
actual fill price, fee, net PnL, dan execution_mode yang tidak pernah NULL.

---

## Step 1 — Fix RR di config.json
**File:** `config.json`
**Estimasi waktu:** 5 menit
**Risk:** Low

### Apa yang diubah
```json
// SEBELUM
"risk_reward_ratio": 1.0

// SESUDAH
"risk_reward_ratio": 3.0
```

### Kenapa ini PERTAMA
Semua trades baru harus sudah pakai RR yang benar sebelum counting KR3 dimulai.
Kalau ini dilakukan belakangan, ada risk trades yang masuk dengan RR salah ikut dihitung.

### Verifikasi
Setelah ubah, cek log cycle berikutnya — TP price seharusnya 3x lebih jauh dari entry dibanding SL.

---

## Step 2 — Backup DB
**File:** `src/data/storage.py` → `backup_db()`
**Estimasi waktu:** 1 menit
**Risk:** None

### Apa yang dilakukan
Panggil `backup_db()` secara manual sebelum migration apapun. Function ini sudah ada dan sudah handle integrity check + rolling backup 7 file terakhir.

```python
# Jalankan sekali via script atau python shell
from src.data.storage import backup_db
backup_db()
```

### Verifikasi
Cek folder `data/backups/` — harus ada file `trading_YYYYMMDD_HHMMSS.db`.

---

## Step 3 — Schema Migration: Kolom Baru

**File:** `src/data/storage.py`
**Estimasi waktu:** 1-2 jam
**Risk:** Medium — test di environment baru dulu sebelum jalankan di DB live

### Kolom yang ditambah ke `PaperTrade`

```python
# Tambah di class PaperTrade, setelah kolom liq_price

# ── Actual fill data (dari Binance, bukan kalkulasi bot) ──────────────────
actual_entry_price: Mapped[float | None] = mapped_column(
    Float, nullable=True
)  # Actual fill price dari exchange (vs entry_price yang planned)

actual_close_price: Mapped[float | None] = mapped_column(
    Float, nullable=True
)  # Actual close price dari exchange (vs sl_price/tp_price yang planned)

slippage_entry: Mapped[float | None] = mapped_column(
    Float, nullable=True
)  # actual_entry_price - entry_price (negatif = dapat harga lebih baik)

slippage_close: Mapped[float | None] = mapped_column(
    Float, nullable=True
)  # actual_close_price - sl_price atau tp_price

# ── Fee tracking ──────────────────────────────────────────────────────────
fee_open: Mapped[float | None] = mapped_column(
    Float, nullable=True
)  # Fee saat open position (USDT)

fee_close: Mapped[float | None] = mapped_column(
    Float, nullable=True
)  # Fee saat close position (USDT)

# ── Net PnL (ini yang sebenarnya masuk kantong) ───────────────────────────
net_pnl: Mapped[float | None] = mapped_column(
    Float, nullable=True
)  # pnl - fee_open - fee_close
```

### Fix execution_mode: nullable → NOT NULL

```python
# SEBELUM
execution_mode: Mapped[str | None] = mapped_column(
    String(10), nullable=True, default="paper"
)

# SESUDAH
execution_mode: Mapped[str] = mapped_column(
    String(10), nullable=False, default="paper"
)
```

### Tambah indexes yang hilang

```python
# Ubah __table_args__ di class PaperTrade
__table_args__ = (
    Index("ix_paper_trades_status_mode", "status", "execution_mode"),
    Index("ix_paper_trades_pair_status", "pair", "status"),
    Index("ix_paper_trades_exchange_order_id", "exchange_order_id"),
)
```

### Fix DateTime timezone

```python
# SEBELUM (semua kolom DateTime)
entry_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
close_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

# SESUDAH
entry_timestamp: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), nullable=False
)
close_timestamp: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

> ⚠️ Setelah fix timezone, hapus semua `.replace(tzinfo=UTC)` manual yang ada di
> `execution_agent.py` dan `sltp_manager.py` — sudah tidak diperlukan.

---

## Step 4 — Update migrate_db()

**File:** `src/data/storage.py` → function `migrate_db()`
**Estimasi waktu:** 30 menit
**Risk:** Low

### Tambah ke list `new_columns`

```python
new_columns = [
    # ... kolom existing ...
    ("paper_trades", "actual_entry_price", "FLOAT"),
    ("paper_trades", "actual_close_price", "FLOAT"),
    ("paper_trades", "slippage_entry", "FLOAT"),
    ("paper_trades", "slippage_close", "FLOAT"),
    ("paper_trades", "fee_open", "FLOAT"),
    ("paper_trades", "fee_close", "FLOAT"),
    ("paper_trades", "net_pnl", "FLOAT"),
]
```

### Fix execution_mode NULL di data existing

Tambah di akhir `migrate_db()`:

```python
# Fix existing NULL execution_mode → default 'paper'
try:
    with engine.connect() as conn:
        result = conn.execute(text(
            "UPDATE paper_trades SET execution_mode = 'paper' "
            "WHERE execution_mode IS NULL OR execution_mode = ''"
        ))
        conn.commit()
        updated = result.rowcount
        if updated > 0:
            logger.info(f"Migration: Fixed {updated} trades with NULL execution_mode → 'paper'")
except Exception as e:
    logger.warning(f"Migration: Could not fix NULL execution_mode: {e}")
```

### Verifikasi setelah migrate_db() jalan

```sql
-- Harus return 0
SELECT COUNT(*) FROM paper_trades WHERE execution_mode IS NULL;

-- Cek kolom baru ada
PRAGMA table_info(paper_trades);
```

---

## Step 5 — Fee Tracking saat Trade Open

**File:** `src/agents/math/execution_agent.py`
**Estimasi waktu:** 1 jam
**Risk:** Medium

### Di `_execute_live_market()` — saat market order fill

Fee dan actual price diambil dari WebSocket fill event yang sudah ada — tidak perlu REST call tambahan:

```python
# Field sudah ada di WebSocket fill event
actual_entry_price = float(fill_data.get('ap', 0) or fill_data.get('L', 0))
commission_amount  = float(fill_data.get('n', 0))   # fee actual dari Binance
commission_asset   = fill_data.get('N', 'USDT')

fee_open = commission_amount

# Fallback ke estimasi kalau WebSocket miss commission
if fee_open == 0:
    taker_fee_rate = config.get("taker_fee_rate", 0.0004)
    fee_open = float(fill_data.get('z', 0)) * actual_entry_price * taker_fee_rate

trade = PaperTrade(
    # ... existing fields ...
    actual_entry_price=actual_entry_price,
    slippage_entry=actual_entry_price - risk_result.entry_price,
    fee_open=fee_open,
)
```

### Di `_handle_fill()` — saat limit order fill (PENDING_ENTRY → OPEN)

```python
actual_entry_price = float(fill_data.get('ap', 0) or fill_data.get('L', 0))
commission_amount  = float(fill_data.get('n', 0))
fee_open = commission_amount

if fee_open == 0:
    taker_fee_rate = config.get("taker_fee_rate", 0.0004)
    fee_open = float(fill_data.get('z', 0)) * actual_entry_price * taker_fee_rate

db_trade.actual_entry_price = actual_entry_price
db_trade.slippage_entry = actual_entry_price - db_trade.entry_price
db_trade.fee_open = fee_open
```

### Fee rate di config — jangan hardcode

Tambah ke `config.json`:
```json
"taker_fee_rate": 0.0004
```

> Default 0.0004 (0.04%) cukup untuk estimasi. Di mainnet bisa turun kalau
> hold BNB + fee discount aktif (→ 0.00036). Karena ini bisa berubah,
> jangan hardcode di kode — baca dari config.

```python
# Di execution_agent.py — baca dari config, bukan hardcode
TAKER_FEE_RATE = config.get("taker_fee_rate", 0.0004)
```

> **Catatan:** Fee estimasi ini hanya fallback kalau WebSocket miss commission data.
> Prioritas utama tetap ambil `commission` actual dari Binance — lihat Step 6.

---

## Step 6 — Fee Tracking saat Trade Close

**File:** `src/data/ws_user_stream.py` → `_handle_order_update()`
**File:** `src/agents/math/sltp_manager.py` → `check_paper_trades()`
**Estimasi waktu:** 1 jam
**Risk:** Medium

### Di `ws_user_stream.py` — live trade close via WebSocket

Field yang sudah tersedia di `ORDER_TRADE_UPDATE` event, tinggal diparse:

```python
# Field WebSocket yang sudah ada — tidak perlu REST call tambahan
actual_close_price = float(order_data.get('ap', 0) or order_data.get('L', 0))  # avg fill price
commission_amount  = float(order_data.get('n', 0))   # fee actual dari Binance (USDT atau BNB)
commission_asset   = order_data.get('N', 'USDT')      # asset fee (USDT/BNB)
realized_pnl       = float(order_data.get('rp', 0))   # realized PnL dari Binance

# Kalau commission dalam BNB, convert ke USDT (atau skip jika tidak ada rate)
# Untuk simplicity awal: simpan as-is, tambahkan commission_asset ke DB juga
fee_close = commission_amount  # actual dari Binance, bukan estimasi

# Fallback ke estimasi kalau WebSocket miss commission (n=0)
if fee_close == 0:
    taker_fee_rate = config.get("taker_fee_rate", 0.0004)
    fee_close = float(order_data.get('z', trade.size)) * actual_close_price * taker_fee_rate

net_pnl_val = realized_pnl - (trade.fee_open or 0) - fee_close

trade.actual_close_price = actual_close_price
trade.slippage_close = actual_close_price - (
    trade.sl_price if close_reason == 'SL' else trade.tp_price
)
trade.fee_close = fee_close
trade.net_pnl = net_pnl_val
```

### Di `execution_agent.py` — ambil fee saat order open

Sama, dari WebSocket fill event yang sudah ada:

```python
actual_entry_price = float(fill_data.get('ap', 0) or fill_data.get('L', 0))
commission_amount  = float(fill_data.get('n', 0))   # fee actual
commission_asset   = fill_data.get('N', 'USDT')

fee_open = commission_amount

# Fallback kalau miss
if fee_open == 0:
    taker_fee_rate = config.get("taker_fee_rate", 0.0004)
    fee_open = float(fill_data.get('z', 0)) * actual_entry_price * taker_fee_rate

trade.actual_entry_price = actual_entry_price
trade.slippage_entry = actual_entry_price - trade.entry_price
trade.fee_open = fee_open
```

### Di `sltp_manager.py` — paper trade close

Paper mode tidak ada WebSocket fill, jadi pakai formula estimasi dari config:

```python
taker_fee_rate = config.get("taker_fee_rate", 0.0004)
fee_close = trade.size * close_price * taker_fee_rate
net_pnl_val = pnl - (trade.fee_open or 0) - fee_close

trade.actual_close_price = close_price  # paper = planned price, tidak ada slippage
trade.fee_close = fee_close
trade.net_pnl = net_pnl_val
```

> **Note:** Paper mode tidak punya actual fill price — set `actual_entry_price = entry_price`
> dan `fee_open` pakai estimasi saat trade OPEN di `_execute_paper()`.
> Fee paper mode adalah simulasi, bukan angka real.

---

## Step 7 — Audit Data Historis

**File:** Script one-time (tidak perlu masuk ke codebase)
**Estimasi waktu:** 30 menit
**Risk:** Low — read-only query

### Query untuk audit

```python
# audit_trades.py — jalankan sekali, tidak perlu commit ke repo
from src.data.storage import get_session, PaperTrade

with get_session() as db:
    # 1. Trades dengan execution_mode NULL
    null_mode = db.query(PaperTrade).filter(
        PaperTrade.execution_mode == None
    ).all()
    print(f"NULL execution_mode: {len(null_mode)} trades")
    for t in null_mode:
        print(f"  ID {t.id}: {t.pair} {t.side} {t.status} @ {t.entry_timestamp}")

    # 2. Semua trades per mode
    from sqlalchemy import func
    summary = db.query(
        PaperTrade.execution_mode,
        PaperTrade.status,
        func.count(PaperTrade.id).label('count')
    ).group_by(PaperTrade.execution_mode, PaperTrade.status).all()

    print("\nTrade summary by mode + status:")
    for row in summary:
        print(f"  {row.execution_mode or 'NULL'} | {row.status}: {row.count}")

    # 3. Closed testnet trades (kandidat KR3)
    from datetime import datetime, UTC
    closed_testnet = db.query(PaperTrade).filter(
        PaperTrade.execution_mode == 'testnet',
        PaperTrade.status == 'CLOSED',
    ).order_by(PaperTrade.entry_timestamp).all()

    print(f"\nClosed testnet trades: {len(closed_testnet)}")
    wins = sum(1 for t in closed_testnet if t.pnl and t.pnl > 0)
    losses = len(closed_testnet) - wins
    total_pnl = sum(t.pnl or 0 for t in closed_testnet)
    print(f"  Win/Loss: {wins}W/{losses}L")
    print(f"  Total gross PnL: ${total_pnl:.2f}")
```

### Output yang diharapkan
Dari hasil audit ini, catat:
- Berapa trades yang data-nya bersih (execution_mode tidak NULL)
- Tanggal trade testnet pertama yang valid → ini jadi start date counting KR3
- Apakah ada trades dengan execution_mode='paper' yang seharusnya testnet

---

## Checklist KR1

- [ ] RR diubah ke 3.0 di config.json
- [ ] DB di-backup sebelum migration
- [ ] Kolom baru ditambah (actual_entry_price, actual_close_price, slippage_entry, slippage_close, fee_open, fee_close, net_pnl)
- [ ] Indexes ditambah ke paper_trades
- [ ] DateTime timezone fix
- [ ] migrate_db() diupdate dan dijalankan
- [ ] NULL execution_mode sudah di-fix
- [ ] Fee tracking aktif di execution_agent.py
- [ ] Fee tracking aktif di ws_user_stream.py
- [ ] Audit script dijalankan, hasil dicatat
- [ ] Verifikasi: `SELECT COUNT(*) FROM paper_trades WHERE execution_mode IS NULL` = 0
