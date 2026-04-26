# Fix Plan #005 — HIGH: TP Gagal Tanpa Notifikasi Actionable

**Severity:** HIGH
**Confidence:** 95
**Estimasi waktu fix:** 20–30 menit

---

## Apa Masalahnya

Ketika TP algo order gagal setelah semua retry, bot hanya menulis ke
log dan lanjut jalan. Tidak ada notifikasi Telegram. Kamu tidak tahu
ada trade OPEN tanpa TP sampai cek manual.

SL masih terpasang, tapi profit target tidak ada — posisi akan terus
berjalan sampai SL kena tanpa pernah lock profit.

---

## Lokasi Bug

Bug ada di **dua tempat berbeda** di file yang sama:

**File:** `src/agents/math/execution_agent.py`

**Tempat 1** — `_execute_live_market()` (jalur market order / overlap):
```python
# Sekitar line 412
except Exception as e:
    self._log_error(f"TP algo FAILED: {e}. SL still protects capital.")
    # ← lanjut tanpa notif, tp_order_id tetap None
```

**Tempat 2** — `_handle_fill()` (jalur limit order yang baru fill):
```python
# Sekitar line 706
if tp_order_id is None:
    self._log_error(
        f"WARNING: TP algo order FAILED after {SL_MAX_RETRIES} retries for trade {trade_id}. "
        f"SL still protects capital but trade has no TP — consider manual intervention."
    )
    # ← hanya log, tidak ada Telegram
```

---

## Kenapa Bisa Terjadi

`ExecutionAgent` tidak punya `notification_callback` di konstruktornya
— berbeda dari `UserDataStream` yang memang dirancang untuk kirim notif.
Selama ini semua notif dari execution flow dikirim oleh `main.py` setelah
agent return, bukan dari dalam agent sendiri.

Tapi untuk TP failure, `main.py` tidak tahu TP gagal karena `ExecutionResult`
tidak membawa informasi tersebut — result hanya `action="OPEN"` tanpa flag
apapun tentang kegagalan TP.

---

## Cara Fix

Tambah parameter optional `notification_callback` ke `ExecutionAgent`,
lalu kirim notif di kedua tempat TP gagal.

---

### Step 1 — Tambah `notification_callback` di `ExecutionAgent.__init__()`

Sekarang class `ExecutionAgent` tidak punya `__init__` eksplisit
(inherit dari `BaseAgent`). Tambahkan:

```python
class ExecutionAgent(BaseAgent):

    def __init__(self, notification_callback=None):
        """
        Args:
            notification_callback: Optional callable untuk kirim Telegram alert.
                                   Dipanggil dengan string message.
        """
        super().__init__()
        self._notification_callback = notification_callback

    def _send_alert(self, message: str) -> None:
        """Kirim alert via callback kalau tersedia, selalu log juga."""
        self._log_error(message)
        if self._notification_callback:
            try:
                self._notification_callback(message)
            except Exception as e:
                logger.error(f"Failed to send alert notification: {e}")
```

---

### Step 2 — Ganti log di Tempat 1 (`_execute_live_market()`)

```python
# SEBELUM:
except Exception as e:
    self._log_error(f"TP algo FAILED: {e}. SL still protects capital.")

# SESUDAH:
except Exception as e:
    self._send_alert(
        f"⚠️ TP GAGAL | Trade {trade_id} | {symbol}\n"
        f"SL @ {risk_result.sl_price:.4f} masih aktif.\n"
        f"Error: {e}\n"
        f"→ Manual TP perlu dipasang di Binance!"
    )
```

---

### Step 3 — Ganti log di Tempat 2 (`_handle_fill()`)

```python
# SEBELUM:
if tp_order_id is None:
    self._log_error(
        f"WARNING: TP algo order FAILED after {SL_MAX_RETRIES} retries for trade {trade_id}. "
        f"SL still protects capital but trade has no TP — consider manual intervention."
    )

# SESUDAH:
if tp_order_id is None:
    self._send_alert(
        f"⚠️ TP GAGAL setelah {SL_MAX_RETRIES} retry | Trade {trade_id} | {trade_pair}\n"
        f"SL @ {trade_sl_price:.4f} masih aktif.\n"
        f"→ Manual TP perlu dipasang di Binance!"
    )
```

---

### Step 4 — Update instansiasi `ExecutionAgent` di `main.py`

Cari baris di `main.py` di mana `ExecutionAgent` diinstansiasi
(biasanya di `__init__` class `TradingBot`), dan tambahkan callback:

```python
# SEBELUM:
self._execution_agent = ExecutionAgent()

# SESUDAH:
self._execution_agent = ExecutionAgent(
    notification_callback=self.send_notification_sync
)
```

---

## File yang Diubah

| File | Fungsi | Jenis Perubahan |
|------|--------|-----------------|
| `src/agents/math/execution_agent.py` | `ExecutionAgent.__init__()` | Tambah — ~10 baris |
| `src/agents/math/execution_agent.py` | `_send_alert()` | Tambah helper — ~8 baris |
| `src/agents/math/execution_agent.py` | `_execute_live_market()` | Ganti log → `_send_alert` |
| `src/agents/math/execution_agent.py` | `_handle_fill()` | Ganti log → `_send_alert` |
| `src/main.py` | instansiasi `ExecutionAgent` | Tambah `notification_callback` |

---

## Cara Verifikasi Setelah Fix

Ini bug yang sulit di-trigger secara sengaja karena butuh kondisi
TP gagal. Cara verifikasi:

1. Sementara: tambah temporary log di `_send_alert()` untuk konfirmasi
   fungsi dipanggil saat diinisiasi
2. Cek DB untuk trade OPEN dengan `tp_order_id IS NULL`:
   ```sql
   SELECT id, pair, side, tp_order_id FROM paper_trades
   WHERE status = 'OPEN' AND tp_order_id IS NULL
   AND execution_mode IN ('testnet', 'mainnet');
   ```
   Kalau ada row — itu trade yang sudah kena bug ini sebelumnya.
   Manual pasang TP di Binance untuk trade tersebut.
3. Ke depannya: kalau TP gagal, Telegram harus terima pesan alert
   dalam format `⚠️ TP GAGAL | Trade X | ETHUSDT`
