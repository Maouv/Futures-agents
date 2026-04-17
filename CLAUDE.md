# Futures Agents

Multi-agent crypto futures trading bot running 24/7 on a VPS. Trades Binance USD-M Futures via ccxt. Pipeline: Math Agents (pure Python) → LLM Analyst (Cerebras) → optional RL filter (ONNX).

**Language**: Use English for all communication and explanations. Indonesian only when explicitly requested.

---

## Architecture

```
src/main.py                      → Orchestrator — 15-min APScheduler cycle + Telegram
src/config/
  settings.py                    → Pydantic Settings — secrets from .env + @property delegates to config_loader
  config_loader.py                → Load all config from config.json (pairs, system, trading, llm, secrets)
src/data/
  storage.py                     → SQLAlchemy models (OHLCV + PaperTrade) + session factory
  ohlcv_fetcher.py               → REST API fetcher + gap detector + session filter
  ws_user_stream.py              → User Data WebSocket (live mode only, order updates)
src/agents/math/                 → Pure Python — NO LLM calls allowed here
  base_agent.py                  → BaseAgent ABC — all agents inherit from this
  trend_agent.py                 → H4 BOS/CHOCH → TrendResult
  reversal_agent.py              → H1 SMC (OB+FVG) → ReversalResult
  confirmation_agent.py          → 15m validation → ConfirmationResult
  risk_agent.py                  → ATR SL/TP + fixed USD sizing → RiskResult
  execution_agent.py             → Paper: INSERT DB | Live: Limit + Algo SL/TP → ExecutionResult
  position_manager.py            → Trailing stop (live only) + liquidation price estimation
  sltp_manager.py                → Paper mode SL/TP check (high/low candle)
src/agents/llm/
  analyst_agent.py               → Cerebras Qwen-3, rule-based fallback if API down → AnalystDecision
  commander_agent.py             → Groq Llama-3.1 — Telegram command parser
  concierge_agent.py             → Groq Llama-3.1 — chat mode, concurrency locked
src/indicators/
  _smc_core.py                   → Internal SMC logic (OB, FVG, BOS/CHOCH)
  luxalgo_smc.py                  → Public API: detect_order_blocks(), detect_fvg(), detect_bos_choch()
  mean_reversion.py               → RSI + Bollinger Bands
  helpers.py                      → ATR, Swing High-Low
src/rl/                           → RL filter — training on Colab, ONNX inference on VPS
  environment.py                  → TradingEnvironment, 13 features, SKIP/ENTRY
  dqn_agent.py                    → DQN + Thompson Sampling, ONNX export
  inference.py                    → ONNX Runtime inference (VPS)
  trainer.py                      → Multi-pair training — COLAB ONLY
src/telegram/
  bot.py                          → Router: Command→Commander, Chat→Concierge
src/backtest/
  engine.py                       → CSV → Math Agents → entry/exit simulation
  metrics.py                      → calculate_metrics() — SKIPPED excluded
src/utils/
  exchange.py                     → Singleton ccxt factory + algo order helpers (place_algo_order, cancel_algo_order)
  rate_limiter.py                 → Sliding window 800 req/min (Binance)
  llm_rate_limiter.py             → Semaphore + sliding window + min_interval rate limiter (Cerebras/Groq LLM)
  kill_switch.py                  → Emergency stop
  logger.py                       → Loguru setup

data/historical/    → CSV OHLCV per pair×timeframe (backtest input)
data/rl_models/     → ONNX model + normalization params (VPS inference)
data/rl_training/   → Signal CSV per pair×year (Colab training input)
data/backtest_results/ → Backtest output
tests/              → Pytest unit tests (CI-ready)
scripts/            → Manual utility & test scripts (not for CI)
docs/               → PRD, implementation plan, specs
examples/           → RL environment demo
logs/               → Runtime logs (auto-generated)
```

## Result Models (Pydantic)

Each agent must return these models — do not invent extra fields:

