# Futures Agents

Bot trading crypto futures multi-agent yang jalan 24/7 di VPS. Trade Binance USD-M Futures via ccxt. Pipeline: Math Agents (pure Python) → LLM Analyst (Cerebras) → optional RL filter (ONNX).

**Bahasa**: Gunakan Bahasa Indonesia untuk semua komunikasi dan penjelasan. English hanya untuk code, identifier, dan technical terms.

---

## Arsitektur

```
src/main.py                      → Orchestrator — 15-min APScheduler cycle + Telegram
src/config/
  settings.py                    → Pydantic Settings — SINGLE SOURCE OF TRUTH semua config
  pairs.py                        → Load pairs dari pairs.json
src/data/
  storage.py                      → SQLAlchemy models (OHLCV + PaperTrade) + session factory
  ohlcv_fetcher.py                → REST API fetcher + gap detector + session filter
  ws_user_stream.py               → User Data WebSocket (live mode only, order updates)
src/agents/math/                  → Pure Python — DILARANG panggil LLM di sini
  base_agent.py                   → BaseAgent ABC — semua agent turun dari sini
  trend_agent.py                  → H4 BOS/CHOCH → TrendResult
  reversal_agent.py               → H1 SMC (OB+FVG) → ReversalResult
  confirmation_agent.py           → 15m validation → ConfirmationResult
  risk_agent.py                   → ATR SL/TP + fixed USD sizing → RiskResult
  execution_agent.py              → Paper: INSERT DB | Live: Limit + Algo SL/TP → ExecutionResult
  sltp_manager.py                 → Paper mode SL/TP check (high/low candle)
src/agents/llm/
  analyst_agent.py                → Cerebras Qwen-3, fallback rule-based jika API down → AnalystDecision
  commander_agent.py              → Groq Llama-3.1 — Telegram command parser
  concierge_agent.py              → Groq Llama-3.1 — chat mode, concurrency locked
src/indicators/
  _smc_core.py                    → Internal SMC logic (OB, FVG, BOS/CHOCH)
  luxalgo_smc.py                  → Public API: detect_order_blocks(), detect_fvg(), detect_bos_choch()
  mean_reversion.py               → RSI + Bollinger Bands
  helpers.py                      → ATR, Swing High/Low
src/rl/                           → RL filter — training di Colab, inference ONNX di VPS
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
  rate_limiter.py                 → Sliding window 800 req/min
  kill_switch.py                  → Emergency stop
  logger.py                       → Loguru setup
```

## Result Models (Pydantic)

Setiap agent return model ini — jangan ngarang field lain:

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
        → POST /fapi/v1/algoOrder, algoType=CONDITIONAL, param=triggerPrice (BUKAN stopPrice)
        → returns dict dengan key 'algoId' (BUKAN 'orderId')

CANCEL: cancel_algo_order(algoId, symbol)
        → DELETE /fapi/v1/algoOrder
        → BUKAN exchange.cancel_order() — endpoint lama tidak bisa cancel algo

WS TRIGGER: ORDER_TRADE_UPDATE.i = orderId BARU (bukan algoId)
        → Fallback match: cari by symbol + side jika algoId tidak cocok
