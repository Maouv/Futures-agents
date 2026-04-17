# Bug #011 — HIGH: Trailing Stop Config KeyError

**File**: `src/agents/math/position_manager.py:70,110`
**Impact**: Kalau `TRAILING_STOP_STEPS` di `config.json` ada dict yang kurang key `profit_pct` atau `new_sl_pct` → `KeyError` crash saat trailing stop check. Seluruh trading cycle crash untuk semua pair.

**Repro**: Edit `config.json`, ubah salah satu step jadi `{"profit_pct": 0.02}` (tanpa `new_sl_pct`). Jalankan bot → crash.

**Fix approach**: Validasi `TRAILING_STOP_STEPS` saat load config (di `config_loader.py` atau di awal `position_manager.py`). Pastikan setiap step punya `profit_pct` dan `new_sl_pct`. Kalau invalid → log warning + skip trailing stop, jangan crash.
