# Phase 3 — Validasi Strategi
**Target: KR3 | Timeline: Minggu 3-5**
**Dependency: Phase 1 & 2 harus selesai dulu**

---

## Goal Phase Ini
30 closed trades testnet dengan data bersih, RR 1:3, win rate ≥ 55%,
dan net PnL aggregate positif. Hasil ini jadi dasar keputusan masuk mainnet.

---

## Step 1 — Set Baseline & Start Date

**Estimasi waktu:** 15 menit
**Risk:** Low

Setelah Phase 1 selesai dan audit data historis dilakukan, catat:

```
KR3 Start Date  : [isi tanggal Phase 1 selesai]
Trades counted  : 0 / 30
Valid trades    : hanya entry_timestamp >= start date
                  DAN execution_mode = 'testnet'
                  DAN RR = 1:3
```

> **Penting:** Jangan hitung trades sebelum Phase 1 selesai.
> Data lama mungkin punya RR 1:1 atau execution_mode NULL.

Tambah di `/stats` command — tampilkan progress KR3:

```
🎯 KR3 Progress
Closed testnet trades : 5 / 30
Since                 : 2026-05-01
Win Rate              : 60.0% (3W/2L)
Net PnL               : +$8.20
Status                : ON TRACK ✅
```

---

## Step 2 — Monitor Signal Frequency (Minggu ke-3)

**Estimasi waktu:** Ongoing
**Risk:** Medium — kalau signal terlalu jarang, KR3 tidak tercapai tepat waktu

### Decision point di akhir Minggu ke-3

Hitung: berapa trade masuk per minggu sejak start date?

```
Scenario A: ≥ 3 trade/minggu
→ On track. Tidak perlu ubah apapun.
→ 30 trades dalam ~10 minggu, tapi target kita 5 minggu
→ Kalau frekuensi bagus (5+/minggu), target bisa lebih cepat

Scenario B: 1-2 trade/minggu
→ Pertimbangkan relax confidence threshold: 60% → 55%
→ Test dulu selama 1 minggu, monitor apakah win rate turun signifikan
→ Kalau win rate tetap ≥ 55%, pertahankan di 55%

Scenario C: < 1 trade/minggu
→ Signal terlalu jarang — kemungkinan market sedang sideways atau
  pairs yang dipilih kurang volatile
→ Pertimbangkan tambah 1-2 pairs yang lebih aktif (SOLUSDT, DOGEUSDT)
→ Jangan tambah lebih dari 2 pair sekaligus
```

### Query untuk cek frekuensi

```python
from datetime import UTC, datetime, timedelta
from src.data.storage import PaperTrade, get_session

KR3_START_DATE = datetime(2026, 5, 1, tzinfo=UTC)  # ganti dengan tanggal aktual

with get_session() as db:
    trades = db.query(PaperTrade).filter(
        PaperTrade.execution_mode == 'testnet',
        PaperTrade.entry_timestamp >= KR3_START_DATE,
        PaperTrade.status.in_(['OPEN', 'CLOSED', 'PENDING_ENTRY']),
    ).all()

    weeks_elapsed = (datetime.now(UTC) - KR3_START_DATE).days / 7
    trades_per_week = len(trades) / max(weeks_elapsed, 0.1)

    print(f"Total trades: {len(trades)}")
    print(f"Weeks elapsed: {weeks_elapsed:.1f}")
    print(f"Trades/week: {trades_per_week:.1f}")
```

---

## Step 3 — Evaluasi di 15 Trades (Midpoint Check)

**Estimasi waktu:** 1 jam review
**Risk:** Low — pure analysis, tidak ada code change

Saat 15 trades pertama selesai (setengah jalan), lakukan evaluasi:

### Metrik yang dievaluasi

| Metrik | Minimum | Target |
|--------|---------|--------|
| Win Rate | ≥ 50% | ≥ 55% |
| Net PnL aggregate | > 0 | +$20 |
| Avg net PnL/trade | > -$0.50 | > +$1.00 |
| Max drawdown | < $20 | < $10 |
| Fee/PnL ratio | < 30% | < 15% |

