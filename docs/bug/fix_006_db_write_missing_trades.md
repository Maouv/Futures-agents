# Fix Plan #006 — HIGH: DB Write Tidak Ter-Wrap, Trade Hilang dari DB

**Severity:** HIGH
**Confidence:** 90
**Estimasi waktu fix:** 15–20 menit

---

## Apa Masalahnya

Setelah limit order berhasil ditempatkan di Binance, step update DB
ke `PENDING_ENTRY` tidak punya error handling sendiri. Kalau step ini
gagal, order ada di Binance tapi tidak ada di DB — bot tidak akan
pernah monitor order ini.

Ini penyebab trade ID 18 tapi hanya 8 yang tercatat di `/perf`.

---

## Lokasi Bug

**File:** `src/agents/math/execution_agent.py`
**Fungsi:** `_execute_live_limit()`
**Step yang bermasalah:** Step 3 — UPDATE ke PENDING_ENTRY

---

## Kenapa Bisa Terjadi

Fungsi `_execute_live_limit()` punya 4 step dengan write-then-exchange
pattern. Step 3 (update DB setelah order placed) tidak ter-wrap `try/except`
lokal:

```python
# Step 2 berhasil — order SUDAH ADA di Binance
exchange_order_id = str(order['id'])
# exchange_order_id: '12345678'

# ── Step 3: UPDATE ke PENDING_ENTRY ───────────────────────────
with get_session() as db:
    db_trade = db.query(PaperTrade).get(trade_id)
    if db_trade:
        db_trade.status = 'PENDING_ENTRY'
        db_trade.exchange_order_id = exchange_order_id
# ↑ Kalau ini gagal (SQLite locked, disk full, timeout),
#   exception naik langsung ke:

except (ccxt.InsufficientFunds, ccxt.InvalidOrder, ccxt.NetworkError,
        ccxt.ExchangeError, Exception) as e:
    # Handler ini anggap exchange yang gagal — mark trade FAILED
    # LOG TIDAK MENYEBUT exchange_order_id yang sudah berhasil dibuat!
    with get_session() as db:
        db_trade = db.query(PaperTrade).get(trade_id)
        if db_trade:
            db_trade.status = 'FAILED'
```

Akibat: order ada di Binance dengan ID valid, tapi DB mencatat `FAILED`.
Bot tidak tahu order ini ada. Trade menjadi orphan selamanya.

Lebih parah lagi: log error tidak menyebutkan `exchange_order_id`,
jadi tidak ada cara untuk recovery manual dengan mudah.

---

## Cara Fix

Wrap Step 3 dalam `try/except` terpisah. Kalau gagal, log dengan
menyebutkan `exchange_order_id` secara eksplisit agar bisa recovery
manual.

```python
# ── Step 2: Place order di exchange ───────────────────────────
try:
    order = exchange.create_order(
        symbol=symbol,
        type='limit',
        side=side,
        amount=float(amount),
        price=float(price),
        params={'timeInForce': 'GTC'},
    )
    exchange_order_id = str(order['id'])
    self._log(
        f"LIMIT order placed | ID: {exchange_order_id} | "
        f"{symbol} {side.upper()} @ {price}"
    )

except (ccxt.InsufficientFunds, ccxt.InvalidOrder,
        ccxt.NetworkError, ccxt.ExchangeError, Exception) as e:
    # Exchange gagal — update DB ke FAILED
    self._log_error(f"Exchange error for trade {trade_id}: {e}")
    with get_session() as db:
        db_trade = db.query(PaperTrade).get(trade_id)
        if db_trade:
            db_trade.status = 'FAILED'
            db_trade.close_reason = 'EXCHANGE_ERROR'
            db_trade.close_timestamp = datetime.now(timezone.utc)
    return self._handle_ccxt_error(e, "live limit execution")

# ── Step 3: UPDATE ke PENDING_ENTRY — TERPISAH dari Step 2 ────
# Order sudah ada di exchange. Kalau step ini gagal, jangan
# mark FAILED — order-nya valid, hanya DB-nya yang bermasalah.
try:
    with get_session() as db:
        db_trade = db.query(PaperTrade).get(trade_id)
        if db_trade:
            db_trade.status = 'PENDING_ENTRY'
            db_trade.exchange_order_id = exchange_order_id

except Exception as db_err:
    # KRITIS: order sudah ada di Binance tapi DB gagal update
    # Log exchange_order_id agar bisa recovery manual
    logger.critical(
        f"CRITICAL DB WRITE FAILED | Trade {trade_id} | {symbol} | "
        f"Order ALREADY ON BINANCE with ID: {exchange_order_id} | "
        f"Error: {db_err} | "
        f"→ Manual: update DB trade {trade_id} status=PENDING_ENTRY "
        f"exchange_order_id={exchange_order_id}"
    )
    # Jangan raise — bot tidak perlu crash, order di exchange tetap valid

return ExecutionResult(
    action="PENDING",
    reason=f"Limit order placed, waiting for fill. Order ID: {exchange_order_id}",
    trade_id=trade_id
)
```

---

## File yang Diubah

| File | Fungsi | Jenis Perubahan |
|------|--------|-----------------|
| `src/agents/math/execution_agent.py` | `_execute_live_limit()` | Pisahkan try/except Step 2 dan Step 3 |

Tidak ada file lain yang perlu diubah.

---

## Cara Verifikasi Setelah Fix

1. Apply fix, restart bot
2. Cek log saat ada trade baru yang masuk dengan limit order
3. Cari baris:
   ```
   LIMIT order placed | ID: XXXXXXXX | XRPUSDT BUY @ 1.42
   ```
   Diikuti tidak ada error apapun setelahnya
4. Cek DB — trade harus ada dengan `status=PENDING_ENTRY` dan
   `exchange_order_id` yang sama dengan yang di log
5. Tidak ada lagi gap antara trade ID tertinggi dan total count di `/perf`
