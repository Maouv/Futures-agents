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
  sltp_manager.py                → Paper mode SL/TP check (high/low candle)
src/agents/llm/
  analyst_agent.py               → Cerebras Qwen-3, rule-based fallback if API down → AnalystDecision
  commander_agent.py             → Groq Llama-3.1 — Telegram command parser
  concierge_agent.py             → Groq Llama-3.1 — chat mode, concurrency locked
src/indicators/
  _smc_core.py                   → Internal SMC logic (OB, FVG, BOS/CHOCH)
  luxalgo_smc.py                  → Public API: detect_order_blocks(), detect_fvg(), detect_bos_choch()
  mean_reversion.py               → RSI + Bollinger Bands
  helpers.py                      → ATR, Swing High/Low
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
  llm_rate_limiter.py             → Semaphore + sliding window rate limiter (Cerebras/Groq LLM)
  kill_switch.py                  → Emergency stop
  logger.py                       → Loguru setup
```

## Directory Structure (non-src)

- `data/historical/` → CSV OHLCV per pair×timeframe (backtest input)
- `data/rl_models/` → ONNX model + normalization params (VPS inference)
- `data/rl_training/` → Signal CSV per pair×year (Colab training input)
- `data/backtest_results/` → Backtest output
- `tests/` → Pytest unit tests (CI-ready)
- `scripts/` → Manual utility & test scripts (not for CI)
- `docs/` → PRD, implementation plan, specs
- `examples/` → RL environment demo
- `logs/` → Runtime logs (auto-generated)

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

1. Every 15 minutes (APScheduler, cron `0,15,30,45`), for each pair in `pairs.json`:
2. `fetch_ohlcv()` → H4, H1, 15m → gap check → session filter (London/NY only)
3. `TrendAgent(H4)` + `ReversalAgent(H1)` + `ConfirmationAgent(15m)` → raw signals
4. `AnalystAgent(LLM)` → LONG/SHORT/SKIP decision (rule-based fallback if API down)
5. [Optional] RL filter via ONNX inference
6. `RiskAgent` → SL/TP/size → `ExecutionAgent` → paper INSERT or live order
7. `sltp_manager` checks all open paper trades using high/low candle

## Conventions

- **Result model**: Each agent returns a Pydantic BaseModel (not dict). Naming pattern: `XxxResult`
- **Agent pattern**: All math agents extend `BaseAgent`, implement `run() → XxxResult`
- **Config**: `config.json` is single source of truth for all non-secret config. `settings.py` holds secrets from `.env` + `@property` delegates to `config_loader.py`. Access via `settings.XXX`
- **Exchange**: Always use `get_exchange()` from `src/utils/exchange.py`. Don't create `ccxt.binanceusdm()` directly
- **Exit check**: Use candle **high/low**, not close (avoid look-ahead bias)
- **SKIPPED trades**: Excluded from all metrics (win rate, profit factor, drawdown)
- **LLM fallback**: Bot MUST NOT crash when LLM is down. `analyst_agent.py` always has rule-based fallback
- **SL/TP live**: 2x Algo Order (`STOP_MARKET` + `TAKE_PROFIT_MARKET`). MUST use `place_algo_order()` from `exchange.py`
- **Model**: Use `openai` SDK + `base_url`
- **Position sizing**: Fixed USD (`RISK_PER_TRADE_USD`), not percentage of balance
- **DB session**: Always use `get_session()` context manager. No raw SQL
- **New files must go to the correct directory** — if the target directory doesn't exist, create it first. Examples: test files → `tests/`, utility scripts → `scripts/`, new agents → `src/agents/math/` or `src/agents/llm/`, indicators → `src/indicators/`, data output → `data/<appropriate_subdir>/`

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
- **Rate limiter**: Max 800 req/min (Binance). LLM rate limiting handled by `cerebras_limiter` in `llm_rate_limiter.py` (semaphore + RPM sliding window)
- **`onchain_fetcher.py`**: Placeholder, not implemented. Don't delete but don't use either
- **RL training**: ONLY on Google Colab (GPU T4). Don't install torch/gymnasium/SB3 on VPS — will OOM
- **Reconciliation symbol format**: `exchange.fetch_positions()` returns unified symbol `'BTC/USDT:USDT'`. Get raw symbol from `pos['info']['symbol']` (`'BTCUSDT'`), NOT from `pos['symbol']`
- **RiskAgent ValueError**: `RiskAgent.run()` can raise ValueError if risk distance is too small. MUST be try/excepted in caller — otherwise entire trading cycle crashes for all pairs
- **OB Midpoint Overlap**: If price has passed OB midpoint in the next cycle, `RiskAgent.run()` can raise `OverlapSkipError` (price outside OB zone → SKIP) or adjust entry to current_price (`entry_adjusted=True`). Live mode: adjusted entry uses market order + immediately places SL/TP, not limit + PENDING_ENTRY
- **SL/TP both hit**: If both SL and TP hit within the same candle, SL takes priority

## Config

**`.env`** (secrets only):

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `BINANCE_API_KEY/SECRET` | SecretStr | Live only | Production credentials |
| `BINANCE_TESTNET_KEY/SECRET` | SecretStr | Live only | Testnet credentials |
| `CEREBRAS_API_KEY` | SecretStr | Yes | Analyst Agent |
| `GROQ_API_KEY` | SecretStr | Yes | Commander + Concierge |
| `CONCIERGE_API_KEY` | SecretStr | No | Concierge (fallback to GROQ_API_KEY) |
| `TELEGRAM_BOT_TOKEN` | SecretStr | Yes | Bot token |

**`config.json`** (all non-secret config):

| Section | Key | Type | Default | Description |
|---------|-----|------|---------|-------------|
| `system` | `execution_mode` | str | `paper` | `paper` = sim DB, `live` = real orders |
| `system` | `use_testnet` | bool | `false` | `true` = Binance Testnet |
| `system` | `confirm_mainnet` | bool | `false` | Must be `true` when live+mainnet |
| `system` | `environment` | str | `production` | - |
| `system` | `telegram_chat_id` | str | `""` | Can be negative (group) |
| `system` | `binance_rest_url` | str | `https://fapi.binance.com` | - |
| `system` | `binance_ws_url` | str | `wss://fstream.binance.com/ws` | - |
| `system` | `binance_testnet_url` | str | `https://testnet.binancefuture.com` | - |
| `system` | `binance_testnet_ws_url` | str | `wss://stream.binancefuture.com/ws` | - |
| `trading` | `leverage` | int | `10` | Range 1-125 |
| `trading` | `margin_type` | str | `isolated` | `isolated` or `cross` |
| `trading` | `risk_per_trade_usd` | float | `10.0` | Fixed USD risk per trade |
| `trading` | `risk_reward_ratio` | float | `2.0` | Don't hardcode — read from settings |
| `trading` | `max_open_positions` | int | `1` | Per pair, not global |
| `trading` | `order_expiry_candles` | int | `48` | Limit order expires after N H1 candles |
| `trading` | `disable_session_filter` | bool | `true` | `true` = trade all hours |
| `llm.cerebras` | `base_url` | str | `https://api.cerebras.ai/v1/...` | - |
| `llm.cerebras` | `model` | str | `qwen-3-235b-...` | Analyst model |
| `llm.cerebras` | `max_concurrent` | int | `2` | Semaphore limit |
| `llm.cerebras` | `rpm` | int | `30` | Sliding window RPM |
| `llm.cerebras` | `retry_on_429` | int | `2` | Max retries on 429 |
| `llm.cerebras` | `timeout_sec` | int | `45` | Request timeout |
| `llm.groq` | `base_url` | str | `https://api.groq.com/...` | - |
| `llm.groq` | `model` | str | `llama-3.1-8b-instant` | Commander + Concierge model |
| `llm.groq` | `max_concurrent` | int | `3` | Semaphore limit |
| `llm.groq` | `rpm` | int | `30` | Sliding window RPM |
| `llm.groq` | `timeout_sec` | int | `45` | Request timeout |
| `llm.concierge` | `base_url` | str | `https://api.groq.com/...` | - |
| `llm.concierge` | `model` | str | `openai/gpt-oss-120b` | Concierge model |
| `llm.concierge` | `timeout_sec` | int | `600` | Concierge timeout |
| `llm.concierge` | `max_tokens` | int | `5000` | Max output tokens |
| `secrets` | `cerebras_api_key` | str | `${CEREBRAS_API_KEY}` | Resolved from .env |
| `secrets` | `groq_api_key` | str | `${GROQ_API_KEY}` | Resolved from .env |
| `secrets` | `concierge_api_key` | str | `${CONCIERGE_API_KEY}` | Resolved from .env |

