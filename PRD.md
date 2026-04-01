
Ini adalah **PRD.md Final Version (Locked)** yang langsung bisa kamu copy-paste ke repo:

---

# 📄 PRD.md — Crypto Multi-Agent Trading System

## 1. Product Overview
Sistem *trading bot* otonom berbasis *multi-agent* yang berjalan 24/7 di VPS (Contabo: 4 vCPU, 8GB RAM, 75GB NVMe). Sistem memisahkan secara tegas antara **Logika Matematika murni (Python)** untuk perhitungan indikator, dan **Kognitif (LLM)** untuk penalaran akhir dan interface pengguna. Fase pertama berjalan dalam mode *Paper Trading* (simulasi), sebelum bermigrasi ke *Live Trading* dengan mekanisme *server-side risk management*.

## 2. Goals & Non-Goals

**Goals:**
- Membangun pipeline data end-to-end menggunakan **REST API** (tanpa *Market Data WebSocket*).
- Mengimplementasikan 7 Agen Matematika dan 3 Agen LLM dengan pembagian tugas yang sangat ketat.
- Memvalidasi akurasi porting PineScript LuxAlgo SMC ke Python (selisih max 0.001).
- Menjalankan *Paper Trade* yang realistis dengan memahami batasan *15-minute candle close*.
- Mengamankan eksekusi *Live Trading* di masa depan menggunakan **2 Stop order terpisah (TP & SL)** dan **User Data WebSocket**.
- Sistem full futures baik saat Paper maupun Live

**Non-Goals (Strictly Prohibited):**
- ❌ **TIDAK** menggunakan WebSocket untuk menerima *stream* data harga (Market Data WS).
- ❌ **TIDAK** menggunakan LLM (dalam kondisi apapun) untuk menghitung indikator teknikal (RSI, SMC, ATR).
- ❌ **TIDAK** membiarkan bot memonitor harga secara manual untuk mengeksekusi Cut Loss di *Live Trading* (Gunakan Entry Order + 2x Stop/TP Market Order terpisah).
- ❌ **TIDAK** menggunakan dynamic position sizing atau risk management yang berubah-ubah.
- ❌ **TIDAK** tidak menggunakan spot trading.

---

## 3. Functional Requirements

### FR-1: Data Collection & Safety Layer
- **FR-1.1:** Fetch OHLCV (H4, H1, 15m) menggunakan `ccxt` REST API setiap 15 menit (di-menit ke-00), dibungkus *Rate Limiter* (Maks 800 req/menit).
- **FR-1.2 (Gap Detector):** Sistem wajib membandingkan timestamp candle terakhir di DB dengan candle baru. Jika terdapat *gap* lebih dari 16 menit, sistem **wajib membatalkan** analisis pada siklus itu untuk mencegah error pada indikator.
- **FR-1.3 (Session Filter):** Sistem wajib menolak untuk menghasilkan sinyal *trade* di luar jam volatilitas tinggi. Sinyal hanya boleh dihasilkan jika waktu UTC berada dalam range: **London Open (07:00 - 10:00 UTC)** atau **New York Open (13:00 - 16:00 UTC)**.
- **FR-1.4:** Fetch status *Copy Trade* dari Binance API dan data On-Chain (DefiLlama) sebagai pelengkap konteks.

### FR-2: Math Agents (Pure Python - No LLM Allowed)
- **FR-2.1 (Trend Agent):** Menganalisis candle H4. Output: `BULLISH`, `BEARISH`, `RANGING`.
- **FR-2.2 (Reversal Agent):** Menganalisis candle H1 menggunakan **Python murni** yang memanggil fungsi LuxAlgo SMC (Order Block, FVG, BOS/CHOCH) dan Mean Reversion (RSI, Bollinger). Output: Sinyal + Confidence Score (0-100).
- **FR-2.3 (Confirmation Agent):** Menganalisis candle 15m untuk validasi pola terhadap sinyal H1. Output: `CONFIRMED` / `REJECTED`.
- **FR-2.4 (Copy Trade Agent):** Parse sinyal dari Binance Copy Trading API.
- **FR-2.5 (Risk Manager Agent):** Membaca parameter statis dari config (Max Drawdown, Risk %, Max Position). Menghitung Position Size dan SL/TP berdasarkan ATR.

