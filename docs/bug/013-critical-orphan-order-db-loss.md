# Bug #013 — Orphan Order: Exchange Order Tidak Tersimpan di DB

**Severity**: CRITICAL | **Status**: ACTIVE | **Found**: 2026-04-18

## Summary

`exchange.create_order()` jalan SEBELUM DB INSERT. Jika INSERT gagal → order ada di Binance tapi tidak di `paper_trades`. Position tidak ter-track, tidak ada trailing stop, PnL tidak ter-record.

**Real evidence**: Order ID `13032917912` (BTCUSDT BUY @ 70829.4) ditempatkan di testnet 2026-04-13 17:00:02 (logs confirm) tapi **tidak ada di DB**. Trade 7 dari logs juga hilang.

## Files Involved

| File | Issue |
|------|-------|
| `src/agents/math/execution_agent.py` | `_execute_live_limit()` line 262: exchange call BEFORE DB insert. Same issue in `_execute_live_market()` line 328 and `_handle_fill()` line 594 |
| `src/data/storage.py` | `busy_timeout=5000` too short for concurrent threads. No auto-backup, no integrity check, no WAL checkpoint |
| `src/utils/mode.py` | `get_current_mode()` depends on editable config.json → mode switch leaves orphaned trades |
| `src/agents/math/execution_agent.py` | `check_pending_orders()` line 455: filters by mode → old mode trades abandoned |
| `src/main.py` | No reconciliation at startup → orphan positions undetected |

## Root Cause

Wrong operation order: **exchange-first, DB-second**. Fix: **DB-first, exchange-second** (write-then-exchange pattern).

## Fix Plan

1. **Write-then-exchange** (`execution_agent.py`): INSERT PENDING_SUBMIT record dulu, baru `create_order()`. Jika exchange gagal → mark FAILED. Jika sukses → UPDATE dengan order_id. Apply to `_execute_live_limit()`, `_execute_live_market()`, `_handle_fill()`.

2. **PRAGMA quick_check** per cycle (`execution_agent.py`): `PRAGMA quick_check(2)` di awal `run()`. Jika corrupt → kill switch → STOP.

3. **Startup reconciliation** (`main.py`): `fetch_positions()` dari exchange → bandingkan dengan DB → recover orphan positions.

4. **Increase timeout** (`storage.py`): `busy_timeout=30000` (30s), `synchronous=NORMAL`, `cache_size=-64000`.

5. **Auto-backup** (`storage.py`): Backup setiap 6 jam ke `~/.trading_backups/` dengan integrity check. WAL checkpoint di startup (bukan shutdown).

6. **Mode switch warning** (`main.py`): Log + Telegram alert jika ada trades dari mode berbeda saat startup.
