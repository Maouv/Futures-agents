# 📄 PRD.md — Crypto Multi-Agent Futures Trading System

> **Last updated:** April 2026 — sinkronisasi dengan codebase aktual.

---

## 1. Product Overview

Sistem trading bot otonom berbasis multi-agent yang berjalan 24/7 di VPS (Contabo: 4 vCPU, 8GB RAM, 75GB NVMe). Sistem memisahkan secara tegas antara **Logika Matematika murni (Python)** untuk perhitungan indikator, dan **Kognitif (LLM)** untuk penalaran akhir dan interface pengguna. Terdapat lapisan **Reinforcement Learning (DQN)** sebagai filter sinyal tambahan yang dilatih di Google Colab dan di-deploy ke VPS via ONNX. Fase pertama berjalan dalam mode *Paper Trading*, sebelum bermigrasi ke *Live Trading* dengan mekanisme *server-side risk management*.

---

## 2. Goals & Non-Goals

**Goals:**
- Membangun pipeline data end-to-end menggunakan **REST API** (tanpa Market Data WebSocket).
- Mengimplementasikan Math Agents dan LLM Agents dengan pembagian tugas yang sangat ketat.
- Memvalidasi akurasi porting PineScript LuxAlgo SMC ke Python (selisih max 0.001).
- Menjalankan Paper Trade realistis dengan simulasi fee (0.05%) dan slippage (0.1%) per sisi.
- Melatih DQN agent di Google Colab (GPU T4), deploy ke VPS via ONNX Runtime sebagai filter sinyal.
- Mendukung **multi-pair** backtest dan trading (BTCUSDT, ETHUSDT, dst.).
- Mengamankan eksekusi Live Trading menggunakan **Entry Order + 2x Stop Market/TP Market Order terpisah**.
- Sistem full Futures (USD-M) baik saat Paper maupun Live.

**Non-Goals (Strictly Prohibited):**
- ❌ **TIDAK** menggunakan WebSocket untuk stream data harga (Market Data WS).
- ❌ **TIDAK** menggunakan LLM untuk menghitung indikator teknikal (RSI, SMC, ATR).
- ❌ **TIDAK** membiarkan bot memonitor harga manual untuk Cut Loss di Live Trading (gunakan server-side Stop Market).
- ❌ **TIDAK** menggunakan dynamic position sizing — risk fixed `RISK_PER_TRADE_USD` dari `.env`.
- ❌ **TIDAK** menggunakan spot trading (`ccxt.binance()`).
- ❌ **TIDAK** menggunakan OCO order di Futures.
- ❌ **TIDAK** melatih PyTorch/RL di VPS production (OOM risk).

---

## 3. Functional Requirements

### FR-1: Data Collection & Safety Layer

- **FR-1.1:** Fetch OHLCV (H4, H1, 15m) menggunakan `ccxt.binanceusdm()` REST API, dibungkus Rate Limiter (max 800 req/menit, sliding window).
- **FR-1.2 (Gap Detector):** Sistem membandingkan timestamp antar candle dalam batch. Jika ada gap > `GAP_MULTIPLIER × timeframe_seconds`, sistem **wajib membatalkan** analisis pada siklus itu. *(Implemented: `detect_gap_in_batch()` di `ohlcv_fetcher.py`)*
- **FR-1.3 (Session Filter):** Sistem wajib menolak sinyal trade di luar jam volatilitas tinggi. Sinyal hanya boleh dihasilkan saat UTC berada di: **London Open (07:00–10:00 UTC)** atau **New York Open (13:00–16:00 UTC)**. Di luar session, SLTP check tetap berjalan. *(Implemented: `is_trading_session()` di `ohlcv_fetcher.py`)*
- **FR-1.4:** Data historis (minimal 3 tahun) di-download dari Binance Vision (`data.binance.vision`) untuk keperluan backtest dan training RL.

### FR-2: Math Agents (Pure Python — No LLM Allowed)

- **FR-2.1 (Trend Agent):** Analisis BOS/CHOCH di H4. Output: `TrendResult` (`BULLISH`/`BEARISH`/`RANGING`, confidence, reason). Lookback: 100 candle terakhir. *(Implemented: `src/agents/math/trend_agent.py`)*
- **FR-2.2 (Reversal Agent):** Analisis H1 menggunakan LuxAlgo SMC (Order Block, FVG, BOS/CHOCH) + Mean Reversion. Output: `ReversalResult` (signal LONG/SHORT/NONE, confidence 0–100, entry_price). *(Implemented: `src/agents/math/reversal_agent.py`)*
- **FR-2.3 (Confirmation Agent):** Validasi sinyal H1 di timeframe 15m. Output: `ConfirmationResult` (confirmed bool, fvg_confluence, bos_alignment). *(Implemented: `src/agents/math/confirmation_agent.py`)*
- **FR-2.4 (Risk Agent):** Hitung SL/TP berbasis ATR + OB edge, position size berbasis `RISK_PER_TRADE_USD` fixed dari settings. Output: `RiskResult` (entry, sl, tp, size, margin_required, rr_ratio). *(Implemented: `src/agents/math/risk_agent.py`)*
- **FR-2.5 (Execution Agent):** Mode Paper: INSERT ke `paper_trades` SQLite status `OPEN`. Mode Live (Phase 8): kirim Entry + 2x Stop Market/TP Market ke Binance. *(Implemented paper mode: `src/agents/math/execution_agent.py`)*
- **FR-2.6 (SLTP Manager):** Cek paper trade terbuka setiap siklus. Bandingkan high/low candle 15m dengan SL/TP (bukan close — menghindari look-ahead bias). Update status `CLOSED`, hitung PnL. *(Implemented: `src/agents/math/sltp_manager.py`)*

