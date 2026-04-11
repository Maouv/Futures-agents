# Futures Agents

Bot trading crypto futures multi-agent yang jalan 24/7 di VPS. Trade Binance USD-M Futures via ccxt. Pipeline: Math Agents (pure Python) → LLM Analyst (Cerebras) → optional RL filter (ONNX).

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
  execution_agent.py              → Paper: INSERT DB | Live: Limit + Algo SL/TP
  sltp_manager.py                 → Paper mode SL/TP check (high/low candle)
src/agents/llm/
  analyst_agent.py                → Cerebras Qwen-3, fallback rule-based jika API down
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
- **Binance -4137**: Error ini = buy price above trigger price untuk stop orders. Artinya stop sudah ke-trigger, skip order
- **Binance -4120 STOP_ORDER_SWITCH_ALGO**: Sejak Des 2025, `STOP_MARKET`/`TAKE_PROFIT_MARKET` TIDAK BISA lewat `POST /fapi/v1/order`. WAJIB pakai `POST /fapi/v1/algoOrder` dengan `algoType=CONDITIONAL`, param `triggerPrice` (bukan `stopPrice`), response key `algoId` (bukan `orderId`)
- **Order status `closed`**: Binance bisa return `closed` selain `filled` untuk order yang sudah tereksekusi. Kedua-duanya harus ditangani
- **Naive datetime di SQLite**: `PaperTrade.entry_timestamp` dari DB tidak punya timezone. Harus `.replace(tzinfo=timezone.utc)` sebelum dikurangi `datetime.now(timezone.utc)`
- **ccxt version**: Pakai `4.2.86`. JANGAN upgrade — versi baru nge-block testnet untuk futures. Algo API dipanggil manual via `requests` di `place_algo_order()`
- **Rate limiter**: Max 800 req/min. Kalau >5 pairs, ada 1 detik throttle antar LLM call
- **`onchain_fetcher.py`**: Placeholder, tidak diimplementasi. Jangan hapus tapi jangan pakai juga
- **RL training**: HANYA di Google Colab (GPU T4). Jangan install torch/gymnasium/SB3 di VPS — akan OOM

## Config

| Key | Default | Keterangan |
|-----|---------|------------|
| `EXECUTION_MODE` | `paper` | `paper` = simulasidi DB, `live` = order sungguhan ke Binance |
| `USE_TESTNET` | `False` | `True` = Binance Testnet, `False` = Production |
| `CONFIRM_MAINNET` | `False` | Wajib `True` kalau `USE_TESTNET=False` — speed bump anti salah klik |
| `RISK_PER_TRADE_USD` | `10.0` | Risk per trade dalam USD (fixed, bukan persen) |
| `RISK_REWARD_RATIO` | `2.0` | R:R ratio. Jangan hardcode — baca dari settings |
| `FUTURES_DEFAULT_LEVERAGE` | `10` | Leverage default (1-125) |
| `FUTURES_MARGIN_TYPE` | `isolated` | `isolated` atau `cross` |
| `MAX_OPEN_POSITIONS` | `1` | Max posisi terbuka per pair |
| `ORDER_EXPIRY_CANDLES` | `48` | Limit order expire setelah N candle H1 (48 = 2 hari) |
| `DISABLE_SESSION_FILTER` | `False` | `True` = trade di semua jam (testing only) |
| `CEREBRAS_MODEL` | `qwen-3-235b-...` | Model Analyst Agent |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Model Commander + Concierge |
| `LLM_FAST_TIMEOUT_SEC` | `45` | Timeout Cerebras & Groq |
| `CONCIERGE_TIMEOUT_SEC` | `600` | Timeout Concierge (GLM-5 lambat) |

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

## Maintenance Rule

- **ALWAYS update CLAUDE.md** when codebase changes affect architecture, gotchas, or conventions
- **CLAUDE.md max 300 lines** — if exceeding, compact by merging sections, removing verbose examples, or archiving stale content. Never remove critical gotchas or conventions
