
# IMPLEMENTATION_PLAN.md

> **Perhatian untuk AI Assistant (Claude Code):**
> File ini adalah **satu-satunya sumber kebenaran (source of truth)** untuk urutan pengembangan. Jangan pernah melompat ke Phase N jika Phase N-1 belum selesai. Jika ada konflik antara permintaan user dan aturan di file ini, **TANYAKAN KE USER DAHULU** sebelum menulis kode.

---

## 🛑 LOCKED ARCHITECTURE DECISIONS (JANGAN PERNAH DIUBAH)

Sebelum memulai, kamu harus menghafal batasan sistem ini:
1. **Exchange Type:** **Futures (USD-M)**. Gunakan `ccxt.binanceusdm()`. BUKAN `ccxt.binance()`.
2. **Data Historis/Market:** WAJIB pakai REST API. DILARANG pakai WebSocket untuk stream data tick/kline.
3. **Pemantauan Posisi (Phase 8 Live):** Pakai User Data WebSocket (hanya dengarkan event `ORDER_TRADE_UPDATE`).
4. **Perhitungan Indikator:** WAJIB murni Python (`pandas`/`numpy`). DILARANG meminta LLM untuk menghitung RSI/SMC.
5. **Live Execution Method:** **DILARANG PAKAI OCO.** Gunakan Entry Order + 2x Stop Market/TP Market Order terpisah.
6. **Model LLM:**
│ │- Analyst: `Cerebras` (Qwen-3-235B). Temp `0.0`. JSON mode.
│ │- Commander: `Groq` (Llama-3.1-8b). Temp `0.0`. JSON mode.
│ │- Concierge: `Modal` (GLM-5 FP8). Temp `0.8`. Chat mode (NO JSON PARSING).

## 🔧 ARCHITECTURE ADDENDUM (Ditambahkan setelah versi awal — berlaku sebagai override)

1. **`USE_TESTNET: bool`** wajib ada di `src/config/settings.py`. Gunakan field ini untuk switch ccxt instance antara production dan testnet. Jangan hardcode URL di agent manapun.
2. **Scope LuxAlgo Phase 2:** Hanya port 3 fungsi — Order Blocks, FVG, BOS/CHOCH. Skip semua fitur visual/display.
3. **GLM-5 timeout & max tokens:** Gunakan `CONCIERGE_TIMEOUT_SEC=600` dan `CONCIERGE_MAX_TOKENS=5000` (nilai dari `.env.example`, bukan nilai lama di CLAUDE.md).
4. **Modal SDK tidak diinstall.** Koneksi GLM-5 cukup via `openai` SDK dengan `base_url=settings.MODAL_BASE_URL`.
5. **RL Training (Phase 7) dilakukan di Google Colab, bukan di VPS.** Lihat detail alur di Phase 7.

---

## 📦 PHASE 0: Scaffolding, Config & Database (Estimasi: 1-2 Hari)
*Tujuan: Membangun pondasi, memastikan Environment Variables aman, dan skema DB siap.*

- [ ] **0.1** Buat struktur folder persis seperti ini:
│ ```text
│ project-root/
│ ├── .env
│ ├── .gitignore (WAJIB masukkan *.env, data/, __pycache__/, venv/)
│ ├── src/
│ ││ │├── __init__.py
│ ││ │├── main.py
│ ││ │├── config/
│ ││ │││ │├── __init__.py
│ ││ │││ │└── settings.py        # Pydantic Settings
│ ││ │├── data/
│ ││ │││ │├── __init__.py
│ ││ │││ │├── storage.py         # SQLAlchemy Models & Session
│ ││ │││ │├── ohlcv_fetcher.py
│ ││ │││ │└── onchain_fetcher.py
│ ││ │├── agents/
│ ││ │││ │├── __init__.py
│ ││ │││ │├── math/              # Agent 1-7
│ ││ │││ │└── llm/               # Agent 8-10
│ ││ │├── indicators/
│ ││ │││ │├── __init__.py
│ ││ │││ │├── luxalgo_smc.py
│ ││ │││ │└── mean_reversion.py
│ ││ │├── telegram/
│ ││ │││ │├── __init__.py
│ ││ │││ │├── bot.py
│ ││ │││ │└── commands.py
│ ││ │└── utils/
│ ││ │   │├── __init__.py
│ ││ │   │├── rate_limiter.py
│ ││ │   │└── logger.py
│ ├── tests/
│ └── data/                      # Lokal DB
│ ```
- [ ] **0.2** Implementasi `src/config/settings.py` mengikuti aturan `ENV_AND_SECRETS_RULE.md` (Gunakan `pydantic-settings`, `SecretStr`, `HttpUrl`). *Pastikan ada variable `FUTURES_MARGIN_TYPE`, `FUTURES_DEFAULT_LEVERAGE`, dan `USE_TESTNET`.*
- [ ] **0.3** Implementasi `src/data/storage.py` (SQLAlchemy):
│ - Tabel `ohlcv_h1`, `ohlcv_h4`, `ohlcv_15m`
│ - Tabel `paper_trades` (id, pair, side, entry_price, sl, tp, size, leverage, status, pnl, timestamp)
│ - Tabel `trade_logs`
- [ ] **0.4** Implementasi `src/utils/logger.py` (Loguru setup).
- [ ] **0.5** Pastikan `python -c "from src.config.settings import settings; print(settings.EXECUTION_MODE)"` berhasil tanpa error.

