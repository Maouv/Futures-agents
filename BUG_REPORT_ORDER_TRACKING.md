# Bug Report: Testnet Order ID 13032917912 Not Persisted Correctly

**Date**: 2026-04-18
**Order**: 13032917912 (BTCUSDT BUY @ 70829.4, 2026-04-13 17:00:02 UTC)

---

## Temuan 1: Bot Start Mode vs Execution Mismatch

Log startup 03:05:16 UTC menunjukkan **"Mode: PAPER"**, tetapi pada 17:00:02 UTC bot menempatkan LIMIT order ke Binance testnet (log: `[ExecutionAgent] LIMIT order placed | ID: 13032917912`). Ini membuktikan bot beralih dari PAPER ke LIVE tanpa restart.

## Temuan 2: execution_mode Tersimpan Salah ('paper' instead of 'testnet')

Database query seluruh 6 rows di `paper_trades` menunjukkan **semua** `execution_mode='paper'` dan **semua** `exchange_order_id=NULL`**, termasuk trade yang seharusnya testnet/live.

## Temuan 3: DB Write Log Hilang

Setelah log "LIMIT order placed" di line 3263, log langsung lanjut ke pair berikutnya (ETHUSDT di line 3264). Tidak ada log konfirmasi DB write (seharusnya ada log seperti "PAPER TRADE PENDING" atau "LIVE TRADE PENDING" dari ExecutionAgent). Ini mengindikasikan DB write **gagal silent** atau **tidak dieksekusi**.

## Temuan 4: execution_agent.py DB Write Tidak Ter-try/except secara lokal

Di `_execute_live_limit()` (line 281-297), bagian DB write dengan `get_session()` tidak ter-wrap dalam try/except lokal. Hanya bagian ccxt order (line 262-271) yang ter-handle oleh error handler di line 305. Jika DB write gagal, error propagates dan bisa crash silent tanpa log.

---

## Root Cause Analysis

Penyebab utama adalah **mode switch tanpa restart** + **`get_current_mode()` yang membaca config.json saat runtime**:

1. Bot di-start jam 03:05 dengan `execution_mode: "paper"` di config.json
2. User mengubah mode via Telegram `/mode` command atau edit config.json menjadi `"live"` tanpa restart
3. `settings.EXECUTION_MODE` berubah jadi `"live"` (via setter di settings.py line 108-110)
4. `get_current_mode()` di mode.py line 6-10 membaca `settings.EXECUTION_MODE` yang sudah berubah, tapi **exchange singleton masih stale** (belum di-reset untuk mode baru)
5. `_execute_live_limit()` dipanggil → order ditempatkan ke exchange → DB write menggunakan `get_current_mode()` yang sekarang返回 `testnet` atau `paper` tergantung timing
6. Jika timing tepat, `execution_mode` tersimpan sebagai `'paper'` padahal order benar-benar di exchange
7. DB write gagal silent karena tidak ada try/except lokal → order ada di exchange tapi tidak ada di DB

Dokumentasi CLAUDE.md sudah mencatat known issue ini: **"Mode switch without restart: Changing EXECUTION_MODE without restart leaves stale exchange config."**

---

## Rekomендasi Fix

### Step 1: Guard mode switch di main.py startup (Paling Kritis)

Di `TradingBot.run()` (main.py line 234-245), tambahkan validasi: jika `config.json` berubah dari PAPER ke LIVE setelah bot start, **reject dan minta restart**:

```python
# Cek apakah mode berubah dari startup mode
startup_mode = self._startup_mode  # simpan saat __init__
current_mode = settings.EXECUTION_MODE
if startup_mode != current_mode:
    logger.critical(
        f"EXECUTION_MODE changed from '{startup_mode}' to '{current_mode}' "
        f"without restart. This causes stale exchange config. RESTART REQUIRED."
    )
    return
```

### Step 2: Tambah try/except lokal di _execute_live_limit() DB write

Di execution_agent.py line 281-297, wrap DB write dalam try/catch:

```python
# ── Store PENDING_ENTRY di DB ─────────────────────────────────
try:
    with get_session() as db:
        trade = PaperTrade(...)
        db.add(trade)
        db.flush()
        trade_id = trade.id
    self._log(f"DB write OK | Trade {trade_id} stored | mode={get_current_mode()}")
except Exception as e:
    self._log_error(f"DB WRITE FAILED after order placed! Order {exchange_order_id} on exchange but NOT in DB: {e}")
    # TODO: Consider canceling order or manual reconciliation
```

### Step 3: Tambah log konfirmasi setelah DB write

Di execution_agent.py, setelah line 297 (db.flush()), tambahkan log:

```python
self._log(
    f"LIVE TRADE PENDING | ID: {trade_id} | "
    f"{symbol} {reversal_result.signal} | "
    f"Limit @ {price} | Order ID: {exchange_order_id} | Mode: {get_current_mode()}"
)
```

### Step 4: Reconcile order 13032917912 secara manual

Order 13032917912 ada di Binance testnet tapi tidak di DB. Langsung insert manual:

```sql
INSERT INTO paper_trades (pair, side, entry_price, sl_price, tp_price, size, leverage,
  status, execution_mode, exchange_order_id, entry_timestamp)
VALUES ('BTCUSDT', 'LONG', 70829.4, 70201.98, 72711.87, 0.0239, 25,
  'PENDING_ENTRY', 'testnet', '13032917912', '2026-04-13 17:00:02');
```

Kemudian jalankan `check_pending_orders()` untuk sync status dari exchange.

### Step 5: Tambah check di check_pending_orders()

Di execution_agent.py `_check_single_pending()`, tambahkan logging execution_mode untuk audit:

```python
self._log(f"Checking pending | Trade {trade_id} | Mode: {trade.get('execution_mode')} | Order: {trade_exchange_order_id}")
```

---

## Files Referenced

- `/root/futures-agents/src/agents/math/execution_agent.py` — lines 240-306 (_execute_live_limit), 433-567 (check_pending_orders)
- `/root/futures-agents/src/utils/mode.py` — lines 6-10 (get_current_mode)
- `/root/futures-agents/src/config/settings.py` — lines 99-110 (EXECUTION_MODE property + setter)
- `/root/futures-agents/src/main.py` — lines 234-245 (startup safety checks)
- `/root/futures-agents/src/data/storage.py` — lines 81-107 (PaperTrade model, execution_mode default 'paper')
- `/root/futures-agents/logs/trading_2026-04-13.log.zip` — line 3263 (order placement log)
