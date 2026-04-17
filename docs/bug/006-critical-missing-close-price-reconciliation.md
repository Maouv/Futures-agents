# Bug #006 — CRITICAL: Missing close_price saat Reconciliation

**File**: `src/main.py:327`
**Impact**: Reconciled trades punya `close_price=None` dan `pnl=None` di DB. Saat query performance, `t.pnl or 0` treat None sebagai $0 → win rate & total PnL salah.

**Repro**: Mode live, posisi terbuka di Binance tapi tidak ada di DB (atau sebaliknya). Reconciliation close trade via `close_trade(trade, 'RECONCILED')` tanpa passing `close_price`.

**Fix approach**: Ambil close price dari `positions` data Binance saat reconciliation, lalu pass ke `close_trade(trade, 'RECONCILED', close_price=...)`. Kalau tidak bisa dapat (misal position sudah closed di Binance), gunakan `current_price` sebagai fallback.
