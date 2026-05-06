# Futures Agents

Multi-agent crypto futures trading bot. Trades USD-M Futures via ccxt(for now only support binance). Pipeline: Math Agents (pure Python) → LLM Analyst → Execution.

> **Detail per domain lives in `.claude/agents/` — load the relevant sub-agent before working on a specific area.**

---

## Pipeline (15-min APScheduler cycle)

```
0. OrderMonitor.check_pending_orders()  → live mode only, runs BEFORE per-pair loop
                                          FILLED  → place SL + TP via algo order, update DB to OPEN
                                          EXPIRED → cancel order on Binance, update DB to EXPIRED
1. fetch_ohlcv()          → H4, H1, 15m per pair → gap check → session filter
2. TrendAgent(H4)         → BOS/CHOCH → TrendResult
3. ReversalAgent(H1)      → SMC (OB+FVG) → ReversalResult
4. ConfirmationAgent(15m) → validate signal → ConfirmationResult
5. AnalystAgent(LLM)      → provider chain → LONG/SHORT/SKIP → AnalystDecision
6. RiskAgent              → ATR SL/TP + fixed USD sizing → RiskResult
7. ExecutionAgent         → paper INSERT or live algo order → ExecutionResult
8. SLTPManager            → check open paper trades via candle high/low (not close)
   PositionManager        → trailing stop for live trades (cancel old SL → place new)
```

---

## Architecture

```
src/main.py                     → Orchestrator + APScheduler + Telegram runner
src/config/
  settings.py                   → Pydantic Settings — secrets from .env only
  config_loader.py              → All non-secret config from config.json
src/data/
  storage.py                    → SQLAlchemy models (OHLCVCandle, PaperTrade) + session factory
  ohlcv_fetcher.py              → REST fetcher + gap detector + session filter
  ws_user_stream.py             → User Data WebSocket (live mode only)
src/agents/math/                → Pure Python — NO LLM calls allowed here
  base_agent.py / trend_agent.py / reversal_agent.py / confirmation_agent.py
  risk_agent.py / execution_agent.py / execution_utils.py
  position_manager.py / sltp_manager.py / order_monitor.py
src/agents/llm/
  analyst_agent.py              → Provider chain + rule-based fallback
  commander_agent.py            → Telegram command parser (Groq)
  concierge_agent.py            → Chat mode, concurrency locked (Modal)
src/indicators/
  luxalgo_smc.py                → Public SMC API (OB, FVG, BOS/CHOCH)
  _smc_core.py                  → Internal port of LuxAlgo — DO NOT TOUCH style/naming
  mean_reversion.py / helpers.py
src/telegram/bot.py             → Router: Command → Commander, Chat → Concierge
src/backtest/engine.py          → CSV → Math Agents → entry/exit simulation
src/utils/
  exchange.py                   → ccxt singleton (get_exchange / reset_exchange)
  rate_limiter.py               → Sliding window 800 req/min
  llm_rate_limiter.py           → Per-provider semaphore + RPM + min_interval
  kill_switch.py / logger.py / mode.py / trade_utils.py
```

---

## Tech Stack

| Library | Version | Note |
|---|---|---|
| ccxt | 4.2.86 | **PINNED — do not upgrade** (newer versions block testnet futures) |
| Python | 3.12 | Use `list` not `List`, `X \| None` not `Optional[X]`, `dict` not `Dict` |
| SQLAlchemy | 2.0.31 | Use `Mapped` + `mapped_column` style — not 1.x legacy `Column()` |
| openai SDK | 1.40.0 | Used for ALL LLM providers (Cerebras, Groq, Modal) via `base_url` |
| Pydantic | 2.8.2 | v2 API — use `model_validate()` not `parse_obj()` |
| Ruff | 0.15.12 | Linter + formatter — replaces flake8, black, isort |

---

## Coding Conventions

