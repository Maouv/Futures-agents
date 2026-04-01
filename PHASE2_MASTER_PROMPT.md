# 🤖 PHASE 2 MASTER PROMPT — Porting Indikator & Validasi
# Untuk: Claude Code (claude-code CLI)
# Prasyarat: Phase 0 dan Phase 1 sudah SELESAI dan semua test PASS

---

## BRIEFING PHASE 2

Phase ini adalah **BLOCKING phase** — jangan lanjut ke Phase 2.5 atau Phase 3 sebelum
validasi manual selesai dan akurat. Kesalahan di sini akan menyebar ke seluruh sistem.

Tujuan utama: menerjemahkan logika PineScript LuxAlgo SMC ke Python murni dengan
akurasi matematis identik (toleransi selisih maks `0.0001`).

**File referensi wajib dibaca sebelum mulai:**
- `luxAlgo-pineScript.txt` — source PineScript asli
- `CLAUDE.md` section 7 (Porting Indikator)
- `IMPLEMENTATION_PLAN.md` Phase 2

---

## ⚠️ ATURAN KRITIS PHASE 2 (Baca & Hafal)

1. **DILARANG menggunakan LLM untuk menghitung indikator** — murni Python (`pandas`/`numpy`)
2. **DILARANG menggunakan `ta` atau `pandas-ta`** untuk SMC — harus port manual dari PineScript
3. **BOLEH menggunakan `ta` atau `pandas-ta`** hanya untuk RSI dan Bollinger Bands (`mean_reversion.py`)
4. **Semua fungsi wajib return Pydantic Model** — bukan `dict` mentah
5. **Prioritaskan keterbacaan** — jangan optimasi dulu, validasi dulu

---

## 🔑 PANDUAN KONVERSI PINESCRIPT → PYTHON

Ini bagian paling kritis. PineScript dan Python punya perbedaan fundamental yang sering
menyebabkan bug halus.

### Perbedaan #1: Indexing Array (PALING SERING SALAH)

```pinescript
// PineScript — index [0] = candle SEKARANG, [1] = candle SEBELUMNYA
high[0]  // high candle ini
high[1]  // high candle 1 bar lalu
high[2]  // high candle 2 bar lalu
```

```python
# Python pandas — iloc[-1] = baris TERAKHIR (candle sekarang)
df['high'].iloc[-1]   # high candle ini
df['high'].iloc[-2]   # high candle 1 bar lalu
df['high'].iloc[-3]   # high candle 2 bar lalu

# Atau dengan shift (lebih aman untuk operasi vectorized):
df['high'].shift(1)   # kolom berisi high[1] untuk setiap baris
df['high'].shift(2)   # kolom berisi high[2] untuk setiap baris
```

**Aturan konversi:**
```
PineScript high[N]  →  Python df['high'].shift(N)  (untuk operasi kolom)
PineScript high[N]  →  Python df['high'].iloc[-(N+1)]  (untuk akses baris tunggal)
```

### Perbedaan #2: `ta.highest()` dan `ta.lowest()`

```pinescript
// PineScript
ta.highest(high, 5)  // Nilai high tertinggi dalam 5 bar terakhir
ta.lowest(low, 5)    // Nilai low terendah dalam 5 bar terakhir
```

```python
# Python — rolling window
df['high'].rolling(5).max()   # Equivalent ta.highest(high, 5)
df['low'].rolling(5).min()    # Equivalent ta.lowest(low, 5)
```

### Perbedaan #3: `ta.crossover()` dan `ta.crossunder()`

```pinescript
// PineScript
ta.crossover(close, level)   // True jika close baru saja naik melewati level
ta.crossunder(close, level)  // True jika close baru saja turun melewati level
```

```python
# Python — deteksi crossover manual
def crossover(series: pd.Series, level: float) -> pd.Series:
    """True pada baris dimana series baru saja naik melewati level."""
    prev_below = series.shift(1) <= level
    curr_above = series > level
    return prev_below & curr_above

def crossunder(series: pd.Series, level: float) -> pd.Series:
    """True pada baris dimana series baru saja turun melewati level."""
    prev_above = series.shift(1) >= level
    curr_below = series < level
    return prev_above & curr_below
```

### Perbedaan #4: `ta.change()` dan `ta.atr()`

```pinescript
ta.change(value)     // value - value[1]
ta.atr(length)       // Average True Range
```

```python
# Python
df['value'].diff(1)                    # Equivalent ta.change()
df['high'] - df['low']                 # True Range sederhana
# ATR — pakai pandas-ta atau manual:
import pandas_ta as pta
df.ta.atr(length=14)                   # Pakai pandas-ta
# Atau manual:
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low'] - df['close'].shift(1)).abs()
], axis=1).max(axis=1)
atr = tr.ewm(span=length, adjust=False).mean()
```