---

## 📦 PHASE 1: Data Engine, Rate Limiter & Safety Checks (Estimasi: 2-3 Hari)
*Tujuan: Sistem bisa mengambil data dari Binance Futures dengan aman, plus memasang 2 fitur "Pengaman" wajib.*

- [ ] **1.1** Implementasi `src/utils/rate_limiter.py` (Sliding window, max 800 req/min).
- [ ] **1.2** Implementasi `src/data/ohlcv_fetcher.py` (Fetch H4, H1, 15m via `ccxt.binanceusdm()`, simpan ke DB, wajib bungkus dengan Rate Limiter).
- [ ] **1.3** **(KRITIS)** Implementasi **Gap Detector** di `ohlcv_fetcher.py`: Cek selisih timestamp candle terakhir di DB dengan candle baru. Jika gap > 16 menit, LOG ERROR dan return `None` (jangan proses data).
- [ ] **1.4** **(KRITIS)** Implementasi **Session Filter** di `ohlcv_fetcher.py`: Hanya return data jika Waktu UTC berada di range London Open (07:00-10:00 UTC) atau New York Open (13:00-16:00 UTC). Jika di luar itu, return flag `SKIP_TRADE=True`.
- [ ] **1.5** Buat `tests/test_fetcher.py` untuk memastikan Gap Detector dan Session Filter bekerja benar.

---

## 📦 PHASE 2: Porting Indikator & Validasi (BLOCKING - Estimasi: 3-5 Hari)
*Tujuan: Menerjemahkan logika PineScript ke Python. JANGAN LANJUT KE PHASE 2.5 sebelum validasi ini selesai.*

- [ ] **2.1** Implementasi `src/indicators/helpers.py` (ATR, Swing High/Low logic).
- [ ] **2.2** Implementasi `src/indicators/luxalgo_smc.py`. **Scope terbatas — hanya 3 fungsi:**
│ - `detect_order_blocks(df)` → dari logika `storeOrderBlock` + `deleteOrderBlocks`
│ - `detect_fvg(df)` → dari tipe `fairValueGap` + detection logic
│ - `detect_bos_choch(df)` → dari `displayStructure` (bagian `ta.crossover/crossunder`)
│ - **SKIP** semua fitur visual: drawing boxes, labels, equal highs/lows, premium/discount zones.
│ - *Catatan: Gunakan 0-based indexing, hati-hati shift dari PineScript 1-based.*
- [ ] **2.3** Implementasi `src/indicators/mean_reversion.py` (RSI, Bollinger Bands).
- [ ] **2.4** **VALIDASI MANUAL:** Ambil data historis 100 baris dari TradingView (CSV). Bandingkan output Python dengan TradingView. Jika ada selisih di atas `0.001`, **HENTIKAN** dan perbaiki bug.

---

## 📦 PHASE 2.5: Backtest Engine & Validasi Strategi SMC (BLOCKING - Estimasi: 2-3 Hari)
*Tujuan: Memvalidasi apakah strategi SMC profitable secara historis sebelum lanjut ke Phase 3.*
*JANGAN LANJUT KE PHASE 3 jika win rate backtest di bawah 45%.*

### Mengapa Phase ini ada?
Daripada menunggu 30 hari paper trade untuk tahu strategi layak atau tidak, kita validasi dulu dengan data historis nyata dari Binance. Lebih cepat, lebih hemat waktu.

### Download Data Historis