### FR-3: LLM Agents (Cognitive Layer)

- **FR-3.1 (The Analyst):**
  - **Model:** Cerebras (Qwen-3-235B-A22B). Temperature: 0.0. JSON mode.
  - **Tugas:** Menerima output Math Agents, memutuskan `LONG`/`SHORT`/`SKIP` berdasarkan confluence.
  - **Wajib fallback** ke Rule-Based Python jika API down/timeout — bot tidak boleh berhenti.
  - *(Implemented: `src/agents/llm/analyst_agent.py`)*

- **FR-3.2 (The Commander):**
  - **Model:** Groq (Llama-3.1-8b-instant). Temperature: 0.0. JSON mode.
  - **Tugas:** Terjemahkan perintah Telegram user ke nama fungsi Python yang bisa dieksekusi.
  - *(Implemented: `src/agents/llm/commander_agent.py`)*

- **FR-3.3 (The Concierge):**
  - **Model:** Modal (GLM-5 FP8). Temperature: 0.7. Chat mode — **DILARANG JSON parsing**.
  - **Timeout:** `CONCIERGE_TIMEOUT_SEC=600`. **Max tokens:** `CONCIERGE_MAX_TOKENS=5000`.
  - Koneksi via `openai` SDK + `base_url=settings.MODAL_BASE_URL` (bukan Modal SDK).
  - Wajib ada Concurrency Lock — jika sedang proses, tolak request baru.
  - *(Implemented: `src/agents/llm/concierge_agent.py`)*

### FR-4: Reinforcement Learning Layer

- **FR-4.1 (Environment):** Custom `TradingEnvironment` (non-gymnasium) yang konsumsi CSV signals dari backtest. Action space: `SKIP=0` / `ENTRY=1`. State vector: 13 fitur. *(Implemented: `src/rl/environment.py`)*
- **FR-4.2 (DQN Agent + Thompson Sampling):** DQN dengan arsitektur `[input → 128 → 64 → output]`. Exploration menggunakan Thompson Sampling (Beta distribution per action) — lebih adaptive dari epsilon-greedy. *(Implemented: `src/rl/dqn_agent.py`)*
- **FR-4.3 (Training — Google Colab):** Training dilakukan di Colab (GPU T4), BUKAN di VPS. Multi-pair training: load semua CSV dari `data/rl_training/`. Export model ke ONNX. *(Implemented: `src/rl/trainer.py`)*
- **FR-4.4 (Inference — VPS):** Deploy model ONNX ke VPS, jalankan via `onnxruntime` (tanpa PyTorch). RL filter adalah lapisan opsional (`use_rl=True` di BacktestEngine). *(Implemented: `src/rl/inference.py`)*
- **FR-4.5 (Reward Shaping):**
  - ENTRY + TP → actual PnL (positif)
  - ENTRY + SL/TIMEOUT → actual PnL (negatif)
  - SKIP + TP → -0.5 (missed opportunity)
  - SKIP + SL/TIMEOUT → +0.3 (avoided loss)
  - SKIP + SKIPPED → 0.0 (neutral)

### FR-5: Backtest Engine

- **FR-5.1:** Load data dari CSV historis Binance Vision (H4, H1, 15m per pair). Jalankan pipeline Math Agents. Simulasi entry/exit dengan high/low candle (bukan close) untuk menghindari look-ahead bias. *(Implemented: `src/backtest/engine.py`)*
- **FR-5.2:** Fee 0.05% + slippage 0.1% per sisi dimasukkan ke kalkulasi PnL.
- **FR-5.3:** Output `BacktestMetrics`: total_trades, win_rate, profit_factor, max_drawdown, avg_win, avg_loss. SKIPPED trades dieksklusi dari metrik.
- **FR-5.4:** CSV export per trade dengan 22+ kolom field termasuk RL training features (bos_type, ob_size, distance_to_ob, fvg_present, candle_body_ratio, hour_of_day, consecutive_losses, time_since_last_trade, current_drawdown_pct).
- **FR-5.5:** Multi-pair support — `run_backtest.py --pairs BTCUSDT,ETHUSDT,SOLUSDT` akan aggregate metrics dari semua pair.

