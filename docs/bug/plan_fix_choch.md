# Fix: CHoCH `broken_index` — BOS/CHOCH Window Check
> v2 — updated after premortem

## Problem
`BOSCHOCHSignal.index` menyimpan **formation candle** (swing point), bukan **confirmation candle**.
`reversal_agent` dan `confirmation_agent` pakai `sig.index >= len(df) - N` → CHoCH valid yang baru
terkonfirmasi tapi formasinya lama selalu di-skip.

## Root Cause
`_smc_core.bos_choch()` return DataFrame dengan kolom `BrokenIndex` (index candle konfirmasi).
Di `detect_bos_choch()` kolom ini **tidak diambil**. `BOSCHOCHSignal` model tidak punya field `broken_index`.

---

## ⚠️ Premortem Flags (wajib baca sebelum implement)

**FLAG 1 — `BrokenIndex` adalah `float64`, bukan `int`**
`_smc_core.py:366` → `np.where(broken != 0, broken, np.nan)` mengubah `int32` → `float64`.
`int(row["BrokenIndex"])` bisa crash jika ada NaN lolos dari filter.
**Wajib guard:**
```python
broken_raw = row["BrokenIndex"]
safe_broken_index = int(broken_raw) if (not np.isnan(broken_raw) and broken_raw > 0) else idx
```

**FLAG 2 — Window 20 H1 masih terlalu ketat**
CHoCH H1 rata-rata perlu 25–40 candle untuk konfirmasi. Naikkan ke **35**.

**FLAG 3 — Window 10 candle 15m di confirmation_agent juga terlalu ketat**
Konfirmasi 12 candle lalu (3 jam) tetap miss. Naikkan ke **20** (= 5 jam).

---

## Files to Read
```
src/indicators/luxalgo_smc.py         ← model BOSCHOCHSignal + fungsi detect_bos_choch
src/indicators/_smc_core.py           ← line 222–375, kolom BrokenIndex di return value
src/agents/math/reversal_agent.py     ← line 59–75, pengecekan recent_signal
src/agents/math/confirmation_agent.py ← line 57–70, pengecekan bos_alignment
```

---

## Changes

### 1. `src/indicators/luxalgo_smc.py`

**Tambah field ke `BOSCHOCHSignal`:**
```python
class BOSCHOCHSignal(BaseModel):
    index: int
    broken_index: int   # ← TAMBAH
    type: str
    bias: int
    level: float
```

**Di `detect_bos_choch()`, capture `BrokenIndex` dengan guard NaN:**
```python
broken_raw = row["BrokenIndex"]
safe_broken_index = int(broken_raw) if (not np.isnan(broken_raw) and broken_raw > 0) else idx

result.append(BOSCHOCHSignal(
    index=idx,
    broken_index=safe_broken_index,  # ← TAMBAH di kedua block (BOS dan CHOCH)
    type="BOS",  # atau "CHOCH"
    bias=int(bos_val),  # atau choch_val
    level=float(level_val)
))
```

### 2. `src/agents/math/reversal_agent.py`

```python
# SEBELUM:
if last.index >= len(df_h1) - 20:
# SESUDAH:
if last.broken_index >= len(df_h1) - 35:
```

### 3. `src/agents/math/confirmation_agent.py`

```python
# SEBELUM:
if sig.index >= len(df_15m) - 10:
# SESUDAH:
if sig.broken_index >= len(df_15m) - 20:
```

---

## Expected Outcome
CHoCH yang formasinya lama tapi baru dikonfirmasi dalam 35 candle H1 terakhir akan ter-detect.
Tidak ada crash dari float→int conversion karena guard dipasang di satu tempat (luxalgo_smc.py).

## No Breaking Changes
Field `index` (formation) tetap ada. Hanya tambah `broken_index`.