### Perbedaan #5: `var` keyword di PineScript

```pinescript
// PineScript — var = nilai persisten, tidak reset setiap bar
var float lastHigh = na
if condition
    lastHigh := high
```

```python
# Python — tidak ada equivalent langsung
# Gunakan iterrows() atau cumulative logic:
last_high = None
results = []
for idx, row in df.iterrows():
    if condition(row):
        last_high = row['high']
    results.append(last_high)
df['last_high'] = results
```

---

## 📋 TASK LIST PHASE 2

### Task 2.1 — `src/indicators/helpers.py`

Implementasi fungsi-fungsi utility yang dipakai oleh semua indikator lain.

```python
"""
helpers.py — Fungsi utility untuk kalkulasi indikator.
Semua fungsi WAJIB pure Python/pandas — DILARANG pakai LLM.
"""
from typing import Optional
import pandas as pd
import numpy as np


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Hitung Average True Range.
    Gunakan EMA (Wilder's smoothing) bukan SMA — sama dengan TradingView default.
    """
    ...

def find_swing_highs(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """
    Identifikasi swing high points.
    Swing high = candle dimana high-nya lebih tinggi dari `lookback` candle di kiri dan kanan.
    Return: pd.Series of bool
    """
    ...

def find_swing_lows(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """
    Identifikasi swing low points.
    """
    ...

def crossover(series: pd.Series, level: pd.Series | float) -> pd.Series:
    """True pada bar dimana series naik melewati level."""
    ...

def crossunder(series: pd.Series, level: pd.Series | float) -> pd.Series:
    """True pada bar dimana series turun melewati level."""
    ...
```

### Task 2.2 — `src/indicators/luxalgo_smc.py`

**SCOPE TERBATAS — hanya 3 fungsi ini. Tidak lebih.**

#### Pydantic Output Models (wajib dibuat di awal file)

```python
from pydantic import BaseModel
from typing import Optional
import pandas as pd

class OrderBlock(BaseModel):
    index: int              # Index baris di DataFrame
    high: float
    low: float
    bias: int               # 1 = BULLISH, -1 = BEARISH
    mitigated: bool = False # True jika sudah ditembus harga

class FairValueGap(BaseModel):
    index: int              # Index baris di DataFrame
    top: float
    bottom: float
    bias: int               # 1 = BULLISH, -1 = BEARISH
    filled: bool = False    # True jika sudah terisi harga

class BOSCHOCHSignal(BaseModel):
    index: int
    type: str               # 'BOS' atau 'CHOCH'
    bias: int               # 1 = BULLISH, -1 = BEARISH
    level: float            # Level harga yang ditembus

class SMCResult(BaseModel):
    order_blocks: list[OrderBlock]
    fair_value_gaps: list[FairValueGap]
    bos_choch_signals: list[BOSCHOCHSignal]
    current_bias: int       # Bias trend saat ini: 1, -1, atau 0
```

#### Fungsi yang Harus Diimplementasi

**Fungsi 1: `detect_order_blocks(df)`**

Referensi PineScript: fungsi `storeOrderBlock()` dan `deleteOrderBlocks()` di `luxAlgo-pineScript.txt`.

Logika inti:
```
1. Identifikasi swing highs dan swing lows (pakai helpers.find_swing_highs/lows)
2. Untuk setiap swing high baru (bearish leg):
   - Cari candle dengan parsedHigh tertinggi antara swing sebelumnya dan sekarang
   - Itu adalah Bearish Order Block (barHigh, barLow dari candle tersebut)
3. Untuk setiap swing low baru (bullish leg):
   - Cari candle dengan parsedLow terendah antara swing sebelumnya dan sekarang
   - Itu adalah Bullish Order Block
4. Tandai OB sebagai 'mitigated' jika:
   - Bearish OB: close > ob.high (harga naik menembus OB bearish)
   - Bullish OB: close < ob.low (harga turun menembus OB bullish)
```

**Catatan penting dari PineScript:**
```pinescript
// parsedHigh dan parsedLow di PineScript difilter berdasarkan volatilitas:
atrMeasure = ta.atr(200)
highVolatilityBar = (high - low) >= (2 * atrMeasure)
parsedHigh = highVolatilityBar ? low : high   // Jika bar volatile, pakai low sebagai parsedHigh
parsedLow  = highVolatilityBar ? high : low   // Jika bar volatile, pakai high sebagai parsedLow
```
Ini WAJIB diimplementasi — tanpa ini OB detection akan berbeda dari TradingView.

