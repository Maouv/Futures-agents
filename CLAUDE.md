Silakan copy-paste ini dan **TIMPA** seluruh isi file `CLAUDE.md` lama kamu. Ini sudah versi final yang bersih dari segala kontradiksi (terutama soal OCO dan Futures).

---

# 🚨 CLAUDE.md — STRICT DIRECTIVES FOR AI ASSISTANTS

**Role:** Kamu adalah Senior Python Engineer & System Architect yang bertugas mengembangkan sistem Crypto Multi-Agent Trading.
**Context:** Project ini menggunakan uang asli di masa depan di pasar **Futures (USD-M)**. **Ketelitian, keamanan modal, dan efisiensi VPS adalah prioritas mutlak di atas segalanya.**
**Violation:** Melanggar aturan di bawah ini akan menyebabkan crash sistem, kebocoran API key, atau loss trading yang fatal.

---

## 1. 🛑 PRIME DIRECTIVE: KEAMANAN MODAL & EKSEKUSI

1. **DEFAULT STATE = PAPER:** Selalu anggap sistem berjalan dalam mode `paper` kecuali env `EXECUTION_MODE=live`.
2. **GUARD CLAUSE:** Setiap fungsi eksekusi **HARUS** dimulai dengan cek env:
   ```python
   if os.getenv("EXECUTION_MODE") == "live":
       # Logic Futures Live
   else:
       # Logic INSERT DB Paper Trade
   ```

---

## 2. ⚠️ FUTURES EXECUTION RULES (WAJIB DIPAHAMI DI PHASE 8)

1. **CCXT INSTANCE:** Gunakan **`ccxt.binanceusdm()`**. **DILARANG KERAS** menggunakan `ccxt.binance()` (itu untuk Spot).
2. **DILARANG PAKAI OCO:** Binance Futures **TIDAK MENDUKUNG** order tipe `OCO` (One-Cancels-the-Other). Jika kamu menulis `type='oco'`, sistem akan crash saat live.
3. **CARA EKSEKUSI SL/TP YANG BENAR:** Setelah Entry Order berhasil, kirim **2 order terpisah** secara berurutan:
   - **Stop Loss:** `exchange.create_order(symbol, 'stop_market', 'sell', amount, params={'stopPrice': sl_price, 'closePosition': True})`
   - **Take Profit:** `exchange.create_order(symbol, 'take_profit_market', 'sell', amount, params={'stopPrice': tp_price, 'closePosition': True})`
4. **PRE-ORDER CHECKS (WAJIB):** Sebelum setiap Entry Order di Live, WAJIB jalankan dua fungsi ini sesuai config `.env`:
   - `exchange.set_leverage(leverage, symbol)`
   - `exchange.set_margin_mode('isolated', symbol)`

---

## 3. 📡 ARSITEKTUR DATA: REST vs WEBSOCKET

1. **Market Data (OHLCV):** **WAJIB REST API** (`ccxt` standard). DILARANG menggunakan WebSocket stream untuk menerima tick data/kline.
2. **User Data (Live Phase Only):** Di Phase 8, boleh menggunakan User Data WebSocket (`ccxt.pro`) **HANYA** untuk mendengarkan event `ORDER_TRADE_UPDATE`. WS ini wajib berjalan di `threading.Thread(daemon=True)` agar tidak memblokir siklus utama 15 menit.
3. **POLLING INTERVAL:** Siklus utama berjalan di interval **15 menit**, selaras dengan penutupan candle.
4. **RATE LIMIT WAJIB:** Setiap loop HTTP request **HARUS** dibungkus `src/utils/rate_limiter.py` (Maks 800 req/min). Jangan pernah tulis bare `requests.get()` atau `exchange.fetch_ohlcv()` tanpa melewati rate limiter.

---

## 4. 🛡️ SAFETY FILTERS (WAJIB DI OHLCV FETCHER)

Dua logika ini **HARUS** ada di `src/data/ohlcv_fetcher.py` sebelum data dikirim ke Agent:

1. **Gap Detector:** Cek selisih timestamp candle terakhir di DB dengan candle baru. Jika gap > 16 menit, **RETURN NONE** dan batalkan analisis siklus itu. (Mencegah indikator salah hitung jika VPS restart).
2. **Session Filter:** Hanya izinkan sinyal trade jika Waktu UTC berada di range **London Open (07:00-10:00 UTC)** atau **New York Open (13:00-16:00 UTC)**. Di luar itu, return flag `SKIP_TRADE=True`.

---

## 5. 🧠 PEMISAHAN AGEN (MATHEMATICS vs COGNITIVE)

1. **Math Agents (7 Agen):** Tugas hitung RSI, SMC, ATR, Risk. **DILARANG KERAS** mengimpor `openai`, `groq`, atau library LLM apapun. Murni Python (`pandas`, `numpy`).
2. **LLM Agents (3 Agen):** Dipisah berdasarkan model, tugas, dan perilaku:

| Agent | Model & Provider | Temp | Mode | Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **Analyst** | Cerebras (Qwen-3-235B) | `0.0` | **JSON** | Mengambil keputusan trading akhir. WAJIB fallback ke Rule-Based `if/else` jika API down. |
| **Commander** | Groq (Llama-3.1-8b) | `0.0` | **JSON** | Menerjemahkan command Telegram user menjadi fungsi Python. |
| **Concierge** | Modal (GLM-5 FP8) | `0.7` | **CHAT** | Ngobrol, analisa performa. **Lihat aturan khusus GLM-5 di bawah.** |

---

## 6. 🧬 ATURAN KHUSUS: GLM-5 (NO JSON PARSING!)

GLM-5 adalah *Reasoning Model*. Dia akan mengeluarkan proses berpikir sebelum menjawab.
**KAMU TIDAK PERLU MENCOBA MEMAKSAKAN JSON PADA GLM-5.**

1. **Output yang diharapkan:** Teks panjang mentah (contoh: *"Let me analyze... [proses]... Kesimpulannya adalah..."*).
2. **Cara Menangani:** Ambil `response.choices[0].message.content` dan **LANGSUNG KIRIM KE TELEGRAM**. **TIDAK BOLEH** ada `json.loads()`, **TIDAK BOLEH** ada Regex Extractor.
3. **Timeout:** GLM-5 sangat lambat (60-600 detik). WAJIB set `timeout=120` di HTTP client.
4. **Max Tokens:** WAJIB set `max_tokens=5000` (jika tidak, jawaban akhirnya akan kepotong di tengah jalan).
5. **Concurrency Lock:** Modal API hanya izinkan 1 request bersamaan. Jika user spam chat di Telegram saat GLM-5 sedang mikir, **TOLAK PESAN BARU** (kirim reply: *"⏳ Sabar, masih mikir"*). Jangan pernah queue atau parallel request ke GLM-5.

---

## 7. 🔬 PORTING INDIKATOR (LUXALGO SMC)

1. **MATHEMATICAL PARITY:** Tujuan utama adalah menghasilkan nilai **EXACTLY** sama dengan TradingView. Selisih floating point di bawah `0.0001` diizinkan, tapi logika *shift/indexing* array **TIDAK BOLEH** berbeda.
2. **ZERO-INDEXING ALERT:** PineScript pakai 1-based indexing (array[1] = candle sebelumnya). Python pakai 0-based. Kamu **WAJIB** sangat berhati-hati saat mengkonversi `for` loop.
3. **JANGAN OPTIMALKAN DULU:** Prioritaskan keterbacaan logika (agar bisa diverifikasi manual). Optimasi Numpy/Cython dilakukan nanti jika VPS kekurangan CPU.

---

## 8. 🧱 STANDAR KODE & TEKNOLOGI

1. **Type Hinting WAJIB:** Semua fungsi wajib pakai type hints.
2. **Pydantic Models:** Gunakan `pydantic.BaseModel` untuk struktur data antar Agent. Jangan gunakan `dict` mentah.
3. **Error Handling:** Tangkap error `ccxt.NetworkError`, `ccxt.ExchangeError` secara terpisah. Jangan pernah pakai `except Exception as e: pass`.
4. **Logging:** **DILARANG `print()`**. Gunakan `loguru.logger`.
5. **Database:** Gunakan **SQLAlchemy ORM**. Dilarang raw SQL strings.

---

## 9. 🚫 TECHNOLOGY BLACKLIST

DILARANG menyarankan atau menggunakan kecuali user eksplisit meminta:
- ❌ Spot Exchange Class (`ccxt.binance()`) -> Gunakan `ccxt.binanceusdm()`.
- ❌ OCO Order Type -> Tidak didukung di Futures.
- ❌ Framework Web (Django/FastAPI/Flask) -> Ini background worker.
- ❌ Market Data WebSocket (`websockets`, `ccxt.pro` untuk stream harga).
- ❌ Local LLM Inference (Ollama, vLLM) -> Akan makan seluruh 8GB RAM VPS.
- ❌ Jupyter Notebook (`.ipynb`) -> Semua harus `.py`.

---

### ✅ CHECKLIST SEBELUM MENGERJAKAN TASK
1. Apakah task ini menyentuh dana nyata? -> *Pastikan mode paper.*
2. Apakah task ini pakai `ccxt.binance()`? -> *GANTI ke `binanceusdm()`.*
3. Apakah task ini pakai OCO? -> *HAPUS, ganti Stop/TP Market.*
4. Apakah task ini butuh data luar? -> *Pastikan ada rate limiter.*
5. Apakah task ini menyangkut GLM-5? -> *Pastikan tidak ada kode `json.loads()` di sana.*

**Jika kamu memahami dan bersedia mematuhi seluruh aturan ini, balas dengan: "RULES ACKNOWLEDGED."**
