# 🤖 PHASE 3 MASTER PROMPT — Math Agents
# Untuk: Claude Code
# Prasyarat: Phase 0, 1, 2 selesai. Data historis ada di data/historical/

---

## BRIEFING PHASE 3

Membangun 7 Math Agent Python murni. Tidak ada LLM di phase ini.
Semua agent menerima data dari DB dan mengembalikan Pydantic Model.

**WAJIB BACA SEBELUM MULAI:**
- `CLAUDE.md` — terutama section 5 (pemisahan Math vs LLM)
- `IMPLEMENTATION_PLAN.md` — Phase 3 dan Strategy Specification
- `src/indicators/luxalgo_smc.py` — output models yang sudah ada
- `src/config/settings.py` — semua config dibaca dari sini

**RULE UTAMA:** DILARANG import `openai`, `groq`, `cerebras`, atau library LLM apapun di folder `src/agents/math/`.

---

## 🎯 STRATEGY SPECIFICATION (LOCKED — JANGAN DIUBAH)

Entry hanya valid jika semua kondisi terpenuhi:

```
LONG entry:
1. H4 trend = BULLISH
2. Ada Bullish OB aktif di bawah harga sekarang
3. Entry price = OB midpoint (ob.high + ob.low) / 2
4. FVG bullish unfilled sebagai confluence (opsional tapi boosts confidence)
5. BOS atau CHOCH bullish di H1 sebagai konfirmasi

SHORT entry:
1. H4 trend = BEARISH
2. Ada Bearish OB aktif di atas harga sekarang
3. Entry price = OB midpoint (ob.high + ob.low) / 2
4. FVG bearish unfilled sebagai confluence (opsional)
5. BOS atau CHOCH bearish di H1 sebagai konfirmasi

Risk Management (semua dari settings — DILARANG hardcode):
- Risk per trade  : settings.RISK_PER_TRADE_USD (default $10)
- Risk/Reward     : settings.RISK_REWARD_RATIO (default 2.0)
- SL Bullish      : ob.low - (ATR * 0.5)
- SL Bearish      : ob.high + (ATR * 0.5)
- TP              : entry + (entry - SL) * RR
- Leverage        : settings.FUTURES_DEFAULT_LEVERAGE (default 10)
- Position size   : (Risk USD * leverage) / abs(entry - SL)
```

---

## 📦 TASK LIST PHASE 3

### Sebelum mulai — tambah 2 field ke Settings

Di `src/config/settings.py`, tambahkan:
```python
# ── Trading Strategy Params ──────────────────────────────────────────────────
RISK_PER_TRADE_USD: float = Field(default=10.0, description="Risk per trade dalam USD")
RISK_REWARD_RATIO: float = Field(default=2.0, description="Risk:Reward ratio (2 = 1:2)")
```

Di `.env.example`, tambahkan:
```
RISK_PER_TRADE_USD=10.0
RISK_REWARD_RATIO=2.0
```

---

### Task 3.1 — `src/agents/math/base_agent.py`

```python
"""
base_agent.py — Abstract base class untuk semua Math Agents.
"""
from abc import ABC, abstractmethod
from typing import Any
import pandas as pd
from pydantic import BaseModel
from src.utils.logger import logger


class BaseAgent(ABC):
    """Base class untuk semua Math Agents."""

    @abstractmethod
    def run(self, *args, **kwargs) -> BaseModel:
        """Jalankan agent dan return Pydantic Model."""
        pass

    def _log(self, message: str) -> None:
        logger.info(f"[{self.__class__.__name__}] {message}")

    def _log_error(self, message: str) -> None:
        logger.error(f"[{self.__class__.__name__}] {message}")
```

---

### Task 3.2 — `src/agents/math/trend_agent.py`

**Input:** DataFrame H4 (dari DB)
**Output:** `TrendResult`

```python
from pydantic import BaseModel

class TrendResult(BaseModel):
    bias: int           # 1=BULLISH, -1=BEARISH, 0=RANGING
    bias_label: str     # 'BULLISH', 'BEARISH', 'RANGING'
    confidence: float   # 0.0 - 1.0
    reason: str         # Penjelasan singkat
```

