# Fix: OB Entry 4-State Logic
> v2 — updated after premortem (critical bug fix pada state mapping)

## Problem
Entry sekarang hanya di OB midpoint (limit). Tidak ada handling:
- Harga belum masuk OB → tidak ada limit yang dipasang lebih awal
- Harga baru masuk OB (sebelum midpoint) → jatuh ke overlap error
- reversal_agent hanya deteksi OB kalau harga sudah overlap → hampir selalu NONE

---

## ⚠️ Premortem Flags (wajib baca sebelum implement)

**FLAG 1 — CRITICAL: State mapping LONG/SHORT di v1 plan terbalik**
Untuk LONG, bullish OB ada *di bawah* current price (price harus retrace turun).
- `price > ob.high` = State 1 (belum masuk, normal) → **BUKAN State 4**
- `price < ob.low` = State 4 (OB invalidated) → **ini yang harus skip**
Plan v1 membalik ini: akan skip semua State 1 dan masuk di State 4. Tabel di bawah adalah yang benar.

**FLAG 2 — `calculate_atr` tidak diimport di reversal_agent**
Proximity filter akan crash dengan `NameError`. Wajib tambah:
`from src.indicators.helpers import calculate_atr`

**FLAG 3 — Paper mode tidak punya State 1 pending simulation**
`_execute_paper()` selalu langsung `status='OPEN'`. State 1 di paper mode harus insert
`status='PENDING_ENTRY'` dan di-monitor oleh `sltp_manager` atau handler tersendiri.
Tanpa ini: paper trade masuk di harga salah → statistik kotor.
**Scope untuk implementasi ini: paper mode State 1 insert sebagai PENDING_ENTRY,
monitor fill ketika `current_price <= entry_price` (LONG) / `>= entry_price` (SHORT) di cycle berikutnya.**

**FLAG 4 — Proximity filter 3x ATR terlalu longgar di BTC volatile**
ATR BTC H1 bisa 200–400 USD → 3x ATR = 600–1200 USD. Bot pilih OB jauh, order tidak pernah fill, expired tiap cycle.
Gunakan **2x ATR**. Tambahkan log: `f"OB distance: {distance:.1f} (ATR: {atr:.1f}, max: {max_distance:.1f})"`.

**FLAG 5 — State 1 entry di ob.high menghasilkan risk distance lebih besar**
Entry di ob.high (bukan midpoint) → risk = `(ob.high - ob.low) + ATR` → lebih besar.
Dengan RR 1.0 yang ada, edge makin tipis. **Setelah implementasi berjalan, naikkan RR ke 1.5.**

---

## State Mapping yang Benar

### LONG (Bullish OB — ada DI BAWAH current price, nunggu retrace turun)

| State | Kondisi | Action |
|-------|---------|--------|
| 1 — Belum masuk | `price > ob.high` | Limit di `ob.high` (OB top edge) |
| 2 — Dalam OB, sebelum midpoint | `ob.midpoint <= price <= ob.high` | Limit di `current_price` |
| 3 — Lewat midpoint, masih dalam OB | `ob.low < price < ob.midpoint` | Market di `current_price`, `entry_adjusted=True` |
| 4 — Keluar bawah (invalidated) | `price < ob.low` | `OverlapSkipError` → SKIP |

### SHORT (Bearish OB — ada DI ATAS current price, nunggu retrace naik)

| State | Kondisi | Action |
|-------|---------|--------|
| 1 — Belum masuk | `price < ob.low` | Limit di `ob.low` (OB bottom edge) |
| 2 — Dalam OB, sebelum midpoint | `ob.low <= price <= ob.midpoint` | Limit di `current_price` |
| 3 — Lewat midpoint, masih dalam OB | `ob.midpoint < price < ob.high` | Market di `current_price`, `entry_adjusted=True` |
| 4 — Keluar atas (invalidated) | `price > ob.high` | `OverlapSkipError` → SKIP |

---

## Files to Read
```
src/agents/math/risk_agent.py          ← full file — logika overlap + OverlapSkipError
src/agents/math/reversal_agent.py      ← OB selection loop (nearest_bull_ob / nearest_bear_ob)
src/agents/math/execution_agent.py     ← _execute_paper, _execute_live_limit, entry_adjusted flag
src/agents/math/sltp_manager.py        ← untuk memahami bagaimana paper trade di-monitor (perlu extend untuk State 1 paper pending)
src/indicators/helpers.py              ← calculate_atr signature
src/main.py                            ← line 110–145, cara RiskAgent dipanggil
```

---

## Changes Required

### 1. `src/agents/math/reversal_agent.py`

**Tambah import:**
```python
from src.indicators.helpers import calculate_atr
```

