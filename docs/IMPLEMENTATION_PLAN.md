# IMPLEMENTATION_PLAN.md

> **Untuk AI Assistant (Claude Code):**
> File ini adalah **satu-satunya sumber kebenaran** untuk urutan pengembangan. Jangan pernah melompat ke Phase N jika Phase N-1 belum selesai. Jika ada konflik antara permintaan user dan aturan di file ini, **TANYAKAN KE USER DAHULU** sebelum menulis kode.

---

## 🛑 LOCKED ARCHITECTURE DECISIONS (JANGAN PERNAH DIUBAH)

1. **Exchange Type:** `ccxt.binanceusdm()` — USD-M Futures. BUKAN `ccxt.binance()`.
2. **Data Market:** WAJIB REST API. DILARANG WebSocket untuk stream tick/kline.
3. **Pemantauan Posisi (Phase 8 Live):** User Data WebSocket — hanya event `ORDER_TRADE_UPDATE`.
4. **Indikator:** Murni Python (`pandas`/`numpy`). DILARANG LLM menghitung RSI/SMC.
5. **Live Execution:** DILARANG OCO. Gunakan Entry Order + 2x Stop Market/TP Market terpisah.
6. **Model LLM:**
   - Analyst: Cerebras (Qwen-3-235B-A22B). Temp `0.0`. JSON mode.
   - Commander: Groq (Llama-3.1-8b-instant). Temp `0.0`. JSON mode.
   - Concierge: Modal (GLM-5 FP8). Temp `0.7`. Chat mode (NO JSON PARSING).
7. **RL Training:** Google Colab (GPU T4). BUKAN VPS. VPS hanya jalankan ONNX inference.
8. **Modal:** Koneksi via `openai` SDK + `base_url`. Modal SDK TIDAK diinstall.

## 🔧 ARCHITECTURE ADDENDUM (Override jika ada konflik dengan versi lama)

1. `USE_TESTNET: bool` wajib ada di `src/config/settings.py`. Gunakan untuk switch ccxt instance.
2. **LuxAlgo Scope:** Hanya 3 fungsi — Order Blocks, FVG, BOS/CHOCH. Skip semua visual/display.
3. **GLM-5 settings:** `CONCIERGE_TIMEOUT_SEC=600`, `CONCIERGE_MAX_TOKENS=5000`.
4. **RR Ratio:** Baca dari `settings.RISK_REWARD_RATIO`. DILARANG hardcode nilai RR di kode manapun.
5. **Position Size:** Fixed risk `settings.RISK_PER_TRADE_USD` (bukan % dari balance).
6. **Exit Check:** Gunakan high/low candle, BUKAN close price (menghindari look-ahead bias).
7. **SKIPPED trades:** Dieksklusi dari semua kalkulasi metrics (win rate, profit factor, drawdown).
8. **RL Exploration:** Thompson Sampling (Beta distribution per action). BUKAN epsilon-greedy.
9. **Multi-pair:** Backtest dan RL training support multi-pair via `--pairs` flag.

---

## STATUS IMPLEMENTASI

### ✅ PHASE 0: Scaffolding, Config & Database — SELESAI

- [x] Struktur folder sesuai spec
- [x] `src/config/settings.py` — Pydantic Settings, SecretStr, USE_TESTNET, FUTURES_MARGIN_TYPE, FUTURES_DEFAULT_LEVERAGE, RISK_PER_TRADE_USD, RISK_REWARD_RATIO
- [x] `src/data/storage.py` — SQLAlchemy models (ohlcv_h1, ohlcv_h4, ohlcv_15m, paper_trades, trade_logs)
- [x] `src/utils/logger.py` — Loguru setup
- [x] `src/utils/rate_limiter.py` — Sliding window, max 800 req/min

### ✅ PHASE 1: Data Engine & Safety Checks — SELESAI