**Logika trend H4:**
```
Gunakan BOS/CHOCH dari luxalgo_smc.detect_bos_choch(df_h4, swing_size=10)
- Jika sinyal terakhir = BULLISH (BOS atau CHOCH bullish) → BULLISH
- Jika sinyal terakhir = BEARISH → BEARISH
- Jika tidak ada sinyal dalam 10 candle terakhir → RANGING
- Confidence: jumlah sinyal searah / total sinyal dalam 20 candle terakhir
```

---

### Task 3.3 — `src/agents/math/reversal_agent.py`

**Input:** DataFrame H1
**Output:** `ReversalResult`

```python
class ReversalResult(BaseModel):
    signal: str         # 'LONG', 'SHORT', 'NONE'
    confidence: int     # 0-100
    ob: OrderBlock | None       # OB yang relevan
    fvg: FairValueGap | None    # FVG terdekat (confluence)
    bos_choch: BOSCHOCHSignal | None  # Signal terbaru
    entry_price: float | None   # OB midpoint jika ada signal
    reason: str
```

**Logika:**
```python
# 1. Detect semua SMC di H1
result = detect_all(df_h1, swing_size=5)

# 2. Cari OB aktif terdekat dengan harga sekarang
current_price = df_h1['close'].iloc[-1]

nearest_bull_ob = None  # OB bullish aktif terdekat di BAWAH harga
nearest_bear_ob = None  # OB bearish aktif terdekat di ATAS harga

for ob in result.order_blocks:
    if not ob.mitigated:
        if ob.bias == 1 and ob.high < current_price:
            if nearest_bull_ob is None or ob.high > nearest_bull_ob.high:
                nearest_bull_ob = ob
        if ob.bias == -1 and ob.low > current_price:
            if nearest_bear_ob is None or ob.low < nearest_bear_ob.low:
                nearest_bear_ob = ob

# 3. Cek BOS/CHOCH terbaru (dalam 5 candle terakhir)
recent_signal = None
if result.bos_choch_signals:
    last = result.bos_choch_signals[-1]
    if last.index >= len(df_h1) - 5:
        recent_signal = last

# 4. Tentukan sinyal
# LONG: ada bullish OB + ada bullish BOS/CHOCH terbaru
# SHORT: ada bearish OB + ada bearish BOS/CHOCH terbaru
```

---

### Task 3.4 — `src/agents/math/confirmation_agent.py`

**Input:** DataFrame 15m, signal dari ReversalAgent
**Output:** `ConfirmationResult`

```python
class ConfirmationResult(BaseModel):
    confirmed: bool
    reason: str
    fvg_confluence: bool    # Ada FVG 15m yang mendukung arah?
    bos_alignment: bool     # BOS 15m searah dengan signal H1?
```

**Logika:**
```
Jalankan detect_all(df_15m, swing_size=5)
Cek apakah BOS/CHOCH terbaru di 15m searah dengan signal H1
Cek apakah ada FVG unfilled di 15m yang mendukung arah
confirmed = True jika minimal 1 dari 2 kondisi terpenuhi
```

---

### Task 3.5 — `src/agents/math/risk_agent.py`

**Input:** ReversalResult, current_price, df untuk ATR
**Output:** `RiskResult`

```python
class RiskResult(BaseModel):
    entry_price: float
    sl_price: float
    tp_price: float
    position_size: float    # Dalam kontrak/qty
    risk_usd: float         # Actual risk dalam USD
    reward_usd: float       # Potential reward dalam USD
    rr_ratio: float         # Actual RR
    leverage: int
    margin_required: float  # Modal yang dibutuhkan
```

**Logika (WAJIB baca dari settings — DILARANG hardcode):**
```python
from src.config.settings import settings

atr = calculate_atr(df, period=14).iloc[-1]

if signal == 'LONG':
    sl = ob.low - (atr * 0.5)
    entry = (ob.high + ob.low) / 2  # OB midpoint
else:
    sl = ob.high + (atr * 0.5)
    entry = (ob.high + ob.low) / 2

risk_distance = abs(entry - sl)
tp = entry + (risk_distance * settings.RISK_REWARD_RATIO) * (1 if signal == 'LONG' else -1)

# Position size: berapa kontrak yang bisa dibeli dengan risk $10
position_size = (settings.RISK_PER_TRADE_USD * settings.FUTURES_DEFAULT_LEVERAGE) / risk_distance
margin_required = (position_size * entry) / settings.FUTURES_DEFAULT_LEVERAGE
```

---

### Task 3.6 — `src/agents/math/execution_agent.py`