**Fungsi 2: `detect_fvg(df)`**

Fair Value Gap = celah antara candle[2].high dan candle[0].low (bullish) atau candle[2].low dan candle[0].high (bearish).

```
Bullish FVG: candle[-1].low > candle[-3].high  (ada gap di atas candle 2 bars lalu)
Bearish FVG: candle[-1].high < candle[-3].low  (ada gap di bawah candle 2 bars lalu)

FVG dianggap 'filled' jika harga masuk ke dalam gap tersebut.
```

**Fungsi 3: `detect_bos_choch(df)`**

Referensi PineScript: fungsi `displayStructure()` di `luxAlgo-pineScript.txt`.

```
BOS (Break of Structure):
  - Bullish BOS: close crossover swingHigh.currentLevel DAN trend sebelumnya BULLISH
  - Bearish BOS: close crossunder swingLow.currentLevel DAN trend sebelumnya BEARISH

CHOCH (Change of Character):
  - Bullish CHOCH: close crossover swingHigh.currentLevel DAN trend sebelumnya BEARISH
  - Bearish CHOCH: close crossunder swingLow.currentLevel DAN trend sebelumnya BULLISH

Perbedaan BOS vs CHOCH: apakah breakout SEARAH atau BERLAWANAN dengan trend sebelumnya.
```

### Task 2.3 — `src/indicators/mean_reversion.py`

Untuk file ini, **BOLEH menggunakan `pandas-ta`** — tidak perlu port manual.

```python
"""
mean_reversion.py — RSI dan Bollinger Bands.
Boleh menggunakan pandas-ta untuk kalkulasi.
"""
from pydantic import BaseModel
import pandas as pd
import pandas_ta as pta


class MeanReversionResult(BaseModel):
    rsi: float                  # 0-100
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_position: float          # -1.0 (bawah lower) sampai +1.0 (atas upper), 0 = middle
    rsi_signal: str             # 'OVERSOLD', 'OVERBOUGHT', 'NEUTRAL'


def calculate_mean_reversion(df: pd.DataFrame) -> MeanReversionResult:
    """
    Hitung RSI(14) dan Bollinger Bands(20, 2.0).
    Parameter default ini WAJIB sama dengan TradingView default.
    """
    ...
```

### Task 2.4 — Validasi Manual vs TradingView

**Ini adalah gate check — WAJIB LULUS sebelum lanjut ke Phase 2.5.**

#### Langkah-langkah validasi:

**Step 1: Ambil data dari TradingView**
```
1. Buka TradingView → chart BTCUSDT Futures (BINANCE:BTCUSDT.P)
2. Timeframe: 1H
3. Tambahkan indicator: LuxAlgo Smart Money Concepts
4. Export 100 baris terakhir: klik kanan chart → Download CSV
   (atau pakai Pine Script export jika tersedia)
5. Catat nilai OB, FVG, BOS/CHOCH yang terlihat di chart
```

**Step 2: Jalankan Python terhadap data yang sama**
```bash
python scripts/validate_indicators.py --symbol BTCUSDT --timeframe 1h --bars 100
```

Buat script `scripts/validate_indicators.py`:
```python
"""
validate_indicators.py — Bandingkan output Python vs TradingView manual.
Jalankan ini dan bandingkan hasilnya dengan chart TradingView secara visual.
"""
import pandas as pd
from src.data.ohlcv_fetcher import fetch_and_store_ohlcv
from src.indicators.luxalgo_smc import detect_order_blocks, detect_fvg, detect_bos_choch
from src.indicators.mean_reversion import calculate_mean_reversion
from src.utils.logger import logger


def validate(symbol: str = "BTCUSDT", timeframe: str = "1h", bars: int = 100):
    df = fetch_and_store_ohlcv(symbol, timeframe)
    if df is None:
        logger.error("Failed to fetch data")
        return
    
    df = df.tail(bars)
    
    # Print hasil untuk dibandingkan manual dengan TradingView
    from src.indicators.luxalgo_smc import detect_order_blocks
    obs = detect_order_blocks(df)
    
    logger.info(f"=== ORDER BLOCKS (last {bars} candles) ===")
    for ob in obs[-5:]:  # Print 5 OB terakhir
        logger.info(f"  {'BULLISH' if ob.bias == 1 else 'BEARISH'} OB | "
                   f"High: {ob.high:.2f} | Low: {ob.low:.2f} | "
                   f"Mitigated: {ob.mitigated}")
    
    # Bandingkan nilai ini dengan apa yang lu lihat di TradingView
    # Toleransi: selisih < 0.0001 untuk setiap nilai

if __name__ == "__main__":
    validate()
```