- [x] `src/data/ohlcv_fetcher.py` — Fetch H4/H1/15m via `ccxt.binanceusdm()`
- [x] Gap Detector — `detect_gap_in_batch()`, tolak jika gap > `GAP_MULTIPLIER × timeframe_seconds`
- [x] Session Filter — `is_trading_session()`, London 07:00–10:00 + NY 13:00–16:00 UTC
- [x] Rate Limiter terintegrasi
- [x] `src/data/onchain_fetcher.py` — placeholder

### ✅ PHASE 2: Indikator SMC & Mean Reversion — SELESAI

- [x] `src/indicators/helpers.py` — ATR, Swing High/Low
- [x] `src/indicators/_smc_core.py` — Core SMC logic (internal)
- [x] `src/indicators/luxalgo_smc.py` — `detect_order_blocks()`, `detect_fvg()`, `detect_bos_choch()`, `detect_all()`
- [x] `src/indicators/mean_reversion.py` — RSI, Bollinger Bands
- [x] `scripts/validate_indicators.py` — script validasi manual vs TradingView

### ✅ PHASE 2.5: Backtest Engine — SELESAI

- [x] `src/backtest/engine.py` — Full pipeline: load CSV → Math Agents → simulasi entry/exit
  - Exit check pakai high/low candle (bukan close)
  - Position size: fixed risk USD dengan leverage
  - Fee 0.05% + slippage 0.1% per sisi
  - RL filter opsional via `use_rl=True` + ONNX inference
  - Multi-pair support
  - CSV export dengan 22+ kolom RL features
- [x] `src/backtest/metrics.py` — `TradeResult`, `BacktestMetrics`, `calculate_metrics()` — SKIPPED trades dieksklusi
- [x] `scripts/run_backtest.py` — CLI dengan `--pairs`, `--h4-csv`, `--h1-csv`, `--m15-csv`, `--use-rl` flags
- [x] Gate check terpenuhi (best config: WR ~55%, PF ~1.53, MDD ~8.84%, RR 2:1)

### ✅ PHASE 3: Math Agents — SELESAI

- [x] `src/agents/math/base_agent.py` — Base class
- [x] `src/agents/math/trend_agent.py` — H4 BOS/CHOCH, lookback 100 candle
- [x] `src/agents/math/reversal_agent.py` — H1 SMC + Mean Reversion, confidence 0–100
- [x] `src/agents/math/confirmation_agent.py` — 15m validation, fvg_confluence + bos_alignment
- [x] `src/agents/math/risk_agent.py` — ATR-based SL/TP, fixed USD risk, RR dari settings (tidak hardcode)
- [x] `src/agents/math/execution_agent.py` — Paper mode: INSERT paper_trades
- [x] `src/agents/math/sltp_manager.py` — Cek high/low candle, update CLOSED, hitung PnL

### ✅ PHASE 4: LLM Agents — SELESAI

- [x] `src/agents/llm/analyst_agent.py` — Cerebras Qwen-3-235B, temp 0.0, JSON mode, rule-based fallback
- [x] `src/agents/llm/commander_agent.py` — Groq Llama-3.1-8b, temp 0.0, JSON mode
- [x] `src/agents/llm/concierge_agent.py` — Modal GLM-5, temp 0.7, chat mode, concurrency lock

### ✅ PHASE 5: Orchestrator & Telegram — SELESAI

- [x] `src/main.py` — APScheduler 15 menit, full pipeline orchestration, asyncio + background thread
- [x] `src/telegram/bot.py` — Router Command/Chat, send_notification helper
- [x] `src/telegram/commands.py` — Handler output CommanderAgent
- [x] Stress test (24 jam): belum dilakukan secara formal

### ✅ PHASE 6: VPS Deployment — SELESAI

- [x] **6.1** Whitelist IP VPS di Binance API Management
- [x] **6.2** `/etc/systemd/system/crypto-agent.service` sudah dibuat
- [x] Bisa dijalankan via `run.sh` dan PM2
- [x] **6.3** Paper mode standalone di-skip — langsung integrasi ke Binance Futures Testnet di Phase 8. Paper trade tanpa exchange integration tidak menghasilkan data yang cukup valid untuk training RL.

