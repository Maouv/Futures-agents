# Backtest

Read this when: working in `src/backtest/` or running strategy simulations.

## How It Works

```
CSV (H4 + H1) → BacktestEngine → Math Agent pipeline → simulate entry/exit → metrics
```

Flow per H1 candle:
1. `TrendAgent(H4)` → `TrendResult`
2. `ReversalAgent(H1)` → `ReversalResult`
3. If signal valid → entry with ATR-based SL/TP
4. Exit check via candle `high`/`low` — never `close`
5. `calculate_metrics()` → `BacktestMetrics`

Note: `ConfirmationAgent` is NOT run in backtest — 15m data is not loaded. Only H4 + H1.

## Key Constants

```python
RISK_PER_TRADE_USD = settings.RISK_PER_TRADE_USD   # fixed risk per trade
LEVERAGE           = settings.FUTURES_DEFAULT_LEVERAGE
RISK_REWARD_RATIO  = settings.RISK_REWARD_RATIO
ATR_SL_MULTIPLIER  = 1.0      # SL = OB edge ± (ATR × 0.5)
FEE_RATE           = 0.0005   # 0.05% taker fee per side
SLIPPAGE           = 0.001    # 0.1% slippage per side
MAX_HOLD_CANDLES   = 48       # max 2 days in H1 candles
```

## Hard Rules

- Exit check always uses candle `high`/`low` — never `close` (look-ahead bias)
- Position size uses fixed USD risk + leverage — not % of balance
- SL/TP is ATR-based — not flat percentage
- SKIPPED trades excluded from all metrics

## Metrics Output (`BacktestMetrics`)

```
total_trades, win_rate, profit_factor
avg_rr, max_drawdown_pct
total_pnl_usd, avg_trade_duration_candles
```

## CSV Format

H4 and H1 CSVs must have columns: `timestamp, open, high, low, close, volume`
`timestamp` must be UTC, parseable by `pd.to_datetime()`.

## Running a Backtest

```bash
source venv/bin/activate
python scripts/run_backtest.py --pair BTCUSDT --h4 data/BTCUSDT_H4.csv --h1 data/BTCUSDT_H1.csv
```

Output is printed to stdout. No DB writes — backtest is read-only.