**PAPER MODE ONLY — DILARANG ada `exchange.create_order` di sini.**

**Input:** RiskResult, ReversalResult, TrendResult
**Output:** `ExecutionResult`

```python
class ExecutionResult(BaseModel):
    action: str         # 'OPEN', 'SKIP'
    reason: str
    trade_id: int | None  # ID dari paper_trades jika OPEN
```

**Logika:**
```python
import os
from src.data.storage import PaperTrade, get_session

# GUARD CLAUSE WAJIB ADA
if os.getenv("EXECUTION_MODE") == "live":
    # Phase 8 — belum diimplementasi
    raise NotImplementedError("Live execution diimplementasi di Phase 8")

# Paper mode: INSERT ke DB
with get_session() as db:
    trade = PaperTrade(
        pair=symbol,
        side=signal,  # 'LONG' atau 'SHORT'
        entry_price=risk_result.entry_price,
        sl_price=risk_result.sl_price,
        tp_price=risk_result.tp_price,
        size=risk_result.position_size,
        leverage=risk_result.leverage,
        status='OPEN',
    )
    db.add(trade)
    db.flush()
    trade_id = trade.id
```

---

### Task 3.7 — `src/agents/math/sltp_manager.py`

**Dijalankan setiap siklus 15 menit untuk cek paper trades.**

```python
"""
sltp_manager.py — Cek SL/TP untuk paper trades yang masih OPEN.
HANYA untuk paper mode. Di live mode, SL/TP sudah diserahkan ke Binance server.
"""

def check_paper_trades(current_prices: dict[str, float]) -> list[dict]:
    """
    Cek semua paper trade OPEN terhadap harga close 15m terbaru.
    current_prices = {'BTCUSDT': 67500.0, ...}
    
    Return list of closed trades dengan reason 'TP' atau 'SL'.
    """
    closed = []
    
    with get_session() as db:
        open_trades = db.query(PaperTrade).filter(
            PaperTrade.status == 'OPEN'
        ).all()
        
        for trade in open_trades:
            price = current_prices.get(trade.pair)
            if price is None:
                continue
            
            hit_tp = False
            hit_sl = False
            
            if trade.side == 'LONG':
                hit_tp = price >= trade.tp_price
                hit_sl = price <= trade.sl_price
            else:  # SHORT
                hit_tp = price <= trade.tp_price
                hit_sl = price >= trade.sl_price
            
            if hit_tp or hit_sl:
                close_reason = 'TP' if hit_tp else 'SL'
                close_price = trade.tp_price if hit_tp else trade.sl_price
                
                # Hitung PnL
                if trade.side == 'LONG':
                    pnl = (close_price - trade.entry_price) * trade.size
                else:
                    pnl = (trade.entry_price - close_price) * trade.size
                
                trade.status = 'CLOSED'
                trade.pnl = pnl
                trade.close_reason = close_reason
                trade.close_timestamp = datetime.utcnow()
                
                closed.append({
                    'trade_id': trade.id,
                    'pair': trade.pair,
                    'side': trade.side,
                    'pnl': pnl,
                    'reason': close_reason,
                })
    
    return closed
```

---

## ✅ CHECKLIST PHASE 3

- [ ] `settings.py` — tambah `RISK_PER_TRADE_USD` dan `RISK_REWARD_RATIO`
- [ ] `base_agent.py` — abstract base class
- [ ] `trend_agent.py` — output `TrendResult`, pakai H4 BOS/CHOCH
- [ ] `reversal_agent.py` — output `ReversalResult`, cari OB + FVG + BOS/CHOCH H1
- [ ] `confirmation_agent.py` — output `ConfirmationResult`, validasi di 15m
- [ ] `risk_agent.py` — output `RiskResult`, SL/TP/size dari settings
- [ ] `execution_agent.py` — INSERT ke paper_trades, GUARD CLAUSE wajib ada
- [ ] `sltp_manager.py` — cek SL/TP paper trades setiap siklus
- [ ] Tidak ada hardcoded numbers (leverage, risk, RR) — semua dari settings
- [ ] Tidak ada import LLM library di folder `math/`
- [ ] Buat test sederhana: `python -c "from src.agents.math.trend_agent import TrendAgent; print('OK')"`

**Semua checklist hijau → lanjut Phase 4.**

---
*Phase 3 Master Prompt — Versi 1.0*