## Module Dependencies

```
main.py → ohlcv_fetcher → exchange (singleton)
        → trend_agent → luxalgo_smc → _smc_core
        → reversal_agent → luxalgo_smc
        → confirmation_agent
        → analyst_agent → llm_rate_limiter (cerebras_limiter), trend/reversal/confirmation Result models
        → risk_agent → helpers (ATR), luxalgo_smc (OrderBlock)
        → execution_agent → exchange, storage (PaperTrade)
        → sltp_manager → storage
        → telegram_bot → commander_agent, concierge_agent
```

All agents depend on `base_agent.py`. All config accessed via `settings.py` (which delegates to `config_loader.py`). Exchange via singleton `get_exchange()`.

## Config: .env vs config.json

- **Secrets** (API keys, tokens) → `.env` only. Never commit real values
- **All other config** → `config.json` (sections: `pairs`, `system`, `trading`, `secrets`, `llm`)
- **Secret interpolation**: `config.json["secrets"]` uses `${ENV_VAR}` syntax resolved from `.env`
- **Config access**: `settings.XXX` still works — `@property` delegates to `config_loader.py`
- **Config caching**: `config_loader.py` caches config. Call `reload_config()` after editing `config.json`

## Environment & Execution Rules

- **Python environment**: MUST `source venv/bin/activate` before running any Python command (`python`, `pytest`, `pip`, etc). Never run without activating venv
- **Sequential execution**: Execute ALL tasks sequentially, one at a time. NEVER parallel — this model only supports 1 concurrent request. No parallel tool calls, no overlapping background tasks

## Anti-Patterns / Never Do

- **Don't create classes when functions suffice** — math agents use classes for ABC pattern, but utility/helper just need functions
- **Don't refactor working code** — if no bug report or feature request, leave it as is
- **Don't add new dependencies** without first checking if it already exists in requirements.txt or stdlib
- **Don't use `os.getenv()`** — always use `settings.XXX` or `settings.get_secret_value()`. Non-secret config comes from `config.json` via `config_loader.py`
- **Don't create `ccxt.binanceusdm()` directly** — always use `get_exchange()`
- **Don't write raw SQL** — always use SQLAlchemy via `get_session()`
- **Don't install torch/gymnasium/SB3 on VPS** — will OOM, training only on Colab
- **Don't upgrade ccxt** — newer versions block testnet for futures
- **Don't use `exchange.cancel_order()` for algo orders** — use `cancel_algo_order()` from `exchange.py`

## Maintenance Rule

- **ALWAYS update CLAUDE.md** when codebase changes affect architecture, gotchas, or conventions
- **CLAUDE.md max 300 lines** — if exceeding, compact by merging sections, removing verbose examples, or archiving stale content. Never remove critical gotchas or conventions
- **Verify file existence** before referencing — if architecture tree is stale, update it
