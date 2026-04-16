# Bug #004 — MEDIUM + Bug #005 — LOW: Notifikasi Telegram & Komentar Menyesatkan

| Field     | Bug #004                              | Bug #005                              |
|-----------|---------------------------------------|---------------------------------------|
| Severity  | MEDIUM                                | LOW                                   |
| Category  | Logic                                 | Data / Documentation                  |
| Status    | OPEN                                  | FIXED                                 |
| Found     | 2026-04-16                            | 2026-04-16                            |

---

## Bug #004 — MEDIUM: Notifikasi Telegram Bilang "Paper" untuk Live Trade

### Description

Di `main.py:149`, saat `result.action == 'OPEN'`, notifikasi Telegram selalu menampilkan:

```python
f"Paper {decision.action}"
```

Padahal `_execute_live_market()` juga return `action='OPEN'` untuk live market order (overlap path). Jadi trade live dikirim ke Telegram sebagai "Paper LONG" atau "Paper SHORT".

### Impact

- Operator bisa salah mengira trade live cuma paper trade
- Sebaliknya, bisa mengira paper trade adalah live trade (kalau sebalaknya ada path yang lupa di-flag)
- Mengurangi trust terhadap notifikasi Telegram sebagai monitoring tool

### Root Cause

Notification path tidak mengecek `execution_mode` — hardcode "Paper" sebagai label.

### Files to Modify

| File                    | Change                                                       |
|-------------------------|---------------------------------------------------------------|
| `src/main.py`           | Ganti hardcode "Paper" dengan label berdasarkan `execution_mode` |

### Fix Details

**`src/main.py:149`**

**Before:**
```python
f"Paper {decision.action}"
```

**After:**
```python
mode_label = "LIVE" if settings.execution_mode != "paper" else "Paper"
f"{mode_label} {decision.action}"
```

Atau kalau ingin lebih akuran dengan `_current_mode()`:

```python
mode = ExecutionAgent._current_mode()
mode_label = "Paper" if mode == "paper" else mode.upper()  # "TESTNET" or "MAINNET"
f"{mode_label} {decision.action}"
```

### Verification

1. Jalankan bot di testnet, buka trade, cek notifikasi Telegram menampilkan "TESTNET LONG" bukan "Paper LONG"
2. Jalankan di paper mode, verifikasi tetap tampil "Paper LONG"

---

## Bug #005 — LOW: Komentar Menyesatkan di execution_mode Column

### Description

Komentar di `storage.py:100`:

```python
execution_mode = Column(String, default='paper')  # 'paper' atau 'live'
```

Tapi nilai yang tersimpan sebenarnya `'paper'`, `'testnet'`, atau `'mainnet'`. Nilai `'live'` **tidak pernah disimpan** oleh `ExecutionAgent._current_mode()`.

Komentar ini **secara langsung menyebabkan Bug #001** — developer membaca komentar ini lalu menulis filter `execution_mode.in_(['live', 'testnet'])` di `position_manager.py`.

### Impact

- Developer di masa depan bisa mengulangi kesalahan yang sama (Bug #001)
- Kode jadi harder to reason about karena dokumentasi tidak match dengan reality

### Root Cause

Komentar tidak diupdate ketika `ExecutionAgent._current_mode()` diubah dari return `'live'` ke `'mainnet'`/`'testnet'`.

### Files to Modify

| File                    | Change                                                       |
|-------------------------|---------------------------------------------------------------|
| `src/data/storage.py`   | Perbaiki komentar line 100                                    |

### Fix Details

**`src/data/storage.py:100`**

**Before:**
```python
execution_mode = Column(String, default='paper')  # 'paper' atau 'live'
```

**After:**
```python
execution_mode = Column(String, default='paper')  # 'paper', 'testnet', atau 'mainnet'
```

### Verification

1. Grep seluruh codebase untuk `'live'` sebagai execution_mode value — pastikan tidak ada yang pakai `'live'` setelah fix Bug #001
2. Cek `ExecutionAgent._current_mode()` return values konsisten dengan komentar baru
