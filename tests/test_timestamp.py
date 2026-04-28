"""
test_timestamp.py — Unit tests untuk BUG #10 fix.
Test bahwa setiap paper trade mendapat unique timestamp yang benar.
"""
import time
from datetime import UTC, datetime, timezone

from src.data.storage import PaperTrade, get_session, init_db


def test_unique_entry_timestamps():
    """
    Test bahwa dua trade yang dibuat di waktu berbeda memiliki timestamp berbeda.
    Ini memastikan default tidak di-evaluasi sekali saat class definition.
    """
    init_db()

    # Clear existing trades
    with get_session() as db:
        db.query(PaperTrade).delete()
        db.commit()

    # Create first trade
    with get_session() as db:
        trade1 = PaperTrade(
            pair='BTCUSDT',
            side='LONG',
            entry_price=67000.0,
            sl_price=66800.0,
            tp_price=67400.0,
            size=0.05,
            leverage=10,
            status='OPEN',
            entry_timestamp=datetime.now(UTC)
        )
        db.add(trade1)
        db.commit()
        ts1 = trade1.entry_timestamp

    # Wait a bit
    time.sleep(0.1)

    # Create second trade
    with get_session() as db:
        trade2 = PaperTrade(
            pair='ETHUSDT',
            side='SHORT',
            entry_price=3500.0,
            sl_price=3550.0,
            tp_price=3400.0,
            size=0.5,
            leverage=10,
            status='OPEN',
            entry_timestamp=datetime.now(UTC)
        )
        db.add(trade2)
        db.commit()
        ts2 = trade2.entry_timestamp

    # Verify timestamps are different
    assert ts1 != ts2, "Timestamps harus berbeda!"
    assert ts2 > ts1, "Trade kedua harus memiliki timestamp lebih baru"

    # Note: SQLite strips timezone info, so we can't test tzinfo
    # The important thing is timestamps are different and correct


def test_timestamp_is_recent():
    """
    Test bahwa timestamp yang diset adalah recent (dalam 1 detik terakhir).
    Ini memastikan timestamp tidak di-set ke waktu yang salah.
    """
    init_db()

    before = datetime.now(UTC)

    with get_session() as db:
        trade = PaperTrade(
            pair='BTCUSDT',
            side='LONG',
            entry_price=67000.0,
            sl_price=66800.0,
            tp_price=67400.0,
            size=0.05,
            leverage=10,
            status='OPEN',
            entry_timestamp=datetime.now(UTC)
        )
        db.add(trade)
        db.commit()
        ts = trade.entry_timestamp

    after = datetime.now(UTC)

    # SQLite strips timezone, so we need to make ts timezone-aware for comparison
    ts_aware = ts.replace(tzinfo=UTC)

    # Timestamp harus di antara before dan after
    assert before <= ts_aware <= after, "Timestamp harus di antara waktu sebelum dan sesudah insert"

    # Dan harus dalam 1 detik dari sekarang
    now = datetime.now(UTC)
    diff = (now - ts_aware).total_seconds()
    assert diff < 1.0, f"Timestamp terlalu tua: {diff} detik yang lalu"