```

## Cara Kerja

1. Setiap 15 menit (APScheduler, cron `0,15,30,45`), untuk setiap pair di `pairs.json`:
2. `fetch_ohlcv()` → H4, H1, 15m → gap check → session filter (London/NY only)
3. `TrendAgent(H4)` + `ReversalAgent(H1)` + `ConfirmationAgent(15m)` → sinyal mentah
4. `AnalystAgent(LLM)` → keputusan LONG/SHORT/SKIP (fallback ke rule-based jika API down)
5. [Opsional] RL filter via ONNX inference
6. `RiskAgent` → SL/TP/size → `ExecutionAgent` → paper INSERT atau live order
7. `sltp_manager` cek semua open paper trades pakai high/low candle

## Konvensi

- **Result model**: Setiap agent return Pydantic BaseModel (bukan dict). Nama pattern: `XxxResult`
- **Agent pattern**: Semua math agent extend `BaseAgent`, implement `run() → XxxResult`
- **Config**: Satu source of truth di `settings.py`. Akses via `settings.XXX`, secret via `.get_secret_value()`. Jangan pakai `os.getenv()`
- **Exchange**: Selalu `get_exchange()` dari `src/utils/exchange.py`. Jangan buat `ccxt.binanceusdm()` langsung
- **Exit check**: Pakai candle **high/low**, bukan close (hindari look-ahead bias)
- **SKIPPED trades**: Dikecualikan dari semua metric (win rate, profit factor, drawdown)
- **LLM fallback**: Bot TIDAK BOLEH crash karena LLM down. `analyst_agent.py` selalu punya rule-based fallback
- **SL/TP live**: 2x Algo Order (`STOP_MARKET` + `TAKE_PROFIT_MARKET`). WAJIB pakai `place_algo_order()` dari `exchange.py`
- **Model**: Pakai `openai` SDK + `base_url`
- **Position sizing**: Fixed USD (`RISK_PER_TRADE_USD`), bukan persen balance
- **DB session**: Selalu pakai `get_session()` context manager. Jangan raw SQL

## Cara Nambah Fitur Baru

1. Tambah config di `src/config/settings.py` (field + default + `.env`)
2. Kalau agent baru: buat file di `src/agents/math/`, extend `BaseAgent`, return Pydantic model
3. Daftarkan agent di pipeline `src/main.py::TradingBot.run_trading_cycle()`
4. Kalau indikator baru: buat di `src/indicators/`, panggil dari agent (bukan dari LLM)
5. Tambah pair: edit `pairs.json` di root project, restart bot
6. Update section ini jika arsitektur berubah

## Gotcha / Known Issues

- **Exchange singleton**: Setelah network error, panggil `reset_exchange()` — singleton menyimpan stale state
- **SQLite WAL**: Enabled via PRAGMA. Jangan ubah ke DELETE mode — bisa corrupt di concurrent read/write
- **DetachedInstanceError**: Akses atribut PaperTrade di luar session scope akan crash. Ambil semua nilai yang dibutuhkan sebelum session close
- **Mode switch**: Kalau ganti `EXECUTION_MODE` tanpa restart, exchange instance masih pakai config lama. WAJIB restart
- **`current_price` undefined**: Di beberapa path, `current_price` belum di-assign sebelum dipakai. Pastikan selalu ada fallback
- **Binance error codes**:
  | Code | Penyebab | Handling |
  |------|----------|----------|
  | -4137 | Stop sudah ter-trigger (buy price above trigger) | Skip order |
  | -4120 | Pakai `/fapi/v1/order` untuk algo order | Pakai `/fapi/v1/algoOrder` |
- **Order status `closed`**: Binance bisa return `closed` selain `filled`. Kedua-duanya = tereksekusi
- **Naive datetime di SQLite**: `PaperTrade.entry_timestamp` dari DB tidak punya timezone. Harus `.replace(tzinfo=timezone.utc)` sebelum dikurangi `datetime.now(timezone.utc)`
- **ccxt version**: Pakai `4.2.86`. JANGAN upgrade — versi baru nge-block testnet untuk futures. Algo API dipanggil manual via `requests`
- **Rate limiter**: Max 800 req/min. Kalau >5 pairs, ada 1 detik throttle antar LLM call
- **`onchain_fetcher.py`**: Placeholder, tidak diimplementasi. Jangan hapus tapi jangan pakai juga
- **RL training**: HANYA di Google Colab (GPU T4). Jangan install torch/gymnasium/SB3 di VPS — akan OOM
- **Reconciliation symbol format**: `exchange.fetch_positions()` return unified symbol `'BTC/USDT:USDT'`. Ambil raw symbol dari `pos['info']['symbol']` (`'BTCUSDT'`), BUKAN dari `pos['symbol']`
- **RiskAgent ValueError**: `RiskAgent.run()` bisa raise ValueError kalau risk distance terlalu kecil. WAJIB di-try/except di caller — kalau tidak, seluruh trading cycle crash untuk semua pair
- **OB Midpoint Overlap**: Jika harga sudah melewati OB midpoint di cycle berikutnya, `RiskAgent.run()` bisa raise `OverlapSkipError` (harga di luar OB zone → SKIP) atau adjust entry ke current_price (`entry_adjusted=True`). Live mode: adjusted entry pakai market order + langsung pasang SL/TP, bukan limit + PENDING_ENTRY
- **SL/TP both hit**: Kalau dalam 1 candle SL DAN TP sama-sama kena, SL prioritas

## Config

| Key | Type | Default | Required | Keterangan |
|-----|------|---------|----------|------------|
| `EXECUTION_MODE` | str | `paper` | Yes | `paper` = simulasi di DB, `live` = order sungguhan |
| `USE_TESTNET` | bool | `False` | Yes | `True` = Binance Testnet |
| `CONFIRM_MAINNET` | bool | `False` | Yes* | Wajib `True` kalau `USE_TESTNET=False` |
| `BINANCE_API_KEY` | SecretStr | - | Live only | Wajib jika `live` + `USE_TESTNET=False` |
| `BINANCE_TESTNET_KEY` | SecretStr | - | Live only | Wajib jika `live` + `USE_TESTNET=True` |
| `CEREBRAS_API_KEY` | SecretStr | - | Yes | Analyst Agent |
| `GROQ_API_KEY` | SecretStr | - | Yes | Commander + Concierge |
| `TELEGRAM_BOT_TOKEN` | SecretStr | - | Yes | - |
| `TELEGRAM_CHAT_ID` | str | - | Yes | Bisa negatif (group) |
| `RISK_PER_TRADE_USD` | float | `10.0` | No | Risk per trade dalam USD (fixed) |
| `RISK_REWARD_RATIO` | float | `2.0` | No | Jangan hardcode — baca dari settings |
| `FUTURES_DEFAULT_LEVERAGE` | int | `10` | No | Range 1-125 |
| `FUTURES_MARGIN_TYPE` | str | `isolated` | No | `isolated` atau `cross` |
| `MAX_OPEN_POSITIONS` | int | `1` | No | Per pair, bukan global |
| `ORDER_EXPIRY_CANDLES` | int | `48` | No | Limit order expire setelah N candle H1 |
| `DISABLE_SESSION_FILTER` | bool | `True` | No | `True` = trade semua jam |
| `CEREBRAS_MODEL` | str | `qwen-3-235b-...` | No | Model Analyst Agent |
| `GROQ_MODEL` | str | `llama-3.1-8b-instant` | No | Model Commander + Concierge |
| `LLM_FAST_TIMEOUT_SEC` | int | `45` | No | Timeout Cerebras & Groq |
| `CONCIERGE_TIMEOUT_SEC` | int | `600` | No | Timeout Concierge |

## Dependency Antar Modul

```
main.py → ohlcv_fetcher → exchange (singleton)
        → trend_agent → luxalgo_smc → _smc_core
        → reversal_agent → luxalgo_smc
        → confirmation_agent
        → analyst_agent → trend/reversal/confirmation Result models
        → risk_agent → helpers (ATR), luxalgo_smc (OrderBlock)
        → execution_agent → exchange, storage (PaperTrade)
        → sltp_manager → storage
        → telegram_bot → commander_agent, concierge_agent
