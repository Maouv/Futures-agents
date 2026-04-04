#!/usr/bin/env python
"""
Manual integration test untuk verifikasi BUG #3 dan BUG #5 fixes.
Run: python test_bug_fixes.py
"""
import sys
sys.path.insert(0, '/root/futures-agents')

from src.agents.math.risk_agent import RiskAgent
from src.indicators.luxalgo_smc import OrderBlock
from src.agents.math.sltp_manager import check_paper_trades
from src.data.storage import PaperTrade, init_db, get_session
import pandas as pd
import numpy as np

def test_bug3_position_size():
    """Test BUG #3: Formula position size sudah benar."""
    print("\n" + "="*60)
    print("TEST BUG #3: Position Size Formula")
    print("="*60)

    ob = OrderBlock(
        index=100,
        high=67050.0,
        low=66950.0,
        bias=1,
        mitigated=False
    )

    # Create dummy DataFrame
    dates = pd.date_range(start='2024-01-01', periods=50, freq='1h', tz='UTC')
    df = pd.DataFrame({
        'timestamp': dates,
        'open': np.random.uniform(66000, 68000, 50),
        'high': np.random.uniform(67000, 68000, 50),
        'low': np.random.uniform(66000, 67000, 50),
        'close': np.random.uniform(66500, 67500, 50),
        'volume': np.random.uniform(100, 1000, 50)
    })

    agent = RiskAgent()
    result = agent.run(signal='LONG', order_block=ob, df=df, atr_period=14)

    risk_distance = abs(result.entry_price - result.sl_price)
    expected_position_size = 10.0 / risk_distance
    actual_risk = result.position_size * risk_distance

    print(f"Entry Price: ${result.entry_price:.2f}")
    print(f"SL Price: ${result.sl_price:.2f}")
    print(f"Risk Distance: ${risk_distance:.2f}")
    print(f"Position Size: {result.position_size:.6f}")
    print(f"Expected Position Size: {expected_position_size:.6f}")
    print(f"Match: {result.position_size == expected_position_size}")
    print(f"\nActual Risk: ${actual_risk:.2f}")
    print(f"Target Risk: $10.00")
    print(f"Risk Match: {abs(actual_risk - 10.0) < 0.01}")

    assert abs(result.position_size - expected_position_size) < 0.0001, "Position size formula salah!"
    assert abs(actual_risk - 10.0) < 0.01, "Risk calculation salah!"

    print("\n✅ BUG #3 FIX VERIFIED - Position size formula sudah benar!")
    return True

def test_bug5_multi_pair():
    """Test BUG #5: Multi-pair error handling."""
    print("\n" + "="*60)
    print("TEST BUG #5: Multi-Pair Error Handling")
    print("="*60)

    init_db()

    # Clear existing trades
    with get_session() as db:
        db.query(PaperTrade).delete()
        db.commit()

    # Create test trades
    with get_session() as db:
        trade1 = PaperTrade(
            pair='BTCUSDT',
            side='LONG',
            entry_price=67000.0,
            sl_price=66800.0,
            tp_price=67400.0,
            size=0.05,
            leverage=10,
            status='OPEN'
        )
        trade2 = PaperTrade(
            pair='ETHUSDT',
            side='LONG',
            entry_price=3500.0,
            sl_price=3450.0,
            tp_price=3600.0,
            size=0.5,
            leverage=10,
            status='OPEN'
        )
        db.add(trade1)
        db.add(trade2)
        db.commit()
        print(f"Created 2 paper trades: BTCUSDT (ID {trade1.id}), ETHUSDT (ID {trade2.id})")

    # Test 1: Hanya pass BTCUSDT price
    print("\nTest 1: Price dict hanya berisi BTCUSDT")
    print("-" * 40)
    current_prices = {'BTCUSDT': 67500.0}  # TP hit
    closed = check_paper_trades(current_prices)

    print(f"Closed trades: {len(closed)}")
    if len(closed) == 1:
        print(f"  - {closed[0]['pair']} {closed[0]['reason']} (PnL: ${closed[0]['pnl']:.2f})")

    print("\nExpected: ERROR log untuk ETHUSDT dengan CRITICAL level")
    print("Expected: Hanya BTCUSDT yang di-close")

    assert len(closed) == 1, "Hanya BTCUSDT yang harus di-close"
    assert closed[0]['pair'] == 'BTCUSDT', "Pair yang close harus BTCUSDT"
    assert closed[0]['reason'] == 'TP', "Reason harus TP"

    print("\n✅ BUG #5 FIX VERIFIED - Multi-pair error handling sudah benar!")
    return True

if __name__ == "__main__":
    try:
        test_bug3_position_size()
        test_bug5_multi_pair()
        print("\n" + "="*60)
        print("🎉 SEMUA BUG FIX TERVERIFIKASI!")
        print("="*60)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