```python
TrendResult:       bias: int (-1/0/1), bias_label: str, confidence: float, reason: str
ReversalResult:    signal: str (LONG/SHORT/NONE), confidence: int, ob, fvg, bos_choch, entry_price, reason
ConfirmationResult: confirmed: bool, reason: str, fvg_confluence: bool, bos_alignment: bool
RiskResult:        entry_price, sl_price, tp_price, position_size, risk_usd, reward_usd, rr_ratio, leverage, margin_required, entry_adjusted
ExecutionResult:   action: str (OPEN/SKIP/PENDING), reason: str, trade_id: Optional[int]
AnalystDecision:   action: str (LONG/SHORT/SKIP), confidence: int, reasoning: str, source: str (llm/rule_based)
```

## Algo Order Flow (exchange.py)

```
PLACE:  place_algo_order(symbol, side, order_type, trigger_price, qty)
        → POST /fapi/v1/algoOrder, algoType=CONDITIONAL, param=triggerPrice (NOT stopPrice)
        → returns dict with key 'algoId' (NOT 'orderId')

CANCEL: cancel_algo_order(algoId, symbol)
        → DELETE /fapi/v1/algoOrder
        → NOT exchange.cancel_order() — old endpoint cannot cancel algo orders

WS TRIGGER: ORDER_TRADE_UPDATE.i = orderId NEW (not algoId)
        → Fallback match: find by symbol + side if algoId doesn't match
```

## How It Works

1. Every 15 minutes (APScheduler, cron `0,15,30,45`), for each pair in `config.json`:
2. `fetch_ohlcv()` → H4, H1, 15m → gap check → session filter (London/NY only)
3. `TrendAgent(H4)` + `ReversalAgent(H1)` + `ConfirmationAgent(15m)` → raw signals
4. `AnalystAgent(LLM)` → LONG/SHORT/SKIP decision (rule-based fallback if API down)
5. [Optional] RL filter via ONNX inference
6. `RiskAgent` → SL/TP/size → `ExecutionAgent` → paper INSERT or live order
7. `sltp_manager` checks all open paper trades using high/low candle
8. `position_manager` checks trailing stop for all open live trades (cancel old SL → place new SL)

## Conventions

- **Result model**: Each agent returns a Pydantic BaseModel (not dict). Naming pattern: `XxxResult`
- **Agent pattern**: All math agents extend `BaseAgent`, implement `run() → XxxResult`
- **Config**: `config.json` is single source of truth for all non-secret config (sections: `pairs`, `system`, `trading`, `llm`, `secrets`). Secrets via `.env` + `${ENV_VAR}` interpolation. Access via `settings.XXX` (delegates to `config_loader.py`). Call `reload_config()` after editing `config.json`
- **Key config keys** (non-obvious): `confirm_mainnet` (must be `true` when live+mainnet), `disable_session_filter` (`true` = trade all hours), `order_expiry_candles` (limit order expires after N H1 candles)
- **Exchange**: Always use `get_exchange()` from `src/utils/exchange.py`. Don't create `ccxt.binanceusdm()` directly
- **Exit check**: Use candle **high/low**, not close (avoid look-ahead bias)
- **SKIPPED trades**: Excluded from all metrics (win rate, profit factor, drawdown)
- **LLM fallback**: Bot MUST NOT crash when LLM is down. `analyst_agent.py` always has rule-based fallback
- **SL/TP live**: 2x Algo Order (`STOP_MARKET` + `TAKE_PROFIT_MARKET`). MUST use `place_algo_order()` from `exchange.py`
- **Model**: Use `openai` SDK + `base_url`
- **Position sizing**: Fixed USD (`RISK_PER_TRADE_USD`), not percentage of balance
- **DB session**: Always use `get_session()` context manager. No raw SQL
- **New files must go to the correct directory** — if the target directory doesn't exist, create it first
- **Don't refactor working code** — if no bug report or feature request, leave it as is
- **Don't add new dependencies** without first checking if it already exists in requirements.txt or stdlib
- **Don't install torch/gymnasium/SB3 on VPS** — will OOM, training only on Colab
- **Don't upgrade ccxt** — newer versions block testnet for futures

## Non-Obvious Dependencies

```
analyst_agent → llm_rate_limiter (cerebras_limiter)
risk_agent → luxalgo_smc (OrderBlock)
position_manager → exchange (cancel_algo_order, place_algo_order)
```

## How to Add a New Feature

