# Database

Read this when: working in `src/data/`, touching SQLAlchemy models, writing migrations, or debugging DB-related bugs.

## Session Pattern

Always use `get_session()` context manager — never create sessions manually, never write raw SQL.

```python
# Correct
with get_session() as db:
    trade = db.query(PaperTrade).get(trade_id)
    trade.status = "CLOSED"

# Wrong
db = SessionLocal()
db.execute("UPDATE paper_trades SET status = 'CLOSED'")
```

## PaperTrade Schema

```
id                  → primary key
pair                → str (e.g. 'BTCUSDT')
side                → str ('LONG' or 'SHORT')
entry_price         → float, planned entry
actual_entry_price  → float | None, actual fill from exchange
sl_price / tp_price → float
size                → float, quantity in contracts
leverage            → int
status              → str ('OPEN', 'CLOSED', 'PENDING_ENTRY', 'EXPIRED')
pnl                 → float | None, filled on CLOSED
execution_mode      → str ('paper', 'testnet', 'mainnet')
exchange_order_id   → str | None, Binance entry order ID
sl_order_id         → str | None, Binance SL algo order ID
tp_order_id         → str | None, Binance TP algo order ID
close_reason        → str | None ('TP', 'SL', 'MANUAL', 'EXPIRED', 'EMERGENCY_CLOSE_SL_FAIL')
trailing_step       → int, default -1 (never trailed), 0+ = last applied step index
liq_price           → float | None, estimated liquidation price
slippage_entry      → float | None, actual_entry_price - entry_price
fee_open / fee_close → float | None
net_pnl             → float | None, pnl after fees
```

## Gotchas

**DetachedInstanceError** — accessing PaperTrade attributes outside session scope will crash.
Extract all needed values inside the `with get_session()` block before it closes:
```python
# Correct — extract before session closes
with get_session() as db:
    trade = db.query(PaperTrade).get(trade_id)
    trade_data = {
        "id": trade.id,
        "pair": trade.pair,
        "status": trade.status,
    }
# Use trade_data here, not trade

# Wrong
with get_session() as db:
    trade = db.query(PaperTrade).get(trade_id)
print(trade.pair)  # DetachedInstanceError
```

**Naive datetime** — `entry_timestamp` from SQLite has no timezone. Always attach UTC before arithmetic:
```python
if entry_ts.tzinfo is None:
    entry_ts = entry_ts.replace(tzinfo=UTC)
```

**SQLite WAL** — enabled via PRAGMA. Never switch to DELETE mode — can corrupt under concurrent read/write.

**SKIPPED trades** — excluded from ALL metrics: win rate, profit factor, drawdown.

## Backup & Migration

Always call `backup_db()` before any schema migration:
```python
from src.data.storage import backup_db
backup_db()  # Creates rolling backup in data/backups/
```

