# Trailing Stop + Liquidation Level — Design Spec

**Date:** 2026-04-16
**Status:** Approved, pending implementation

## Context

Bot saat ini memiliki SL/TP statis — dihitung sekali oleh `RiskAgent`, tidak pernah berubah. Trade yang sudah profit signifikan bisa reversal sampai kena SL awal, kehilangan semua unrealized profit. Selain itu, tidak ada info liquidation level — user tidak tahu seberapa dekat posisi ke likuidasi, berbahaya di leverage tinggi.

## Design Decisions

1. **Trailing stop**: Percentage-based, step-based, live/testnet only (paper mode tidak)
2. **Liquidation level**: Estimasi harga likuidasi (simplified formula), tampilkan di `/trades` dan notifikasi
3. **File baru `position_manager.py`** — terpisah dari `sltp_manager.py`. Kalau paper mode dihapus nanti, cleanup gampang

## Config Schema

Tambah di `config.json` → `trading` section:

```json
{
  "trading": {
    ...existing...,
    "trailing_stop": {
      "enabled": true,
      "steps": [
        {"profit_pct": 1.0, "new_sl_pct": 0.0},
        {"profit_pct": 2.0, "new_sl_pct": 0.5},
        {"profit_pct": 3.0, "new_sl_pct": 1.0}
      ]
    }
  }
}
```

### Config Field Meaning

| Field | Type | Description |
|-------|------|-------------|
| `trailing_stop.enabled` | bool | Master switch. False = no-op |
| `trailing_stop.steps` | list[dict] | Array of step definitions, must be ascending by `profit_pct` |
| `steps[].profit_pct` | float | Unrealized profit % threshold to activate this step |
| `steps[].new_sl_pct` | float | New SL position as % from entry (0 = breakeven, negative = below entry) |

### Step Example (LONG, entry=100, leverage=10x)

| Step | profit_pct | new_sl_pct | Trigger Price | New SL | Meaning |
|------|-----------|------------|---------------|--------|---------|
| 0    | -         | -          | -             | 95.00  | Original SL from RiskAgent |
| 1    | 1.0%      | 0.0%       | 101           | 100.00 | Breakeven |
| 2    | 2.0%      | 0.5%       | 102           | 100.50 | Lock 0.5% profit |
| 3    | 3.0%      | 1.0%       | 103           | 101.00 | Lock 1% profit |

## Files to Modify

### 1. `src/config/config_loader.py`
- Tambah `DEFAULT_TRAILING_STOP` constant:
  ```python
  DEFAULT_TRAILING_STOP = {
      "enabled": False,
      "steps": [
          {"profit_pct": 1.0, "new_sl_pct": 0.0},
          {"profit_pct": 2.0, "new_sl_pct": 0.5},
          {"profit_pct": 3.0, "new_sl_pct": 1.0},
      ],
  }
  ```
- Tambah `load_trailing_stop_config()` function — merge DEFAULT_TRAILING_STOP dengan config.json
- Atau merge langsung ke `load_trading_config()` return value

### 2. `src/config/settings.py`
- Tambah `@property` `TRAILING_STOP_ENABLED` → `load_trailing_stop_config().get('enabled', False)`
- Tambah `@property` `TRAILING_STOP_STEPS` → `load_trailing_stop_config().get('steps', [])`

### 3. `config.json`
- Tambah `"trailing_stop": {...}` di dalam section `"trading"`

### 4. `src/agents/math/position_manager.py` (FILE BARU)

```python
def calculate_liquidation_price(entry_price: float, side: str, leverage: int) -> float:
    """
    Estimasi harga likuidasi (isolated margin, simplified).
    LONG:  liq_price = entry * (1 - 1/leverage)
    SHORT: liq_price = entry * (1 + 1/leverage)
    """
```

```python
def check_trailing_stop(current_prices: Dict[str, Dict]) -> List[Dict]:
    """
    Cek semua OPEN live trades, apply trailing stop steps.
    Returns list of dicts: [{trade_id, pair, side, old_sl, new_sl, step_index}]
    """
```

**check_trailing_stop logic:**

1. Skip jika `TRAILING_STOP_ENABLED == False` atau `EXECUTION_MODE == "paper"`
2. Query `PaperTrade` where `status == 'OPEN'` and `execution_mode in ('live', 'testnet')`
3. Untuk tiap trade:
   a. Hitung unrealized profit %:
      - LONG: `(current_price - entry_price) / entry_price * 100`
      - SHORT: `(entry_price - current_price) / entry_price * 100`
   b. Cari step tertinggi yang tercapai (`profit_pct <= current_profit_pct`) DAN `step_index > trade.trailing_step`
   c. Hitung new SL:
      - LONG: `entry_price * (1 + new_sl_pct / 100)`
      - SHORT: `entry_price * (1 - new_sl_pct / 100)`
   d. Validate: new SL harus lebih baik dari current SL (LONG: lebih tinggi, SHORT: lebih rendah)
   e. Jika valid → update:
      - Cancel old SL: `cancel_algo_order(trade.sl_order_id, trade.pair)`
      - Place new SL: `place_algo_order(trade.pair, close_side, 'STOP_MARKET', new_sl, trade.size)`
      - Update DB: `sl_price`, `sl_order_id`, `trailing_step`
      - Return notification data