- [ ] **2.5.1** Buat script `scripts/download_historical.py`:
│ - Source: `https://data.binance.vision` (data resmi Binance, gratis, tanpa API key)
│ - Download OHLCV Futures untuk pasangan utama (default: `BTCUSDT`)
│ - Timeframe yang dibutuhkan: `15m`, `1h`, `4h`
│ - Range: minimal 1 tahun ke belakang (lebih banyak = lebih akurat)
│ - Format output: CSV → simpan ke `data/historical/`
│ - Contoh URL: `https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/15m/BTCUSDT-15m-2024-01.zip`
│ - Script wajib otomatis unzip dan gabungkan semua file bulanan jadi 1 CSV per timeframe.

- [ ] **2.5.2** Buat `scripts/load_historical_to_db.py`:
│ - Baca CSV dari `data/historical/`
│ - Insert ke tabel `ohlcv_15m`, `ohlcv_h1`, `ohlcv_h4` yang sudah ada
│ - Gunakan `get_session()` dari `storage.py` — DILARANG raw SQL
│ - Tampilkan progress: berapa candle berhasil diinsert

### Backtest Engine

- [ ] **2.5.3** Buat `src/backtest/engine.py`:
│ - Load data dari DB (bukan live fetch)
│ - Jalankan pipeline indikator Phase 2 (SMC + Mean Reversion) terhadap data historis
│ - Simulasi entry/exit berdasarkan sinyal — gunakan logika yang **sama persis** dengan yang akan dipakai di Phase 3
│ - Hitung SL/TP berdasarkan ATR (sama dengan `risk_agent.py` nanti)
│ - Output wajib berupa Pydantic Model `BacktestResult`:
│   ```python
│   class BacktestResult(BaseModel):
│       total_trades: int
│       win_rate: float          # 0.0 - 1.0
│       avg_rr: float            # Average Risk/Reward ratio
│       max_drawdown: float      # Dalam persentase
│       profit_factor: float     # Gross profit / Gross loss
│       sharpe_ratio: float
│       total_pnl_pct: float     # Total PnL dalam persentase
│   ```

- [ ] **2.5.4** Buat `scripts/run_backtest.py`:
│ - Entry point untuk menjalankan backtest dari CLI
│ - Print hasil `BacktestResult` ke terminal dalam format yang readable
│ - Simpan hasil ke `data/backtest_results/backtest_{timestamp}.json`

- [ ] **2.5.5** **GATE CHECK — WAJIB SEBELUM LANJUT KE PHASE 3:**
│ Backtest dianggap LULUS jika memenuhi semua kriteria berikut:
│ - Win rate ≥ **45%**
│ - Profit factor ≥ **1.2**
│ - Max drawdown ≤ **30%**
│ - Total trades ≥ **50** (data cukup untuk statistik valid)
│
│ Jika GAGAL: perbaiki parameter indikator atau logika entry/exit di Phase 2, lalu ulangi backtest.
│ **JANGAN lanjut ke Phase 3 sebelum gate check ini LULUS.**

---

## 📦 PHASE 3: Math Agents (Logic Only) (Estimasi: 3-4 Hari)
*Tujuan: Membangun 7 Agent Python murni. DILARANG mengimpor `openai`, `groq`, atau library LLM apapun di phase ini.*

- [ ] **3.1** Buat Base Class di `src/agents/math/base_agent.py` (Menerima OHLCV, mengembalikan Pydantic Model).
- [ ] **3.2** `src/agents/math/trend_agent.py`: Membaca DB H4, menentukan `BULLISH`, `BEARISH`, `RANGING`.
- [ ] **3.3** `src/agents/math/reversal_agent.py`: Membaca DB H1, memanggil fungsi dari `indicators/luxalgo_smc.py` dan `mean_reversion.py`. Output: Signal + Confidence (0-100).
- [ ] **3.4** `src/agents/math/confirmation_agent.py`: Membaca DB 15m, cek apakah mendukung sinyal H1.
- [ ] **3.5** `src/agents/math/copytrade_agent.py`: Fetch API Binance Copy Trading, parse ke format Pydantic Model.
- [ ] **3.6** `src/agents/math/risk_agent.py`: Membaca config, WAJIB menghitung SL/TP berdasarkan ATR, membaca Leverage dari Settings.
- [ ] **3.7** `src/agents/math/execution_agent.py`: Mode Paper (Hanya `INSERT INTO paper_trades` status `OPEN`). **DILARANG** ada kode `exchange.create_order` di sini.

---

## 📦 PHASE 4: LLM Agents Integration (Estimasi: 2-3 Hari)
*Tujuan: Menghubungkan otak AI ke sistem dengan perlakuan berbeda untuk setiap model.*