```

Semua agent bergantung ke `base_agent.py`. Semua config bergantung ke `settings.py`. Exchange diakses via singleton `get_exchange()`.

## Environment & Execution Rules

- **Python environment**: WAJIB `source venv/bin/activate` sebelum menjalankan Python apapun (`python`, `pytest`, `pip`, dll). Jangan pernah run tanpa activate venv
- **Sequential execution**: Kerjakan SEMUA tugas secara sequential, satu per satu. JANGAN pernah paralel — model ini hanya 1 concurrent request. Tidak ada parallel tool calls, tidak ada background tasks yang overlap

## Anti-Patterns / Jangan Pernah

- **Jangan buat class kalau function cukup** — math agents pakai class karena ABC pattern, tapi utility/helper cukup function
- **Jangan refactor yang sudah jalan** — kalau tidak ada bug report atau feature request, biarkan apa adanya
- **Jangan tambah dependency baru** tanpa cek dulu apakah sudah ada di requirements.txt atau stdlib
- **Jangan pakai `os.getenv()`** — selalu `settings.XXX` atau `settings.get_secret_value()`
- **Jangan buat `ccxt.binanceusdm()` langsung** — selalu `get_exchange()`
- **Jangan tulis raw SQL** — selalu pakai SQLAlchemy via `get_session()`
- **Jangan install torch/gymnasium/SB3 di VPS** — OOM, training hanya di Colab
- **Jangan upgrade ccxt** — versi baru nge-block testnet futures
- **Jangan pakai `exchange.cancel_order()` untuk algo order** — pakai `cancel_algo_order()` dari `exchange.py`

## Maintenance Rule

- **ALWAYS update CLAUDE.md** when codebase changes affect architecture, gotchas, or conventions
- **CLAUDE.md max 300 lines** — if exceeding, compact by merging sections, removing verbose examples, or archiving stale content. Never remove critical gotchas or conventions
- **Verify file existence** before referencing — if architecture tree is stale, update it