### Interpretasi hasil

**Jika semua metrik di atas minimum:**
→ Lanjut ke 30 trades, tidak perlu ubah strategi.

**Jika win rate < 50% tapi net PnL positif:**
→ Mungkin ada beberapa loss besar yang offset banyak small wins.
→ Cek distribusi PnL — apakah ada outlier? Review trades yang loss.

**Jika win rate ≥ 55% tapi net PnL negatif:**
→ Fee terlalu besar relatif ke profit per trade.
→ Cek apakah position size terlalu kecil untuk mengcover fee.
→ Dengan RR 1:3 dan win rate 55%, ini seharusnya tidak terjadi — ada yang salah di kalkulasi.

**Jika keduanya di bawah minimum:**
→ Stop counting, review strategi dulu.
→ Kemungkinan: signal quality turun, atau market regime berubah.
→ Jangan lanjut ke mainnet sampai 15 trades berikutnya menunjukkan perbaikan.

---

## Step 4 — Final Evaluation di 30 Trades

**Estimasi waktu:** 2 jam review
**Risk:** Decision point — salah keputusan bisa costly

### Kriteria GO / NO-GO mainnet

**GO jika semua terpenuhi:**
- [ ] Win rate ≥ 55% dari 30 trades
- [ ] Net PnL aggregate > $0
- [ ] Tidak ada bug aktif yang belum di-fix
- [ ] KR1 dan KR2 sudah selesai (data bisa dipercaya)
- [ ] Max drawdown dalam satu bulan < 30% dari modal testnet

**NO-GO jika salah satu dari ini terjadi:**
- Win rate < 50%
- Net PnL aggregate negatif
- Ada trades dengan data tidak lengkap (NULL net_pnl)
- Ada bug yang masih aktif

**CONDITIONAL GO (masuk mainnet dengan size minimal):**
- Win rate 50-55% tapi net PnL positif dan trending up
- Dalam kondisi ini: mulai mainnet dengan risk $1/trade, bukan $5

---

## Step 5 — Persiapan Mainnet (kalau GO)

**Estimasi waktu:** 1-2 hari
**Risk:** High — ini uang nyata

### Config yang perlu dicek ulang sebelum mainnet

```json
{
  "trading": {
    "risk_per_trade_usd": 1.0,     // Start kecil dulu, naikkan bertahap
    "risk_reward_ratio": 3.0,      // Sudah benar
    "leverage": 5,                  // Pertahankan
    "max_open_positions": 1        // Pertahankan untuk fase awal
  },
  "system": {
    "use_testnet": false,          // Switch ke mainnet
    "confirm_mainnet": true        // Wajib true untuk live mainnet
  }
}
```

### Checklist sebelum switch ke mainnet

- [ ] API key mainnet sudah di-set di .env
- [ ] `confirm_mainnet: true` di config
- [ ] Risk per trade diturunkan ke $1 untuk fase pertama
- [ ] DB di-backup
- [ ] Telegram notification sudah terkirim dengan benar
- [ ] `/stats` command sudah bisa bedakan testnet vs mainnet
- [ ] Kill switch tested dan berfungsi
- [ ] Bot sudah jalan stabil minimal 1 minggu tanpa restart manual

### Fase mainnet yang disarankan

```
Minggu 1-2  : Risk $1/trade, monitor ketat
Minggu 3-4  : Kalau profitable, naikkan ke $2/trade
Bulan 2+    : Naikkan bertahap sesuai performa aktual
```

---

## Checklist KR3

- [ ] Start date dicatat dan dipakai sebagai filter
- [ ] Signal frequency dicek di akhir minggu ke-3
- [ ] Midpoint check dilakukan di trade ke-15
- [ ] Final evaluation dilakukan di trade ke-30
- [ ] Keputusan GO/NO-GO/CONDITIONAL GO dibuat berdasarkan data
- [ ] Kalau GO: config mainnet sudah disiapkan dengan risk kecil
