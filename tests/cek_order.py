import sqlite3
from tabulate import tabulate

conn = sqlite3.connect('trading.db')
cursor = conn.cursor()

cursor.execute("SELECT * FROM orders WHERE order_id='13032917912'")
columns = [desc[0] for desc in cursor.description]
rows = cursor.fetchall()

if rows:
    print(tabulate(rows, headers=columns, tablefmt='simple'))
else:
    print("Order tidak ditemukan")

conn.close()