### FR-3: LLM Agents (Cognitive Layer)
- **FR-3.1 (The Analyst):**
  - **Model:** Cerebras (Qwen-3-235B-A22B). **Temperature: 0.0.** Mode: JSON.
  - **Tugas:** Menerima output dari Math Agents dan On-Chain. Mengambil keputusan final (`LONG`, `SHORT`, `SKIP`) berdasarkan *confluence*.
  - **Constraint:** Jika API gagal/disconnected, **wajib fallback** ke Rule-Based Python (`if/else`) tanpa menghentikan siklus 15 menit.
- **FR-3.2 (The Commander):**
  - **Model:** Groq (Llama-3.1-8b-instant). **Temperature: 0.0.** Mode: JSON.
  - **Tugas:** Menerjemahkan perintah tidak terstruktur dari Telegram user menjadi fungsi Python yang bisa dieksekusi (misal: `/close_all`).
- **FR-3.3 (The Concierge):**
  - **Model:** Modal (GLM-5 FP8). **Temperature: 0.8.** Mode: Chat (Max Output: 500 tokens).
  - **Tugas:** Interface ngobrol dengan persona tertentu. Diperbolehkan membaca DB `paper_trades` untuk menjawab pertanyaan performa. **DILARANG** mengakses API Keys atau mengeksekusi perintah sistem.

### FR-4: Execution Layer
- **FR-4.1 (Paper Mode):** **DILARANG** memanggil endpoint Binance Order. Simpan entry ke SQLite (`status: OPEN`).
- **FR-4.2 (Paper SL/TP Check):** Setiap 15 menit, cek Harga Close candle terhadap SL/TP. Jika tersentuh, update DB ke `CLOSED`. *(Catatan: Win rate Paper Trade akan terlihat lebih bagus dari Live karena pengecekan ini hanya di batas candle, bukan intra-candle).*
- **FR-4.3 (Live Mode - Future):** Sistem **WAJIB** mengirim perintah **Entry Order + 2x Stop/TP Market Order terpisah** ke Binance saat entry, bukan memonitor harga secara manual. SL/TP dijamin dieksekusi tepat oleh server Binance.
- **FR-4.4 (Live Monitoring - Future):** Menggunakan **User Data WebSocket** (bukan Market WS) yang berjalan di *Background Thread* untuk menerima notifikasi *Order Filled* dari Binance, yang kemudian hanya bertugas meng-update status di SQLite.

### FR-5: Telegram Interface
- **FR-5.1:** Router pesan yang mampu mendeteksi apakah pesan user adalah *Command* (diteruskan ke Commander) atau *Chat* (diteruskan ke Concierge).
- **FR-5.2:** Mengirim notifikasi struktural: `🔔 Paper Entry`, `✅ TP Hit `, `❌ SL Hit`.

---

## 4. System Architecture Constraints (Mandatory for Developer)

1. **VPS Resource:** CPU dan RAM harus dijaga efisien. Tidak ada model LLM yang boleh di-*download* atau dijalankan secara lokal di VPS ini (semua LLM via API eksternal).
2. **Concurrency:** Siklus utama (15 menit) dan pendengar WS (jika Live) **wajib** berjalan di *thread* yang terpisah (`threading.Thread(daemon=True)`). WS tidak boleh memblokir loop utama.
3. **Error Resilience:** Jika layanan LLM (Cerebas/Groq/Modal) down, bot tetap harus bisa melakukan Paper Trade menggunakan logika Rule-Based default.

---

## 5. Success Metrics untuk Naik ke Fase Live

Sebelum mengubah `.env` ke `EXECUTION_MODE=live`, syarat wajib:
1. Sistem berjalan tanpa *crash* (OOM/CPU Spike) selama **30 hari berturut-turut** di VPS.
2. *Gap Detector* dan *Session Filter* terbukti membatalkan analisis dengan benar saat dikondisikan demikian.
3. Win rate *paper trade* di atas **50%** dengan memperhitungkan *slippage* estimasi 0.1%.
4. Kode untuk pengiriman **Entry Order + 2x Stop/TP Market Order terpisah** sudah ditulis dan berhasil di-*test* di **Binance Testnet** (bukan main net) tanpa error.