**Result models** — every agent returns a Pydantic BaseModel, never a raw `dict`:
```python
TrendResult:        bias: int (-1/0/1), bias_label: str, confidence: float, reason: str
ReversalResult:     signal: str (LONG/SHORT/NONE), confidence: int, entry_price: float, reason: str
ConfirmationResult: confirmed: bool, reason: str, fvg_confluence: bool, bos_alignment: bool
RiskResult:         entry_price, sl_price, tp_price, position_size, rr_ratio, leverage, margin_required
ExecutionResult:    action: str (OPEN/SKIP/PENDING), reason: str, trade_id: int | None
AnalystDecision:    action: str (LONG/SHORT/SKIP), confidence: int, reasoning: str, source: str
```

**Agent pattern** — math agents live in `src/agents/math/`, extend `BaseAgent`, implement `run() → XxxResult`

**Config access** — read config via `settings.XXX` (delegates to `config_loader.py`). Non-secret config goes in `config.json`. Secrets go in `.env` only — never in `config.json` as plaintext.

**Style** — line length is 100 (not 79). Ruff rules: E, F, W, I (isort), N (naming), UP (pyupgrade).
- `_smc_core.py` — skip all style enforcement, upstream port
- `settings.py` — SCREAMING_CASE on `@property` methods is intentional (N802 ignored)

**Non-obvious dependencies:**
```
analyst_agent    → llm_rate_limiter.get_provider_limiter()
risk_agent       → luxalgo_smc.OrderBlock
position_manager → exchange.cancel_algo_order(), exchange.place_algo_order()
```

---

## Hard Rules

```
✗ Math agents         → NO LLM calls — zero exceptions
✗ LLM agents          → NO indicator calculations
✗ Secrets             → never hardcode in any file, .env only
✗ Exchange            → never instantiate ccxt.binanceusdm() directly, always get_exchange()
✗ DB                  → never write raw SQL strings, always use get_session() context manager
✗ ccxt                → never upgrade past 4.2.86 (newer versions break testnet)
✗ Refactor            → only when explicitly requested via bug report or feature request
✗ New dependencies    → check requirements/base.txt and Python stdlib first
✗ Parallel tool calls → run all tasks sequentially, one at a time
```

---

## Algo Order Rules

```
PLACE:  place_algo_order(symbol, side, order_type, trigger_price, qty)
        → returns dict with key 'algoId' — NOT 'orderId'

CANCEL: cancel_algo_order(algoId, symbol)
        → use this, NOT exchange.cancel_order() (wrong endpoint for algo orders)
```

---

## Testing
For testing, type check, format, Lint check. are in [CLAUDE.md](tests/CLAUDE.md)


---

## Cross-Cutting Gotchas

- **algoId ≠ orderId** — always extract `result['algoId']`, not `result['orderId']` from algo order response
- **Exchange singleton stale** — after any network error, call `reset_exchange()` before retrying
- **Mode switch** — changing `EXECUTION_MODE` in config without restarting keeps stale exchange state. Always restart
- **`confirm_mainnet`** — must be `true` in `config.json` before going live on mainnet, or bot will refuse to execute
- **SKIPPED trades** — excluded from ALL metrics: win rate, profit factor, drawdown
- **SL/TP check** — always compare against candle `high`/`low`, never `close` (look-ahead bias)
- **venv** — run `source venv/bin/activate` before every `python`, `pytest`, `pip`, or `ruff` command

> Domain-specific gotchas (DetachedInstanceError, Binance error codes, LLM provider edge cases, etc.)
> → see `.claude/agents/<domain>.md`

---

## Maintenance

- **Update this file** whenever architecture, conventions, or gotchas change
- **Max 150 lines** — if exceeded, move detail to the relevant `.claude/agents/` file
- **When Claude makes a mistake** — add a concrete, verifiable rule here. Do not just fix once.
- **Sub-agents** → `.claude/agents/` — load the relevant one before starting domain-specific work