### 🎯 PHASE 7: Go Live + Testnet Integration — PRIORITAS SEKARANG

*Phase ini sekaligus menggantikan paper trade standalone (Phase 6.3 yang di-skip).*

- [ ] **8.1** Set `.env`: `EXECUTION_MODE=live`, `USE_TESTNET=True`, `BINANCE_TESTNET_KEY`, `BINANCE_TESTNET_SECRET`
- [ ] **8.2** Implementasi `execution_agent.py` Live mode:
  ```python
  # Sebelum entry:
  exchange.set_leverage(leverage, symbol)
  exchange.set_margin_mode('isolated', symbol)

  # Entry:
  exchange.create_order(symbol, 'market', side, amount)

  # Segera setelah entry — 2 order terpisah:
  exchange.create_order(symbol, 'stop_market', opposite_side, amount,
      params={'stopPrice': sl_price, 'closePosition': True})
  exchange.create_order(symbol, 'take_profit_market', opposite_side, amount,
      params={'stopPrice': tp_price, 'closePosition': True})
  ```
  - **DILARANG** `type='OCO'` — tidak didukung di Futures.
- [ ] **8.3** Nonaktifkan `sltp_manager.py` di live mode (SL/TP sudah di server Binance).
- [ ] **8.4** Implementasi `src/data/ws_user_stream.py`:
  - User Data WebSocket (`wss://stream.binancefuture.com/ws` untuk testnet)
  - Hanya dengarkan event `ORDER_TRADE_UPDATE`
  - Jalankan sebagai `threading.Thread(daemon=True)` — tidak boleh blokir loop utama
  - Jika menerima status `FILLED`: update `paper_trades` → `CLOSED`, kirim notif Telegram
- [ ] **8.5** Jalankan di **Binance Testnet** 48 jam tanpa error
- [ ] **8.6** Setelah cukup data dari Testnet (≥100 closed trades) → lanjut Phase 7 (training RL)
- [ ] **8.7** Setelah RL model siap dan diverifikasi → set `USE_TESTNET=False` untuk Mainnet

---

## 📝 CATATAN TEKNIS PENTING

### Bugs yang sudah di-fix
- **Bug #1:** Position size formula — sekarang fixed risk USD dengan leverage (bukan % dari balance)
- **Bug #2:** SL/TP — ATR-based, bukan % flat
- **Bug #3:** Exit check — pakai high/low candle, bukan close (look-ahead bias fix)
- **Bug #4:** RR ratio — dibaca dari `settings.RISK_REWARD_RATIO`, tidak hardcode
- **Bug #5:** SKIPPED trades — dieksklusi dari semua metrics calculation

### Known Issues / Masih Perlu Perhatian
- XRPUSDT bermasalah: ranging behavior menyebabkan TrendAgent selalu output RANGING. Perlu tuning `swing_size` atau threshold per-pair.
- `scripts/export_trade_data.py` belum dibuat — diperlukan untuk Phase 7 setelah Testnet berjalan.
- `src/data/onchain_fetcher.py` masih placeholder.
- Binance Copy Trade agent (`copytrade_agent.py`) belum diimplementasi — ada di FR tapi tidak diprioritaskan.

### File yang ada tapi tidak dipakai di production
- `*.bak` files — backup manual, bisa dihapus
- `examples/demo_environment.py` — demo saja

---

## 📋 SUCCESS METRICS SEBELUM NAIK KE MAINNET

1. Backtest Phase 2.5 **LULUS** gate check (win rate ≥ 45%, profit factor ≥ 1.2, max drawdown ≤ 30%). ✅
2. Kode Entry + 2x Stop Market/TP Market ditest di **Binance Testnet** 48 jam tanpa error.
3. Testnet menghasilkan minimal **100 closed trades** untuk data training RL.
4. RL model dilatih di Colab, diverifikasi via `--use-rl` backtest, improvement terukur.
5. Set `USE_TESTNET=False` → Mainnet.

---

*(File ini di-update April 2026. Architecture Addendum berlaku sebagai override untuk semua konflik dengan versi sebelumnya.)*

