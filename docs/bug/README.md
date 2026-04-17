# Bug Tracker — futures-agents

Found: 2026-04-16 | Total: 7 bugs (2 Critical, 3 High, 2 Medium, 0 Low)

| # | Severity | Status | Title | File |
|---|----------|--------|-------|------|
| 006 | CRITICAL | ACTIVE | Missing close_price saat Reconciliation | src/main.py |
| 007 | CRITICAL | ACTIVE | TP Algo Gagal, Trade Tanpa Proteksi | src/agents/math/execution_agent.py |
| 008 | MEDIUM | ACTIVE | F-string SQL di Migration | src/data/storage.py |
| 009 | HIGH | ACTIVE | Bare except: pass di _cleanup_mode_trades | src/telegram/commands.py |
| 010 | MEDIUM | ACTIVE | Duplicated LLM Call Code | src/agents/llm/analyst_agent.py |
| 011 | HIGH | ACTIVE | Trailing Stop Config KeyError | src/agents/math/position_manager.py |
| 012 | HIGH | ACTIVE | Config Type Mismatch (String vs Number) | src/config/settings.py |

## Fixed Bugs

| # | Severity | Title | Fixed Date |
|---|----------|-------|------------|
| 001 | CRITICAL | Trailing Stop Skip Mainnet Trades | 2026-04-16 |
| 002 | HIGH | Semaphore Double-Release di Analyst Agent | 2026-04-16 |
| 003 | HIGH | Trailing Step 0 (Breakeven) Tidak Pernah Diterapkan | 2026-04-16 |
| 004 | MEDIUM | Notifikasi Telegram Bilang "Paper" untuk Live Trade | 2026-04-16 |
| 005 | LOW | Komentar Menyesatkan di execution_mode Column | 2026-04-16 |

## Rules

1. **Status**: Setiap bug memiliki status `ACTIVE` atau `FIXED`. Saat bug ditemukan, status = `ACTIVE`.
2. **Saat bug di-fix**:
   - Update status di tabel atas dari `ACTIVE` → `FIXED`
   - **Hapus file bug doc** (contoh: `001-critical-*.md`) — file bug doc hanya hidup selama bug masih aktif
   - Jika file gabungan (seperti `004-medium-low-*.md`) masih punya bug aktif, jangan hapus — update saja status bug yang sudah di-fix
   - Jika semua bug dalam file gabungan sudah FIXED, baru hapus file-nya
3. **Tracking**: Jumlah total bug di header harus diupdate setiap kali bug di-fix atau ditemukan bug baru

## Related Bugs

- Bug #001 dan #005 saling berkaitan — komentar yang salah (#005) menyebabkan filter yang salah (#001). **Keduanya sudah FIXED.**
- Bug #003 di `position_manager.py` — file sama yang di-fix untuk #001. **FIXED.**
