# Fix Plan #002 — CRITICAL: WS Entry Fill Diabaikan, SL/TP Telat 15 Menit

**Severity:** CRITICAL
**Confidence:** 95
**Estimasi waktu fix:** 30–45 menit

---

## Apa Masalahnya

Ketika limit order fill di Binance, WebSocket langsung mendapat event
`ORDER_TRADE_UPDATE`. Tapi bot tidak melakukan apapun dengan event itu
untuk entry order — SL/TP baru dipasang 15 menit kemudian saat
`check_pending_orders()` dipanggil di main cycle.

Posisi bisa berjalan **tanpa SL/TP hingga 14 menit** di crypto yang volatile.

---

## Lokasi Bug

**File:** `src/data/ws_user_stream.py`
**Fungsi:** `_handle_order_update()`
**Baris kritis:** ~270–275 (blok `else` di bagian determine close reason)

---

## Kenapa Bisa Terjadi

Di `_handle_order_update()`, setelah order FILLED terdeteksi, bot
menentukan apakah ini SL, TP, atau entry order:

```python
if order_type in ('STOP_MARKET', 'STOP'):
    close_reason = 'SL'
    counter_order_id = trade.tp_order_id

elif order_type in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT'):
    close_reason = 'TP'
    counter_order_id = trade.sl_order_id

else:
    # Entry order fill — tidak perlu close trade
    logger.debug(f"Entry order fill detected for trade {trade.id}")
    return   # ← BERHENTI DI SINI. Tidak ada SL/TP yang dipasang.
```

Sementara itu, `check_pending_orders()` di `execution_agent.py` adalah
satu-satunya yang memanggil `_handle_fill()` untuk place SL/TP.
Dan `check_pending_orders()` hanya dipanggil setiap 15 menit dari
`main.py`.

---

## Cara Fix

Saat WS detect entry fill, langsung panggil `check_pending_orders()`
di thread terpisah agar tidak memblokir WS loop.

`check_pending_orders()` sudah idempotent — kalau dipanggil dua kali
(dari WS dan dari main cycle), yang kedua akan menemukan trade sudah
`OPEN` dan skip tanpa double-place SL/TP.

**Step 1 — Ganti blok `else` di `_handle_order_update()`:**

```python
else:
    # Entry order fill — place SL/TP langsung tanpa tunggu 15 menit
    logger.info(
        f"Entry order fill detected via WS for trade {trade.id} ({symbol}) "
        f"— triggering immediate SL/TP placement"
    )
    trade_id_copy = trade.id
    pair_copy = trade.pair
    # Spawn thread agar tidak block async WS loop
    threading.Thread(
        target=self._handle_entry_fill_async,
        args=(trade_id_copy, pair_copy),
        daemon=True,
    ).start()
    return
```

**Step 2 — Tambah fungsi `_handle_entry_fill_async()` di class `UserDataStream`:**

```python
def _handle_entry_fill_async(self, trade_id: int, pair: str) -> None:
    """
    Dipanggil dari background thread saat entry order fill terdeteksi via WS.
    Trigger check_pending_orders() untuk place SL/TP tanpa tunggu 15 menit.
    """
    try:
        from src.agents.math.execution_agent import ExecutionAgent
        agent = ExecutionAgent()
        results = agent.check_pending_orders()

        for r in results:
            if r.get('trade_id') == trade_id and r.get('action') == 'filled':
                logger.info(
                    f"SL/TP placed immediately via WS fill handler | "
                    f"Trade {trade_id} | {pair}"
                )
                if self._notification_callback:
                    self._notification_callback({
                        'event': 'trade_filled',
                        'trade_id': trade_id,
                        'pair': pair,
                    })
                break

    except Exception as e:
        logger.error(
            f"WS entry fill handler failed for trade {trade_id} ({pair}): {e} "
            f"— SL/TP will be placed at next 15min cycle"
        )
```

**Step 3 — Pastikan `threading` sudah diimport** (sudah ada di file ini,
tidak perlu tambah import baru).

---

## File yang Diubah

| File | Fungsi | Jenis Perubahan |
|------|--------|-----------------|
| `src/data/ws_user_stream.py` | `_handle_order_update()` | Ganti blok `else` — ~5 baris |
| `src/data/ws_user_stream.py` | `_handle_entry_fill_async()` (baru) | Tambah fungsi — ~20 baris |

Tidak ada file lain yang perlu diubah. Tidak ada dependency baru.

---

## Cara Verifikasi Setelah Fix

1. Apply fix, restart bot
2. Tunggu limit order fill (atau force fill manual di Binance demo)
3. Cek log bot — cari baris:
   ```
   SL/TP placed immediately via WS fill handler | Trade X | XRPUSDT
   ```
4. Cek Binance demo → Open Orders → Conditional — SL dan TP harus muncul
   dalam hitungan detik setelah fill, bukan 15 menit kemudian
5. Di Telegram, notif "LIVE order FILLED → SL/TP placed" harus datang
   hampir bersamaan dengan fill, bukan 15 menit kemudian
