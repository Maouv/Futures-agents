# Futures Agent — Mainnet Readiness Plan

## Objective
**Sistem trading siap masuk mainnet dengan data yang bisa dipercaya dan strategi yang terbukti profitable setelah fee.**

---

## Key Results

| # | Key Result | Target | Deadline |
|---|-----------|--------|----------|
| KR1 | 100% trades testnet ter-record lengkap (execution_mode, actual fill price, fee, net_pnl) — zero NULL di field kritis | Zero NULL | Minggu ke-2 |
| KR2 | Telegram report pisahkan paper/testnet/mainnet secara eksplisit, menampilkan net PnL setelah fee yang akurat | Report live | Minggu ke-3 |
| KR3 | 30 closed trades testnet dengan win rate ≥ 55% dan net PnL aggregate positif, dengan RR 1:3 | 30 trades | Minggu ke-5 (target ke-4) |

---

## Timeline Overview

```
Minggu 1    Minggu 2    Minggu 3    Minggu 4    Minggu 5
────────    ────────    ────────    ────────    ────────
Phase 1     Phase 1     Phase 2     Phase 3     Phase 3
(Data)      (Data)      (Report)    (Validasi)  (Validasi)
   │           │           │           │           │
   ▼           ▼           ▼           ▼           ▼
Fix RR     Migration   Telegram    Counting    KR3 eval
Config     + Fee Track  /stats      trades      → mainnet?
```

---

## File Structure Plan Ini

```
00_OKR_OVERVIEW.md          ← File ini
01_PHASE1_DATA_INTEGRITY.md ← KR1: Schema, migration, fee tracking
02_PHASE2_OBSERVABILITY.md  ← KR2: Telegram report, /stats command
03_PHASE3_VALIDATION.md     ← KR3: Counting trades, decision points
04_RISKS_AND_DECISIONS.md   ← Pre-mortem, mitigations, decision log
```

---

## Prinsip Eksekusi

1. **Phase 1 harus selesai sebelum counting KR3 dimulai.** Data yang tidak bersih tidak boleh dihitung.
2. **Backup DB sebelum setiap migration.** `backup_db()` sudah ada, tinggal dipanggil.
3. **Fee dihitung dengan formula mainnet** (0.04% × 2), bukan dari testnet transaction history yang abnormal karena partial fills.
4. **RR 1:3 adalah blocker.** Semua trades yang dihitung untuk KR3 harus menggunakan RR ini.

---

## Config yang Harus Diubah Sekarang

**`config.json`** — ubah sebelum apapun:
```json
"risk_reward_ratio": 3.0
```

> ⚠️ Ini adalah **first action** — 5 menit, lakukan sekarang sebelum bot jalan cycle berikutnya.