**Ganti OB selection loop** — jangan syaratkan price sudah overlap, cari OB terdekat yang relevan:
```python
atr = calculate_atr(df_h1).iloc[-1]
max_distance = atr * 2  # FLAG 4: gunakan 2x, bukan 3x

for ob in result.order_blocks:
    if ob.mitigated:
        continue

    if ob.bias == 1:  # Bullish OB: harus di bawah current_price
        if current_price > ob.low:  # OB ada di bawah (atau price baru masuk)
            distance = max(0, current_price - ob.high)  # 0 jika sudah dalam OB
            if distance <= max_distance:
                if nearest_bull_ob is None or ob.high > nearest_bull_ob.high:
                    nearest_bull_ob = ob
                    self._log(f"Bull OB candidate: {ob.low:.2f}-{ob.high:.2f} | distance: {distance:.1f} | ATR: {atr:.1f}")

    elif ob.bias == -1:  # Bearish OB: harus di atas current_price
        if current_price < ob.high:  # OB ada di atas (atau price baru masuk)
            distance = max(0, ob.low - current_price)  # 0 jika sudah dalam OB
            if distance <= max_distance:
                if nearest_bear_ob is None or ob.low < nearest_bear_ob.low:
                    nearest_bear_ob = ob
                    self._log(f"Bear OB candidate: {ob.low:.2f}-{ob.high:.2f} | distance: {distance:.1f} | ATR: {atr:.1f}")
```

### 2. `src/agents/math/risk_agent.py`

**Ganti seluruh overlap check block** dengan 4-state logic:

```python
entry_price = ob_midpoint  # default
entry_adjusted = False

if current_price is not None:
    if signal == "LONG":
        if current_price < ob_low:
            # State 4: price tembus bawah OB — invalidated
            raise OverlapSkipError(
                f"LONG: price {current_price:.2f} di bawah OB low {ob_low:.2f} — OB invalidated"
            )
        elif current_price >= ob_midpoint:
            # State 1 (price > ob_high) atau State 2 (ob_midpoint <= price <= ob_high)
            # Limit di ob_high — first touch point saat retrace
            entry_price = ob_high
            entry_adjusted = False
            self._log(f"OB State 1/2 LONG: limit di ob.high {ob_high:.2f}")
        else:
            # State 3: ob_low < price < ob_midpoint — sudah lewat midpoint, masih dalam OB
            entry_price = current_price
            entry_adjusted = True
            self._log(f"OB State 3 LONG: market di current_price {current_price:.2f}")

    elif signal == "SHORT":
        if current_price > ob_high:
            # State 4: price tembus atas OB — invalidated
            raise OverlapSkipError(
                f"SHORT: price {current_price:.2f} di atas OB high {ob_high:.2f} — OB invalidated"
            )
        elif current_price <= ob_midpoint:
            # State 1 (price < ob_low) atau State 2 (ob_low <= price <= ob_midpoint)
            # Limit di ob_low — first touch point saat retrace naik
            entry_price = ob_low
            entry_adjusted = False
            self._log(f"OB State 1/2 SHORT: limit di ob.low {ob_low:.2f}")
        else:
            # State 3: ob_midpoint < price < ob_high — sudah lewat midpoint, masih dalam OB
            entry_price = current_price
            entry_adjusted = True
            self._log(f"OB State 3 SHORT: market di current_price {current_price:.2f}")
```

### 3. `src/agents/math/execution_agent.py` + `sltp_manager.py`

**Paper mode State 1/2** (entry_adjusted=False) harus masuk sebagai `PENDING_ENTRY`, bukan langsung OPEN.

Di `_execute_paper()`:
```python
# Jika entry_adjusted=False → limit order, masuk PENDING_ENTRY
# Jika entry_adjusted=True  → market order, langsung OPEN (existing behavior)
if not risk_result.entry_adjusted:
    status = 'PENDING_ENTRY'
else:
    status = 'OPEN'
```

Di `sltp_manager.py` (atau tambah `check_paper_pending()`):
Monitor `PENDING_ENTRY` paper trades — fill ketika:
- LONG: `current_price <= trade.entry_price`
- SHORT: `current_price >= trade.entry_price`
Jika fill: update `status='OPEN'`. Jika `ORDER_EXPIRY_CANDLES` tercapai: update `status='EXPIRED'`.

---

## SL Calculation — Tidak Berubah
SL selalu dari OB boundary, bukan dari entry:
- LONG: `sl = ob.low - (atr * 1.0)`
- SHORT: `sl = ob.high + (atr * 1.0)`

---

## Post-Implementation
Setelah implementasi berjalan dan trade mulai masuk:
- Monitor fill rate State 1 vs State 3 di log
- Jika State 1 fill rate rendah (order sering expired), turunkan `max_distance` ke 1.5x ATR
- **Naikkan `risk_reward_ratio` ke 1.5** — State 1 entry di edge OB punya risk distance lebih besar dari midpoint

