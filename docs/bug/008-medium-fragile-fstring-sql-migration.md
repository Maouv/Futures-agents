# Bug #008 — MEDIUM: F-string SQL di Migration

**File**: `src/data/storage.py:165`
**Impact**: `conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))` — aman karena hardcoded constants, tapi pattern fragile. Kalau suatu hari `new_columns` diisi dari external input, jadi SQL injection.

**Fix approach**: Ganti dengan `sqlalchemy.DDL` atau gunakan string literal langsung (karena table/column/type selalu hardcoded). Contoh:
```python
from sqlalchemy import DDL
conn.execute(DDL(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
```
Atau minimal tambah comment warning "DO NOT populate from external input".
