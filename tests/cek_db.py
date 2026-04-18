import sqlite3

conn = sqlite3.connect('trading.db')
cursor = conn.cursor()

# 1. Lihat semua table
print("=== TABLES DI DATABASE ===")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
for t in tables:
    print(f"  - {t[0]}")

# 2. Cari order ID di semua table
print("\n=== CARI ORDER 13032917912 ===")
for table in tables:
    table_name = table[0]
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [c[1] for c in cursor.fetchall()]
        
        if 'order_id' in columns or 'id' in columns:
            col_name = 'order_id' if 'order_id' in columns else 'id'
            cursor.execute(f"SELECT * FROM {table_name} WHERE {col_name}='13032917912'")
            rows = cursor.fetchall()
            if rows:
                print(f"\n✅ KETEMU di table: {table_name}")
                print(f"Columns: {columns}")
                for r in rows:
                    print(f"Data: {r}")
    except Exception as e:
        pass

conn.close()