- [ ] **4.1** Implementasi `src/agents/llm/analyst_agent.py`:
│ - Gunakan library `openai` (karena Cerebras/Groq kompatibel OpenAI SDK).
│ - Baca env: endpoint, API key, model dari `settings`.
│ - Temperature **0.0**, `response_format={"type": "json_object"}`.
│ - **WAJIB** ada `try-except` fallback ke Rule-Based logic jika API down/timeout.
- [ ] **4.2** Implementasi `src/agents/llm/commander_agent.py`:
│ - Setup sama seperti Analyst (Groq Llama 8B). Temp 0.0.
│ - Tugasnya menerima string dari Telegram, mengembalikan nama fungsi Python yang harus dieksekusi.
- [ ] **4.3** Implementasi `src/agents/llm/concierge_agent.py`:
│ - Koneksi ke Modal GLM-5 via `openai` SDK + `base_url=str(settings.MODAL_BASE_URL)`.
│ - **TIDAK PERLU install Modal SDK** — cukup openai SDK.
│ - Temperature **0.7**. Timeout: `settings.CONCIERGE_TIMEOUT_SEC`. Max tokens: `settings.CONCIERGE_MAX_TOKENS`.
│ - **DILARANG KERAS:** Jangan gunakan `json.loads()` atau `response_format={"type": "json_object"}`. GLM-5 adalah reasoning model.
│ - Ambil raw text `response.choices[0].message.content` dan langsung kirim ke Telegram.
│ - **WAJIB:** Implementasikan Concurrency Lock (jika GLM-5 sedang memproses, tolak chat baru selama durasi timeout).

---

## 📦 PHASE 5: Paper Execution, SL/TP Manager & Telegram Bot (Estimasi: 3-4 Hari)
*Tujuan: Menyatukan semua jadi 1 siklus utuh di `main.py`.*

- [ ] **5.1** Implementasi `src/agents/math/sltp_manager.py`:
│ - **HANYA BERLAKU UNTUK PAPER TRADE.**
│ - Loop: `SELECT * FROM paper_trades WHERE status='OPEN'`.
│ - Bandingkan Harga Close 15m saat ini dengan SL/TP.
│ - Jika kena, `UPDATE status='CLOSED'`, hitung PnL.
- [ ] **5.2** Implementasi `src/telegram/bot.py` dan `commands.py`:
│ - Route pesan user ke `CommanderAgent` atau `ConciergeAgent`.
│ - Implementasi handler untuk output `CommanderAgent`.
- [ ] **5.3** Implementasi `src/main.py` (The Orchestrator):
│ - Gunakan `APScheduler`.
│ - Loop 15 menit: Fetch Data -> Run Math Agents -> Run LLM Analyst -> Run Risk -> Run Execution -> Run SLTP Manager.
- [ ] **5.4** **STRESS TEST:** Jalankan di VPS selama 24 jam. Pantau RAM (jangan sampai *memory leak*), pastikan tidak crash.

---

## 📦 PHASE 6: VPS Deployment (Estimasi: 1 Hari)
*Tujuan: Pindah ke server 24/7.*

- [ ] **6.1** Whitelist IP VPS di Binance API Management.
- [ ] **6.2** Buat file `/etc/systemd/system/crypto-agent.service`.
- [ ] **6.3** Run `PAPER MODE` di VPS selama minimal **2 minggu** untuk mengumpulkan data trade nyata.

---

## 📦 PHASE 7: Reinforcement Learning — Google Colab (Estimasi: 3-5 Hari)
*Tujuan: Melatih model RL menggunakan data paper trade dari Phase 6.*
*⚠️ TRAINING DILAKUKAN DI GOOGLE COLAB, BUKAN DI VPS. VPS hanya untuk deploy model hasil training.*

### Kenapa Colab, bukan VPS?
VPS 4 vCPU / 8GB RAM terlalu kecil untuk training PyTorch. Jika dipaksakan, bot trading bisa crash OOM. Colab menyediakan GPU T4 gratis yang jauh lebih cepat dan zero risiko ke VPS.

### Alur Kerja Phase 7

- [ ] **7.1** **Export data dari VPS:**
│ ```bash
│ # Di VPS — jalankan script ini untuk export paper trade ke CSV
│ python scripts/export_trade_data.py
│ # Output: data/export/paper_trades_{timestamp}.csv
│ # Download file ini ke lokal, lalu upload ke Google Colab
│ ```