1. Add config in `config.json` (system/trading/llm sections) + secrets in `.env`
2. If new agent: create file in `src/agents/math/`, extend `BaseAgent`, return Pydantic model
3. Register agent in pipeline `src/main.py::TradingBot.run_trading_cycle()`
4. If new indicator: create in `src/indicators/`, call from agent (not from LLM)
5. Add pair: edit `config.json` in project root, restart bot
6. Update this section if architecture changes

## Gotcha / Known Issues

- **Exchange singleton**: After network error, call `reset_exchange()` — singleton stores stale state
- **SQLite WAL**: Enabled via PRAGMA. Don't switch to DELETE mode — can corrupt under concurrent read/write
- **DetachedInstanceError**: Accessing PaperTrade attributes outside session scope will crash. Fetch all needed values before session close
- **Mode switch**: If changing `EXECUTION_MODE` without restart, exchange instance still uses old config. MUST restart
- **`current_price` undefined**: In some paths, `current_price` is not assigned before use. Always ensure a fallback exists
- **Binance error codes**:
  | Code | Cause | Handling |
  |------|-------|----------|
  | -4137 | Stop already triggered (buy price above trigger) | Skip order |
  | -4120 | Using `/fapi/v1/order` for algo order | Use `/fapi/v1/algoOrder` |
- **Order status `closed`**: Binance can return `closed` besides `filled`. Both = executed
- **Naive datetime in SQLite**: `PaperTrade.entry_timestamp` from DB has no timezone. Must `.replace(tzinfo=timezone.utc)` before subtracting `datetime.now(timezone.utc)`
- **ccxt version**: Use `4.2.86`. Do NOT upgrade — newer versions block testnet for futures. Algo API called manually via `requests`
- **Rate limiter**: Max 800 req/min (Binance). LLM rate limiting handled by `cerebras_limiter` in `llm_rate_limiter.py` (semaphore + RPM sliding window + min_interval to prevent burst 429s)
- **`onchain_fetcher.py`**: Placeholder, not implemented. Don't delete but don't use either
- **RL training**: ONLY on Google Colab (GPU T4). Don't install torch/gymnasium/SB3 on VPS — will OOM
- **Reconciliation symbol format**: `exchange.fetch_positions()` returns unified symbol `'BTC/USDT:USDT'`. Get raw symbol from `pos['info']['symbol']` (`'BTCUSDT'`), NOT from `pos['symbol']`
- **RiskAgent ValueError**: `RiskAgent.run()` can raise ValueError if risk distance is too small. MUST be try/excepted in caller — otherwise entire trading cycle crashes for all pairs
- **OB Midpoint Overlap**: If price has passed OB midpoint in the next cycle, `RiskAgent.run()` can raise `OverlapSkipError` (price outside OB zone → SKIP) or adjust entry to current_price (`entry_adjusted=True`). Live mode: adjusted entry uses market order + immediately places SL/TP, not limit + PENDING_ENTRY
- **SL/TP both hit**: If both SL and TP hit within the same candle, SL takes priority
- **Trailing stop**: Live/testnet only. Paper mode skips. `position_manager.py` handles cancel+place SL algo. If new SL fails after cancel → emergency market close
- **Liquidation price**: Simplified formula (`entry * (1 ∓ 1/leverage)`). Not tier-based — close enough for Telegram awareness
- **trailing_step column**: Prevents re-applying same step. Default `-1` (never trailed), `0+` = last applied step index. Only `step_index > trade.trailing_step` is processed

## Environment & Execution Rules

- **Python environment**: MUST `source venv/bin/activate` before running any Python command (`python`, `pytest`, `pip`, etc). Never run without activating venv
- **Sequential execution**: Execute ALL tasks sequentially, one at a time. NEVER parallel — this model only supports 1 concurrent request. No parallel tool calls, no overlapping background tasks

## Maintenance Rule

- **ALWAYS update CLAUDE.md** when codebase changes affect architecture, gotchas, or conventions
- **CLAUDE.md max 300 lines** — if exceeding, compact by merging sections, removing verbose examples, or archiving stale content. Never remove critical gotchas or conventions
- **Verify file existence** before referencing — if architecture tree is stale, update it

<!-- RTK: See ~/.claude/RTK.md for RTK commands. Always prefix with `rtk`. -->