### FR-6: Telegram Interface

- **FR-6.1:** Router pesan: Command → CommanderAgent, Chat → ConciergeAgent.
- **FR-6.2:** Notifikasi struktural: `🔔 Paper Entry`, `✅ TP Hit`, `❌ SL Hit`.
- *(Implemented: `src/telegram/bot.py`, `src/telegram/commands.py`)*

---

## 4. System Architecture Constraints (Mandatory)

1. **Exchange:** Selalu `ccxt.binanceusdm()`. BUKAN `ccxt.binance()`.
2. **Data:** REST API only. DILARANG Market Data WebSocket.
3. **Indikator:** Murni Python (`pandas`/`numpy`). DILARANG minta LLM menghitung RSI/SMC.
4. **Live Execution:** Entry Order + 2x Stop Market/TP Market terpisah. DILARANG OCO.
5. **RL Training:** Di Google Colab, bukan VPS. VPS hanya jalankan ONNX inference.
6. **Concurrency:** Scheduler 15 menit (`APScheduler`) di background thread. Telegram bot di main thread (asyncio).
7. **Error Resilience:** LLM down → fallback rule-based. Bot tidak boleh stop karena LLM timeout.
8. **Testnet:** `USE_TESTNET: bool` di `settings.py` untuk switch ccxt instance. DILARANG hardcode URL.
9. **Secrets:** Semua API key via `pydantic-settings` + `SecretStr`. DILARANG hardcode di kode.
10. **Modal/GLM-5:** Koneksi via `openai` SDK, bukan Modal SDK. Modal SDK tidak diinstall.

---

## 5. Data Flow

```
Binance Vision CSV (historis, 3 tahun)
    └→ BacktestEngine (multi-pair) → Math Agents → CSV Signals per pair
           └→ TradingEnvironment → DQNTrainer (Colab) → best_model.onnx

Binance Futures Testnet (live, setiap 15 menit)          ← PRIORITAS SEKARANG
    └→ ohlcv_fetcher (Gap Detector + Session Filter)
           └→ TrendAgent (H4) + ReversalAgent (H1) + ConfirmationAgent (15m)
                  └→ AnalystAgent (Cerebras) ──fallback→ Rule-Based
                         └→ [RL Filter via ONNX — aktif setelah Phase 7 selesai]
                                └→ RiskAgent → ExecutionAgent (Live mode)
                                       └→ Entry + 2x Stop Market/TP Market → Binance Server
                                              └→ User Data WS → update DB → Telegram Notif
```

---

## 6. State Vector RL (13 Features)

| # | Feature | Keterangan |
|---|---------|------------|
| 1 | `trend_bias` | Encoded: BULLISH=1, BEARISH=-1, RANGING=0 |
| 2 | `bos_type` | Encoded: BULLISH_BOS=1, BEARISH_BOS=-1, NONE=0 |
| 3 | `ob_high` | Order Block upper boundary |
| 4 | `ob_low` | Order Block lower boundary |
| 5 | `ob_size` | OB high - OB low |
| 6 | `distance_to_ob` | Jarak entry ke OB midpoint |
| 7 | `atr` | ATR 14-period |
| 8 | `fvg_present` | FVG confluence (binary) |
| 9 | `candle_body_ratio` | abs(close-open) / (high-low) |
| 10 | `hour_of_day` | Jam UTC (0–23) |
| 11 | `consecutive_losses` | Jumlah loss berturut-turut sebelum trade ini |
| 12 | `time_since_last_trade` | Menit sejak trade terakhir |
| 13 | `current_drawdown_pct` | Drawdown saat entry |

---

## 7. Best Config Backtest (Referensi)

Hasil backtest terbaik yang sudah ditemukan (BTCUSDT, 3 tahun data):
- **Config:** RR 3:1, M15 confirmation filter
- **Win Rate:** ~55%
- **Profit Factor:** ~1.53
- **Max Drawdown:** ~8.84%
- **Fee + Slippage:** sudah diperhitungkan
- **Catatan:** XRPUSDT bermasalah karena ranging behavior — threshold trend detection perlu tuning per-pair.

---

## 8. Success Metrics untuk Naik ke Mainnet

1. Backtest **LULUS** gate check: win rate ≥ 45%, profit factor ≥ 1.2, max drawdown ≤ 30%, total trades ≥ 50. ✅
2. Kode Entry + 2x Stop Market/TP Market ditest di **Binance Testnet** 48 jam tanpa error.
3. Testnet menghasilkan minimal **100 closed trades** → dipakai sebagai data training RL.
4. RL model dilatih di Colab, diverifikasi via `--use-rl` backtest, improvement terukur.
5. Set `USE_TESTNET=False` → Mainnet.

