# Math Agents & Indicators

Read this when: working in `src/agents/math/` or `src/indicators/`.

## Hard Rules

- Math agents must never make LLM calls — zero exceptions
- Indicators must never be called from LLM agents — only from math agents
- New indicators go in `src/indicators/`, called from math agent, not directly from `main.py`

## Pipeline Position

```
TrendAgent(H4)         → ReversalAgent(H1) → ConfirmationAgent(15m)
→ RiskAgent → ExecutionAgent → SLTPManager / PositionManager
```

OrderMonitor runs before the per-pair loop (live mode only).

## SL/TP Check Rule

Always compare against candle `high`/`low` — never `close`. Using close is look-ahead bias:
```python
# Correct
if candle["high"] >= trade.tp_price:
    # TP hit

# Wrong — look-ahead bias
if candle["close"] >= trade.tp_price:
    # TP hit
```

## RiskAgent Exceptions

`RiskAgent.run()` can raise two exceptions — always catch in caller:

```python
try:
    risk = RiskAgent().run(...)
except OverlapSkipError:
    # Price outside OB zone → SKIP, not a crash
    pass
except ValueError:
    # Risk distance too small → SKIP
    pass
```

If not caught, entire trading cycle crashes for all pairs.

## SMC Indicators

Public API lives in `src/indicators/luxalgo_smc.py`:
- `detect_order_blocks(df)` → list of `OrderBlock`
- `detect_fvg(df)` → list of FVG zones
- `detect_bos_choch(df, swing_length)` → list of BOS/CHOCH signals

Internal logic in `src/indicators/_smc_core.py` — do not modify, do not import directly.

## Trailing Stop

Live/testnet only — paper mode skips entirely.
`position_manager.py` handles: cancel existing SL algo → place new SL algo.
If new SL fails after cancel → emergency market close to prevent unprotected exposure.
`trailing_step` column prevents re-applying the same step — only process `step_index > trade.trailing_step`.

