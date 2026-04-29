# Risks, Mitigations & Decision Log

---

## Pre-Mortem: Top Risks

### Risk 1 — Data historis terkontaminasi (CRITICAL)
**Probabilitas:** Tinggi — bug execution_mode NULL sudah terkonfirmasi ada

**Dampak:** KR3 dihitung dari data yang tidak bisa dipercaya → keputusan mainnet salah

**Mitigasi:**
- Jalankan audit script (Phase 1 Step 7) sebelum counting dimulai
- Hard rule: hanya hitung trades dengan `entry_timestamp >= KR3_START_DATE`
- KR3_START_DATE = tanggal Phase 1 selesai, bukan hari ini

**Status:** ⏳ Belum di-mitigasi — tunggu Phase 1

---

### Risk 2 — Win rate tidak representatif karena RR salah (CRITICAL)
**Probabilitas:** Sudah terjadi — RR 1:1 aktif saat ini

**Dampak:** Semua trades yang sudah ada dihitung dengan RR yang salah → tidak bisa dibandingkan dengan backtest

**Mitigasi:**
- Fix RR ke 1:3 di config.json **sekarang** (5 menit)
- Jangan hitung trades lama untuk KR3

**Status:** 🔴 Belum di-fix — ACTION REQUIRED

---

### Risk 3 — Signal terlalu jarang, 30 trades tidak tercapai tepat waktu
**Probabilitas:** Medium — strategi SMC dengan multi-filter memang ketat

**Dampak:** KR3 molor dari target Minggu ke-5 → delay masuk mainnet

**Mitigasi:**
- Decision point di Minggu ke-3 (Phase 3 Step 2)
- Opsi: relax confidence threshold 60% → 55%
- Cek terlebih dahulu sebelum tambah pairs baru

**Status:** ⏳ Monitor di Minggu ke-3

---

### Risk 4 — Migration DB corrupt data
**Probabilitas:** Low — tapi konsekuensinya tinggi

**Dampak:** Kehilangan data historis trade

**Mitigasi:**
- `backup_db()` wajib sebelum setiap migration
- Jalankan `check_db_integrity()` setelah migration
- Test migration di fresh DB dulu sebelum jalankan di DB live

**Status:** ⏳ Prosedur sudah ada, tinggal diikuti

---

### Risk 5 — Fee calculation tidak akurat di testnet
**Probabilitas:** Sudah terjadi — partial fills abnormal di testnet

**Dampak:** Evaluasi profitability misleading

**Mitigasi:** 
- Gunakan formula fee mainnet: `position_size × price × 0.0004 × 2`
- **Jangan** ambil fee dari testnet transaction history untuk evaluasi
- Fee yang di-track di DB menggunakan formula ini, bukan data Binance testnet

**Status:** ✅ Sudah disepakati, tinggal diimplementasi di Phase 1

---

### Risk 6 — Bot jalan tanpa monitoring, bug silent
**Probabilitas:** Medium — bot 24/7 di VPS

**Dampak:** Bug baru muncul tapi tidak ketahuan sampai banyak trades rusak

**Mitigasi:**
- Cek Telegram notification setiap hari minimal sekali
- Jika ada hari tanpa satu pun notification padahal market aktif → cek log VPS
- Set `/stats` routine harian — kalau angkanya aneh, investigasi

**Status:** ⏳ Habit yang perlu dibangun

---

## Decision Log

Catat setiap keputusan besar di sini untuk referensi ke depan.

### 2026-04-29 — RR diubah ke 1:3
**Keputusan:** `risk_reward_ratio` diubah dari 1.0 ke 3.0
**Alasan:** RR 1:1 adalah kesalahan dari fase testing eksekusi, bukan target strategi. Backtest menunjukkan RR 1:3 optimal. Dengan win rate 55%, RR 1:3 memberikan edge yang lebih jelas.
**Efek:** Trades lama dengan RR 1:1 tidak akan dihitung untuk KR3.

---

### 2026-04-29 — 50 trades diturunkan ke 30 trades untuk KR3
**Keputusan:** Sample size KR3 diturunkan dari 50 ke 30 trades
**Alasan:** Dengan strategi yang selective, 50 trades bisa butuh 4-6 bulan. 30 trades cukup untuk keputusan "layak masuk mainnet dengan size kecil" — bukan bukti definitif, tapi cukup untuk conditional GO.
**Trade-off:** Statistical significance lebih rendah. Mitigasi: mulai mainnet dengan risk minimal ($1/trade).

---

### 2026-04-29 — Paper mode tidak dihapus
**Keputusan:** Paper mode dipertahankan tapi dipisahkan secara tegas
**Alasan:** Paper mode berguna sebagai sandbox untuk test parameter baru sebelum testnet. Solusinya bukan hapus tapi isolasi — strict filter by execution_mode di semua queries dan reports.
**Efek:** Semua reporting harus filter by execution_mode, tidak boleh aggregate semua mode.

---

### 2026-04-29 — Fee dihitung dari actual commission WebSocket, bukan formula hardcode
**Keputusan:** Fee tracking menggunakan field `n` (commission) dari `ORDER_TRADE_UPDATE` WebSocket event yang sudah ada. Formula estimasi (`position_size × price × taker_fee_rate`) hanya sebagai fallback kalau WebSocket miss.
**Alasan:** Data actual dari Binance lebih akurat dari estimasi. WebSocket sudah subscribe dan tidak menambah rate limit. `taker_fee_rate` dipindah ke `config.json` (default 0.0004) supaya bisa diubah kalau ada BNB discount atau VIP tier.
**Trade-off:** Sedikit lebih kompleks karena perlu handle fallback — tapi tidak hardcore, ini opsi terbaik yang tersedia.
**Efek:** Fee di DB adalah angka actual dari exchange (di mainnet), bukan estimasi. Di testnet, fee actual juga tersedia tapi nilainya tidak representatif karena partial fills abnormal.

---

## Template untuk Decision Log Baru

```
### YYYY-MM-DD — [Judul Keputusan]
**Keputusan:** [Apa yang diputuskan]
**Alasan:** [Kenapa]
**Trade-off:** [Apa yang dikorbankan]
**Efek:** [Dampak ke sistem/data]
```
