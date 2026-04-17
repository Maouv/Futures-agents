# Bug #009 — HIGH: Bare `except: pass` di _cleanup_mode_trades

**File**: `src/telegram/commands.py:57,60,67`
**Impact**: Saat mode switch, cancel_algo_order gagal (auth error, network, dll) tapi di-silent. Algo orders tetap aktif di Binance setelah switch ke mode lain → unexpected triggers.

**Repro**: Mode switch dari live ke paper. Kalau `cancel_algo_order` gagal karena error selain "order not found", error diabaikan total.

**Fix approach**: Ganti `except: pass` dengan catch spesifik:
```python
except Exception as e:
    if "Unknown order" not in str(e) and "order not found" not in str(e):
        logger.warning(f"Failed to cancel algo {trade.sl_order_id}: {e}")
```
Hanya suppress "order not found" (benar-benar sudah tidak ada), log sisanya.
