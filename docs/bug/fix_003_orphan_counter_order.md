# Fix Plan #003 — CRITICAL: Counter-Order Cancel Selalu Gagal (Orphan SL/TP)

**Severity:** CRITICAL
**Confidence:** 100
**Estimasi waktu fix:** 45–60 menit

---

## Apa Masalahnya

Setelah SL hit, bot seharusnya cancel TP yang tersisa (dan sebaliknya).
Tapi cancel ini selalu gagal — SL/TP yang harusnya di-cancel tetap
hidup di Binance sebagai orphan order tanpa posisi aktif.

Terbukti dari screenshot: SUIUSDT TP (23 Apr), BTCUSDT SL (22 Apr),
SOLUSDT TP (20 Apr) masih ada di Open Orders padahal posisinya sudah
lama closed.

---

## Lokasi Bug

**File 1:** `src/data/ws_user_stream.py`
**Fungsi:** `_cancel_counter_order()`
**Baris kritis:** ~324–345

**File 2:** `src/utils/exchange.py`
**Fungsi:** `cancel_algo_order()`
**Baris kritis:** ~231 (URL hardcoded, bukan masalah utama tapi terkait)

---

## Kenapa Bisa Terjadi

Ini kombinasi dari dokumentasi di CLAUDE.md sendiri yang sudah mengakui
masalahnya, tapi fix-nya tidak pernah diimplementasikan:

> "WS TRIGGER: ORDER_TRADE_UPDATE.i = orderId NEW (not algoId)"

**Alur yang salah sekarang:**

1. SL algo order ter-trigger di Binance
2. WS menerima `ORDER_TRADE_UPDATE` dengan `orderId` baru (bukan `algoId`)
3. Bot berhasil match trade via fallback (symbol + side) ✓
4. Bot ambil `counter_order_id = trade.tp_order_id` dari DB
5. `trade.tp_order_id` berisi **`algoId`** yang disimpan saat TP dibuat
6. `_cancel_counter_order(algoId)` dipanggil
7. `cancel_algo_order(algoId)` kirim `DELETE /fapi/v1/algoOrder?algoId=X`
8. TP yang belum trigger masih punya `algoId` yang valid di sistem Algo
9. **Tapi**: error handling di `_cancel_counter_order()` hanya catch
   string tertentu (`'Unknown order'`, `'Order does not exist'`,
   `'algoId'`). Kalau Binance return error lain (misalnya rate limit,
   timeout, atau format error berbeda) → error di-log sebagai CRITICAL
   tapi tidak di-retry → counter-order tetap hidup

Masalah intinya: strategi cancel by ID rapuh. Kalau ID tidak cocok
atau response error tidak sesuai string yang dicek, cancel gagal silent.

---

## Cara Fix

Ganti strategi cancel dari **"cancel by ID"** menjadi
**"fetch open algo orders by symbol, cancel yang tipe berlawanan"**.
Ini tidak bergantung pada kecocokan ID sama sekali.

---

### Step 1 — Tambah fungsi `get_open_algo_orders()` di `exchange.py`

```python
def get_open_algo_orders(symbol: str) -> list:
    """
    Fetch semua open algo orders untuk symbol tertentu via Binance Algo API.
    Digunakan untuk cancel counter-order (SL/TP) setelah trade closed.

    Args:
        symbol: Trading pair, e.g. 'BTCUSDT'

    Returns:
        List of dict, masing-masing berisi setidaknya 'algoId' dan 'type'
    """
    import time
    import hashlib
    import hmac
    import urllib.parse
    import requests as http_requests

    exchange = get_exchange()

    params = {
        'symbol': symbol,
        'timestamp': int(time.time() * 1000),
    }

    query = urllib.parse.urlencode(params)
    signature = hmac.new(
        exchange.secret.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()
    query += f'&signature={signature}'

    if settings.USE_TESTNET:
        base_url = settings.BINANCE_TESTNET_URL.rstrip('/')
    else:
        base_url = 'https://fapi.binance.com'

    url = f'{base_url}/fapi/v1/openAlgoOrders?{query}'
    headers = {'X-MBX-APIKEY': exchange.apiKey}

    response = http_requests.get(url, headers=headers, timeout=10)
    result = response.json()

    if response.status_code != 200:
        raise ccxt.ExchangeError(f"get_open_algo_orders failed: {result}")

    return result.get('orders', [])
```

---

### Step 2 — Ganti `_cancel_counter_order()` di `ws_user_stream.py`

```python
def _cancel_counter_order(self, order_id: str, symbol: str, reason: str) -> None:
    """
    Cancel counter-order (SL hit → cancel TP, TP hit → cancel SL).
    Strategi: fetch open algo orders by symbol, cancel yang tipe berlawanan.
    Tidak bergantung pada kecocokan ID — lebih robust dari cancel by algoId.
    """
    try:
        from src.utils.exchange import get_open_algo_orders, cancel_algo_order

        # SL hit → cancel TAKE_PROFIT_MARKET yang tersisa
        # TP hit → cancel STOP_MARKET yang tersisa
        cancel_type = 'TAKE_PROFIT_MARKET' if reason == 'SL' else 'STOP_MARKET'

        open_orders = get_open_algo_orders(symbol)

        if not open_orders:
            logger.debug(
                f"No open algo orders for {symbol} — counter-order already gone"
            )
            return

        cancelled = False
        for o in open_orders:
            order_type = o.get('type', o.get('algoType', ''))
            if order_type == cancel_type:
                algo_id = str(o.get('algoId', ''))
                if algo_id:
                    cancel_algo_order(algo_id, symbol)
                    logger.info(
                        f"Counter-order cancelled | algoId: {algo_id} | "
                        f"Type: {cancel_type} | Symbol: {symbol} | "
                        f"Reason: {reason} was hit"
                    )
                    cancelled = True
                    break

        if not cancelled:
            logger.debug(
                f"No {cancel_type} algo order found for {symbol} — already gone"
            )

    except Exception as e:
        logger.error(
            f"CRITICAL: Failed to cancel counter-order for {symbol}! "
            f"Manual cancel required in Binance dashboard. Error: {e}"
        )
```

---

## File yang Diubah

| File | Fungsi | Jenis Perubahan |
|------|--------|-----------------|
| `src/utils/exchange.py` | `get_open_algo_orders()` (baru) | Tambah fungsi ~25 baris |
| `src/data/ws_user_stream.py` | `_cancel_counter_order()` | Replace seluruh isi fungsi ~30 baris |

---

## Tindakan Manual Sebelum Fix

Sebelum apply fix, **manual cancel 3 orphan orders** yang masih ada
di Binance demo dashboard sekarang:
- SUIUSDT — Take Profit Market
- BTCUSDT — Stop Market
- SOLUSDT — Take Profit Market

Caranya: Binance demo → Orders → Open Orders → Conditional → Cancel

---

## Cara Verifikasi Setelah Fix

1. Apply fix, restart bot
2. Tunggu salah satu trade closed via SL atau TP
3. Cek log bot — cari:
   ```
   Counter-order cancelled | algoId: X | Type: TAKE_PROFIT_MARKET | Symbol: BTCUSDT
   ```
4. Cek Binance demo → Open Orders → Conditional — setelah trade closed,
   counter-order harus hilang dalam hitungan detik
5. Tidak boleh ada accumulation orphan orders lagi setelah beberapa hari