### 5. `src/data/storage.py` — PaperTrade model
Tambah columns:

```python
trailing_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
liq_price: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- `trailing_step`: 0 = belum trailing, N = step index terakhir yang di-apply
- `liq_price`: estimasi harga likuidasi, diisi saat trade dibuka

### 6. `src/agents/math/execution_agent.py`
- Di `_execute_live_market()` dan `_handle_fill()`:
  - Import `calculate_liquidation_price` dari `position_manager`
  - Hitung liq_price dan simpan ke `PaperTrade.liq_price`
- Di notifikasi trade opened: tambahkan `Liq: $X.XX`

### 7. `src/main.py`
- Tambah method `_run_trailing_stop_check(current_prices)`:
  ```python
  def _run_trailing_stop_check(self, current_prices: dict):
      from src.agents.math.position_manager import check_trailing_stop
      updated = check_trailing_stop(current_prices)
      for trade in updated:
          self.send_notification_sync(
              f"Trailing SL Updated\n"
              f"{trade['pair']} {trade['side']}\n"
              f"SL: ${trade['old_sl']:.2f} → ${trade['new_sl']:.2f}\n"
              f"Step: {trade['step_index']}"
          )
  ```
- Di `run_trading_cycle()`, setelah `_run_sltp_check()`, panggil `self._run_trailing_stop_check(current_prices)`

### 8. `src/telegram/commands.py`
- `cmd_get_open_trades()`: tambah `Liq: $X` dan `Step: N` di output per trade
- `cmd_get_status()`: tambah `Trailing stop: ON/OFF`

## Data Flow

```
main.py (15-min cycle)
  → fetch_ohlcv() → current_prices per pair
  → ...existing pipeline...
  → _run_sltp_check(current_prices)          # existing, paper only
  → _run_trailing_stop_check(current_prices) # NEW, live only
      → position_manager.check_trailing_stop()
          → for each OPEN live trade:
              → calc unrealized profit %
              → find highest matched step (step_index > trailing_step)
              → if new SL better than current:
                  → cancel_algo_order(old_sl)
                  → place_algo_order(new_sl)
                  → update DB (sl_price, sl_order_id, trailing_step)
                  → return notification data
```

## Edge Cases

| # | Case | Handling |
|---|------|----------|
| 1 | Step sudah di-apply, harga turun lalu naik lagi ke step yang sama | `trailing_step` column mencegah re-apply. Hanya step_index > trailing_step yang diproses |
| 2 | New SL worse than current SL | Skip — SL hanya bisa bergerak menguntungkan |
| 3 | `cancel_algo_order` gagal | Log error, jangan update DB. SL lama masih aktif di Binance |
| 4 | `place_algo_order` gagal setelah cancel berhasil | CRITICAL: posisi tanpa SL → emergency market close (sama seperti `_handle_fill`) |
| 5 | `trailing_stop.enabled = False` | `check_trailing_stop()` return empty list, no-op |
| 6 | SL dan trailing trigger di cycle yang sama | SL/TP check jalan dulu, bisa close trade. Trailing check di belakang, trade sudah CLOSED → skip |
| 7 | Trade tanpa `sl_order_id` (SL belum di-place) | Skip trade ini — jangan trailing kalau SL belum ada |

## Liquidation Price Formula

Simplified (tanpa Binance tier-based maintenance margin):

```
LONG:  liq_price = entry_price × (1 - 1/leverage)
SHORT: liq_price = entry_price × (1 + 1/leverage)
```

Contoh: LONG BTC entry=100,000, leverage=10x → liq = 100,000 × (1 - 0.1) = 90,000

Ini estimasi kasar. Binance maintenance margin rate bikin harga likuidasi aktual sedikit lebih dekat ke entry, tapi untuk awareness di Telegram ini cukup. Bisa di-refine nanti dengan Binance `/fapi/v1/leverageBracket` API.

## Verification

1. **Unit test** `position_manager.py`:
   - `calculate_liquidation_price()` — LONG/SHORT, berbagai leverage
   - `check_trailing_stop()` — mock DB + mock exchange, verifikasi step progression
2. **Config test** — verifikasi `trailing_stop` section di-load benar
3. **Integration** — manual testnet: buka trade, tunggu harga naik, verifikasi SL bergerak
4. **Telegram** — `/trades` menampilkan liq_price dan trailing step
