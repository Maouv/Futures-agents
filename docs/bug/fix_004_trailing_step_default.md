# Fix Plan #004 — HIGH: trailing_step Migration Default Salah

**Severity:** HIGH
**Confidence:** 90
**Estimasi waktu fix:** 10–15 menit

---

## Apa Masalahnya

Trailing stop step pertama tidak pernah diapply untuk trade lama yang
sudah ada di DB sebelum kolom `trailing_step` ditambahkan. Trade baru
tidak terdampak, tapi semua trade lama akan skip step pertama trailing.

---

## Lokasi Bug

**File:** `src/data/storage.py`
**Baris 107** — definisi model SQLAlchemy:
```python
trailing_step: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
```

**Baris 149** — migration SQL:
```python
("paper_trades", "trailing_step", "INTEGER DEFAULT 0"),
```

---

## Kenapa Bisa Terjadi

Ada dua tempat yang mendefinisikan default untuk kolom yang sama,
dan nilainya berbeda:

**Di model SQLAlchemy (line 107):** `default=-1`
Ini yang dipakai saat INSERT trade baru. `-1` artinya belum pernah
trailing sama sekali.

**Di migration SQL (line 149):** `INTEGER DEFAULT 0`
Ini yang dipakai saat `ALTER TABLE ADD COLUMN` dijalankan untuk DB
yang sudah ada. Semua row lama mendapat nilai `0`.

Di `position_manager.py`, trailing stop memiliki kondisi:
```python
for i, step in enumerate(trailing_steps):
    if i <= trade.trailing_step:
        continue   # Skip step yang sudah diapply
```

Kalau `trailing_step = 0`, maka step index 0 (step pertama) di-skip
karena `0 <= 0` adalah `True`. Trade lama tidak pernah dapat trailing
stop step pertama.

---

## Cara Fix

**Di `src/data/storage.py`**, dua perubahan:

**Perubahan 1** — Ubah SQL DEFAULT di migration list (line 149):
```python
# SEBELUM:
("paper_trades", "trailing_step", "INTEGER DEFAULT 0"),

# SESUDAH:
("paper_trades", "trailing_step", "INTEGER DEFAULT -1"),
```

**Perubahan 2** — Tambah data fix di dalam loop migration yang sudah ada.
Cari blok loop `for table, column, col_type in new_columns:` dan
tambahkan koreksi data setelah kolom berhasil di-add:

```python
for table, column, col_type in new_columns:
    try:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            conn.commit()
            logger.info(f"Migration: Added column {table}.{column}")

            # Fix data: trailing_step yang dapat DEFAULT 0 harus di-reset ke -1
            if column == 'trailing_step':
                conn.execute(text(
                    "UPDATE paper_trades SET trailing_step = -1 WHERE trailing_step = 0"
                ))
                conn.commit()
                logger.info("Migration: Fixed trailing_step default from 0 to -1")

    except Exception:
        conn.rollback()
        # Kolom sudah ada — normal, skip
```

---

## File yang Diubah

| File | Baris | Jenis Perubahan |
|------|-------|-----------------|
| `src/data/storage.py` | ~149 | Ubah `DEFAULT 0` → `DEFAULT -1` |
| `src/data/storage.py` | ~loop migration | Tambah UPDATE data fix setelah ADD COLUMN |

Tidak ada file lain yang perlu diubah.

---

## Cara Verifikasi Setelah Fix

1. Apply fix
2. Cek DB langsung:
   ```sql
   SELECT id, pair, trailing_step FROM paper_trades WHERE status = 'OPEN';
   ```
   Semua row harus punya `trailing_step = -1` (belum pernah trailing)
   atau nilai `>= 0` yang memang sudah diapply step-nya.
3. Tidak boleh ada row dengan `trailing_step = 0` kecuali memang step
   index 0 sudah benar-benar diapply oleh `position_manager`.
4. Restart bot, cek log — cari "Migration: Fixed trailing_step" yang
   konfirmasi update data berhasil.
