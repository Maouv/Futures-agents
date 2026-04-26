# Fix Plan #001 — CRITICAL: Reconcile Membunuh PENDING_ENTRY yang Valid

**Severity:** CRITICAL
**Confidence:** 100
**Estimasi waktu fix:** 30–45 menit

---

## Apa Masalahnya

Setiap kali bot restart, semua limit order yang masih menunggu fill
di-mark `RECONCILED` dan dihapus dari DB — padahal order-nya masih
hidup di Binance dan belum fill. Ini penyebab utama hampir semua
trade di history berstatus RECONCILED.

---

## Lokasi Bug

**File:** `src/main.py`
**Fungsi:** `_reconcile_positions()`
**Baris kritis:** ~398–410

---

## Kenapa Bisa Terjadi

Fungsi `_reconcile_positions()` mengambil semua trade dengan status
`OPEN` **dan** `PENDING_ENTRY` dari DB, lalu mengeceknya semua
menggunakan `fetch_positions()`:

```python
# KONDISI YANG SALAH — PENDING_ENTRY ikut difilter
open_trades = db.query(PaperTrade).filter(
    PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
    PaperTrade.execution_mode.in_(['testnet', 'mainnet']),
).all()

for trade in open_trades:
    if trade.pair not in active_pairs:   # active_pairs dari fetch_positions()
        close_trade(trade, 'RECONCILED', ...)
```

`fetch_positions()` hanya mengembalikan posisi yang **sudah fill dan
aktif** (posisi dengan amount > 0). Limit order yang belum fill
(`PENDING_ENTRY`) tidak akan pernah muncul di sana — bukan karena
hilang, tapi karena memang endpoint yang berbeda.

Hasilnya: bot melihat trade `PENDING_ENTRY` di DB, cek Binance
positions, tidak ketemu, lalu anggap orphan dan close sebagai
RECONCILED. Padahal limit order-nya masih hidup di Binance.

---

## Cara Fix

Pisahkan logika pengecekan menjadi dua jalur berbeda:

- **`OPEN`** → tetap gunakan `fetch_positions()` ✓
- **`PENDING_ENTRY`** → gunakan `fetch_open_orders()` untuk cek apakah
  limit order masih ada di Binance

```python
def _reconcile_positions(self) -> None:
    from src.utils.exchange import get_exchange
    exchange = get_exchange()

    try:
        # ── 1. Fetch active positions (untuk cek OPEN trades) ──────────
        positions = exchange.fetch_positions()
        active_pairs = set()
        for pos in positions:
            amt = float(pos.get('contracts', pos.get('positionAmt', 0)))
            if abs(amt) > 0:
                symbol = pos.get('info', {}).get('symbol', '')
                if not symbol:
                    unified = pos.get('symbol', '')
                    if '/' in unified:
                        symbol = unified.split(':')[0].replace('/', '')
                    else:
                        symbol = unified
                active_pairs.add(symbol)

        # ── 2. Fetch open limit orders (untuk cek PENDING_ENTRY trades) ─
        open_orders = exchange.fetch_open_orders()
        active_order_ids = {str(o.get('id', '')) for o in open_orders if o.get('id')}

        with get_session() as db:
            open_trades = db.query(PaperTrade).filter(
                PaperTrade.status.in_(['OPEN', 'PENDING_ENTRY']),
                PaperTrade.execution_mode.in_(['testnet', 'mainnet']),
            ).all()

            for trade in open_trades:

                if trade.status == 'OPEN':
                    # Cek via fetch_positions() — posisi aktif
                    if trade.pair not in active_pairs:
                        close_price = self._get_close_price_for_trade(trade, exchange)
                        pnl = (
                            calculate_pnl(trade.side, trade.entry_price, close_price, trade.size)
                            if close_price else None
                        )
                        close_trade(trade, 'RECONCILED', close_price=close_price, pnl=pnl)
                        logger.warning(f"Reconciled OPEN: Trade {trade.id} ({trade.pair})")

                elif trade.status == 'PENDING_ENTRY':
                    # Cek via fetch_open_orders() — limit orders belum fill
                    order_id = trade.exchange_order_id

                    if not order_id:
                        # Tidak ada order_id → orphan pasti
                        close_trade(trade, 'RECONCILED', close_price=None, pnl=None)
                        logger.warning(
                            f"Reconciled PENDING_ENTRY: Trade {trade.id} ({trade.pair}) "
                            f"— no exchange_order_id in DB"
                        )

                    elif order_id not in active_order_ids:
                        # Order tidak ada di open orders — mungkin sudah fill atau cancelled
                        try:
                            ccxt_symbol = self._pair_to_ccxt_symbol(trade.pair)
                            order = exchange.fetch_order(order_id, ccxt_symbol)
                            order_status = order.get('status', '')
                            if order_status in ('filled', 'closed'):
                                # Sudah fill tapi DB belum update
                                # Biarkan — check_pending_orders() akan handle di cycle berikutnya
                                logger.info(
                                    f"PENDING_ENTRY Trade {trade.id} ({trade.pair}) "
                                    f"order filled — will be handled next cycle"
                                )
                            else:
                                # Cancelled/expired di luar bot
                                close_trade(trade, 'RECONCILED', close_price=None, pnl=None)
                                logger.warning(
                                    f"Reconciled PENDING_ENTRY: Trade {trade.id} ({trade.pair}) "
                                    f"order status={order_status}"
                                )
                        except Exception as e:
                            # Tidak bisa verifikasi — biarkan daripada salah reconcile
                            logger.warning(
                                f"Cannot verify PENDING_ENTRY Trade {trade.id} "
                                f"order {order_id}: {e} — leaving as PENDING_ENTRY"
                            )
                    else:
                        # Order masih ada di Binance — valid, biarkan
                        logger.info(
                            f"PENDING_ENTRY Trade {trade.id} ({trade.pair}) "
                            f"order {order_id} still open — OK"
                        )

    except Exception as e:
        logger.error(f"Position reconciliation failed: {e}")
        logger.warning("Proceeding without reconciliation — monitor manually!")
```

---

## File yang Diubah

| File | Fungsi | Jenis Perubahan |
|------|--------|-----------------|
| `src/main.py` | `_reconcile_positions()` | Replace seluruh isi fungsi |

Tidak ada file lain yang perlu diubah. Tidak ada dependency baru.

---

## Cara Verifikasi Setelah Fix

1. Apply fix, restart bot
2. Buka log bot, cari baris:
   ```
   PENDING_ENTRY Trade X (XRPUSDT) order Y still open — OK
   ```
3. Kalau baris itu muncul dan trade tidak di-RECONCILED → fix berhasil
4. Cek `/history testnet` di Telegram — history baru tidak boleh semua RECONCILED