- [ ] **7.2** Buat `scripts/export_trade_data.py`:
│ - Query semua `paper_trades` dengan `status='CLOSED'` dari SQLite
│ - Export ke CSV dengan kolom: pair, side, entry_price, sl, tp, pnl, leverage, timestamp
│ - Minimum 100 closed trades sebelum training (data kurang = model tidak valid)

- [ ] **7.3** Implementasi `src/rl/trading_env.py` (Custom `gymnasium.Env`):
│ - *File ini ditulis di repo tapi dijalankan di Colab*
│ - Observation space: output indikator SMC + mean reversion
│ - Action space: LONG / SHORT / SKIP
│ - Reward: PnL aktual dari paper trade history

- [ ] **7.4** Implementasi `src/rl/train.py` (Menggunakan `stable-baselines3` PPO):
│ - *Dijalankan di Colab — bukan di VPS*
│ - Load CSV paper trade dari **7.1**
│ - Training dengan `PPO` algorithm
│ - Save model terbaik ke `data/rl_models/best_model.zip`

- [ ] **7.5** **Di Google Colab:**
│ 1. Upload `paper_trades_{timestamp}.csv` ke Colab
│ 2. Clone repo atau upload `src/rl/` ke Colab
│ 3. Install: `pip install gymnasium stable-baselines3 torch pandas`
│ 4. Jalankan `train.py`
│ 5. Download `best_model.zip` dari Colab

- [ ] **7.6** **Upload model ke VPS:**
│ ```bash
│ # Di lokal/Termux — upload model ke VPS
│ scp best_model.zip root@vps-ip:/path/to/project/data/rl_models/
│ ```

- [ ] **7.7** Integrasikan model ke `analyst_agent.py` sebagai salah satu input keputusan.

---

## 📦 PHASE 8: Go Live & User Data WS (Estimasi: 3 Hari)
*Tujuan: Menggunakan uang asli (Futures) dengan pengamanan maksimal tanpa OCO.*

- [ ] **8.1** Ubah `.env`: `EXECUTION_MODE=live`. Pastikan `USE_TESTNET=False`.
- [ ] **8.2** Ubah `execution_agent.py`:
│ - **DILARANG MENGGUNAKAN `type='OCO'` (Tidak didukung di Futures).**
│ - Sebelum entry, WAJIB jalankan: `exchange.set_leverage()` dan `exchange.set_margin_mode('isolated')`.
│ - Kirim Entry Order (Market/Limit).
│ - **SEGERA setelah Entry**, kirim **2 order terpisah secara berurutan**:
│ │ 1. `exchange.create_order(symbol, 'stop_market', 'sell', amount, params={'stopPrice': sl_price, 'closePosition': True})`
│ │ 2. `exchange.create_order(symbol, 'take_profit_market', 'sell', amount, params={'stopPrice': tp_price, 'closePosition': True})`
- [ ] **8.3** Nonaktifkan `sltp_manager.py` (SL/TP sudah diserahkan ke Binance server).
- [ ] **8.4** Implementasi `src/data/ws_user_stream.py`:
│ - Gunakan library `websockets` terhubung ke **User Data Stream** Binance.
│ - **BUKAN market data stream** — hanya mendengarkan event `ORDER_TRADE_UPDATE`.
│ - Jalankan sebagai `threading.Thread(daemon=True)` agar tidak memblokir loop 15 menit.
│ - Jika menerima status `FILLED`, update DB `paper_trades` jadi `CLOSED` dan kirim notifikasi Telegram.
- [ ] **8.5** Soft launch: gunakan `USE_TESTNET=True` + Leverage 1-2 + modal kecil di Testnet dulu.
- [ ] **8.6** Jika Testnet mulus 48 jam tanpa error → set `USE_TESTNET=False` untuk Mainnet.

---

## 📋 SUCCESS METRICS SEBELUM NAIK KE LIVE

Sebelum mengubah `EXECUTION_MODE=live`, syarat wajib:
1. Backtest Phase 2.5 **LULUS** gate check (win rate ≥ 45%, profit factor ≥ 1.2).
2. Sistem berjalan tanpa crash selama **30 hari** di VPS paper mode.
3. Win rate paper trade di atas **50%** dengan estimasi slippage 0.1%.
4. Kode SL/TP Order sudah ditest di **Binance Testnet** tanpa error.

---
*(File ini di-update dari versi awal. Architecture Addendum di bagian atas berlaku sebagai override untuk semua konflik dengan versi sebelumnya.)*

