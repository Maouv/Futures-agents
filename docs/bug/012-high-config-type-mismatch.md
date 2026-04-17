# Bug #012 — HIGH: Config Type Mismatch (String vs Number)

**File**: `src/config/settings.py` (multiple properties, e.g. `RISK_PER_TRADE_USD`)
**Impact**: Kalau user masukin `"risk_per_trade_usd": "100"` (string bukan number) di `config.json`, property return string. Saat dipakai di arithmetic (position sizing, margin calculation) → `TypeError` crash. Sulit di-debug karena error muncul jauh dari sumbernya.

**Repro**: Edit `config.json`, set `"risk_per_trade_usd": "10"` sebagai string. Jalankan bot → `TypeError` saat hitung position size.

**Fix approach**: Tambah type coercion di `config_loader.py` atau di settings properties. Contoh: `float(config['risk_per_trade_usd'])`. Atau validasi schema penuh dengan Pydantic saat load config di startup — reject config invalid sebelum bot jalan.
