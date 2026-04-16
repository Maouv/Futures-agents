# Bug Tracker — futures-agents

Found: 2026-04-16 | Total: 1 bug (0 Critical, 0 High, 1 Medium, 0 Low)

| # | Severity | Status | Title | File |
|---|----------|--------|-------|------|
| 004 | MEDIUM | ACTIVE | Notifikasi Telegram Bilang "Paper" untuk Live Trade | [004-medium-low-notification-and-comment.md](004-medium-low-notification-and-comment.md) |

## Fixed Bugs

| # | Severity | Title | Fixed Date |
|---|----------|-------|------------|
| 001 | CRITICAL | Trailing Stop Skip Mainnet Trades | 2026-04-16 |
| 002 | HIGH | Semaphore Double-Release di Analyst Agent | 2026-04-16 |
| 003 | HIGH | Trailing Step 0 (Breakeven) Tidak Pernah Diterapkan | 2026-04-16 |
| 005 | LOW | Komentar Menyesatkan di execution_mode Column | 2026-04-16 |

## Rules

1. **Status**: Setiap bug memiliki status `ACTIVE` atau `FIXED`. Saat bug ditemukan, status = `ACTIVE`.
2. **Saat bug di-fix**:
   - Update status di tabel atas dari `ACTIVE` → `FIXED`
   - **Hapus file bug doc** (contoh: `001-critical-*.md`) — file bug doc hanya hidup selama bug masih aktif
   - Jika file gabungan (seperti `004-medium-low-*.md`) masih punya bug aktif, jangan hapus — update saja status bug yang sudah di-fix
   - Jika semua bug dalam file gabungan sudah FIXED, baru hapus file-nya
3. **Tracking**: Jumlah total bug di header harus diupdate setiap kali bug di-fix atau ditemukan bug baru

## Fix Priority

1. **Bug #004** — Medium, misleading notification

## Files That Will Be Modified (Active Bugs)

| File | Bugs |
|------|------|
| `src/main.py` | #004 |

## Related Bugs

- Bug #001 dan #005 saling berkaitan — komentar yang salah (#005) menyebabkan filter yang salah (#001). **Keduanya sudah FIXED.**
- Bug #003 di `position_manager.py` — file sama yang di-fix untuk #001. **FIXED.**
