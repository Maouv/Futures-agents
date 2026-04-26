# Bug Fix Plans — Index
_Futures-agents-main | 2026-04-26_

6 bug aktif, diurutkan berdasarkan prioritas eksekusi.

---

| # | Severity | File Utama | Bug | Estimasi |
|---|----------|------------|-----|----------|
| [FIX-001](FIX-001-reconcile-kills-pending-entry.md) | CRITICAL | `src/main.py` | Reconcile bunuh PENDING_ENTRY setiap restart | 30–45 mnt |
| [FIX-002](FIX-002-ws-fill-silent-no-sltp.md) | CRITICAL | `src/data/ws_user_stream.py` | Entry fill diabaikan WS, SL/TP telat 15 menit | 30–45 mnt |
| [FIX-003](FIX-003-orphan-counter-order.md) | CRITICAL | `src/data/ws_user_stream.py` + `src/utils/exchange.py` | Counter-order cancel selalu gagal, orphan SL/TP | 45–60 mnt |
| [FIX-004](FIX-004-trailing-step-default.md) | HIGH | `src/data/storage.py` | trailing_step migration DEFAULT 0 harusnya -1 | 10–15 mnt |
| [FIX-005](FIX-005-tp-fail-no-alert.md) | HIGH | `src/agents/math/execution_agent.py` | TP gagal tanpa notifikasi Telegram | 20–30 mnt |
| [FIX-006](FIX-006-db-write-missing-trades.md) | HIGH | `src/agents/math/execution_agent.py` | DB write Step 3 tidak ter-wrap, trade hilang | 15–20 mnt |

**Total estimasi:** 2.5–3.5 jam

---

## Urutan Eksekusi yang Disarankan

```
HARI 1 — Data reliability dulu:
  FIX-001  src/main.py               → Reconcile fix
  FIX-004  src/data/storage.py       → trailing_step fix (2 menit saja)

HARI 2 — Eksekusi order:
  FIX-006  execution_agent.py        → DB write wrap
  FIX-005  execution_agent.py        → TP alert (file yang sama, sekalian)

HARI 3 — WebSocket:
  FIX-003  exchange.py + ws_user_stream.py  → Orphan fix (paling complex)
  FIX-002  ws_user_stream.py         → Entry fill → SL/TP real-time

SEBELUM MULAI — Manual action:
  Cancel 3 orphan orders di Binance demo dashboard:
  SUIUSDT Take Profit Market, BTCUSDT Stop Market, SOLUSDT Take Profit Market
```
