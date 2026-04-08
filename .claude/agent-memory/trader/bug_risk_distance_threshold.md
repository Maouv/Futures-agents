---
name: bug_risk_distance_threshold
description: Critical bug - risk_distance < $1.0 hardcoded threshold kills all signals on low-price pairs like SUIUSDT
type: project
---

Bug KRITIS di `src/backtest/engine.py` baris 386: `if risk_distance < 1.0: continue`

**Why:** Threshold $1.0 hardcoded untuk BTC (harga ~$65K, risk_distance ~$1,339). Tapi SUIUSDT harga ~$1.66, risk_distance rata-rata hanya $0.064. 100% sinyal SUIUSDT dibunuh oleh filter ini.

**How to apply:** Risk distance threshold HARUS disesuaikan per pair, bukan hardcoded $1.0. Gunakan persentase dari entry price atau ATR multiplier. SOLUSDT juga terkena (30% sinyal dibunuh).