**Step 3: Kriteria LULUS**
```
✅ LULUS jika:
   - Posisi OB (high/low) selisih < 0.0001 dari TradingView
   - Jumlah FVG yang terdeteksi sama dengan TradingView
   - BOS/CHOCH muncul di candle yang sama dengan TradingView

❌ GAGAL jika:
   - Ada OB yang muncul di Python tapi tidak ada di TradingView (atau sebaliknya)
   - Selisih nilai > 0.0001
   - BOS/CHOCH off by 1 candle atau lebih

Jika GAGAL → cek indexing (perbedaan #1 di atas paling sering jadi penyebab)
```

---

## 🧪 Unit Tests Phase 2

Buat `tests/test_indicators.py`:

```python
"""
test_indicators.py — Unit tests untuk indikator SMC dan Mean Reversion.
Semua test menggunakan data dummy yang sudah diketahui hasilnya.
"""
import pytest
import pandas as pd
import numpy as np
from src.indicators.helpers import crossover, crossunder, calculate_atr
from src.indicators.mean_reversion import calculate_mean_reversion


class TestHelpers:
    def test_crossover_detects_correctly(self):
        """Series naik melewati level 50 pada index ke-3."""
        series = pd.Series([45.0, 48.0, 49.0, 51.0, 53.0])
        result = crossover(series, 50.0)
        assert result.iloc[3] is True
        assert result.iloc[4] is False  # Sudah di atas, bukan crossover lagi

    def test_crossunder_detects_correctly(self):
        series = pd.Series([55.0, 52.0, 51.0, 49.0, 47.0])
        result = crossunder(series, 50.0)
        assert result.iloc[3] is True
        assert result.iloc[4] is False

    def test_atr_positive(self):
        """ATR harus selalu positif."""
        df = pd.DataFrame({
            'high':  [100, 102, 101, 103, 105],
            'low':   [98,  99,  99,  100, 102],
            'close': [99,  101, 100, 102, 104],
        })
        atr = calculate_atr(df, period=3)
        assert (atr.dropna() > 0).all()


class TestMeanReversion:
    def _make_df(self, n: int = 50) -> pd.DataFrame:
        """Buat DataFrame dummy dengan trend naik."""
        close = pd.Series(range(100, 100 + n), dtype=float)
        return pd.DataFrame({
            'high':  close + 1,
            'low':   close - 1,
            'close': close,
            'open':  close - 0.5,
            'volume': [1000.0] * n,
        })

    def test_rsi_range(self):
        """RSI harus selalu antara 0 dan 100."""
        df = self._make_df(50)
        result = calculate_mean_reversion(df)
        assert 0 <= result.rsi <= 100

    def test_bb_position_range(self):
        """bb_position harus antara -1 dan +1 (approximasi)."""
        df = self._make_df(50)
        result = calculate_mean_reversion(df)
        assert -2.0 <= result.bb_position <= 2.0  # Bisa keluar band saat trending kuat
```

---

## ✅ CHECKLIST SEBELUM LANJUT KE PHASE 2.5

- [ ] `src/indicators/helpers.py` — semua fungsi terimplementasi dan tests PASS
- [ ] `src/indicators/luxalgo_smc.py` — 3 fungsi: OB, FVG, BOS/CHOCH
- [ ] `src/indicators/mean_reversion.py` — RSI + Bollinger Bands
- [ ] `tests/test_indicators.py` — semua tests PASS (`pytest tests/ -v`)
- [ ] `scripts/validate_indicators.py` — sudah dijalankan dan dibandingkan manual vs TradingView
- [ ] Validasi manual LULUS (selisih < 0.0001)
- [ ] Tidak ada import `openai`, `groq`, atau library LLM di folder `indicators/`

**Semua checklist hijau → lanjut ke Phase 2.5 (Backtest Engine)**

---

## PREVIEW PHASE 2.5 (Jangan Kerjakan Sekarang)

Setelah Phase 2 selesai, Phase 2.5 akan:
1. Download data historis dari `https://data.binance.vision` (gratis, tanpa API key)
   - Format URL: `https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/15m/BTCUSDT-15m-YYYY-MM.zip`
2. Load ke DB yang sudah ada
3. Jalankan backtest engine menggunakan indikator Phase 2
4. Gate check: win rate ≥ 45%, profit factor ≥ 1.2, max drawdown ≤ 30%
5. Jika lulus → data ini juga jadi dataset untuk training RL di Colab

---
*Generated by Claude — Phase 2 Master Prompt*
*Versi: 1.0 | Tanggal: 2026-04*

