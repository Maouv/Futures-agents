#!/usr/bin/env python3
"""Run ReversalAgent for a single pair and print detailed results."""
import sys
sys.path.insert(0, "/root/futures-agents")

from src.data.ohlcv_fetcher import fetch_ohlcv
from src.agents.math.reversal_agent import ReversalAgent

PAIR = "ETHUSDT"
TIMEFRAME = "1h"

# 1. Fetch OHLCV
print(f"=== Fetching {TIMEFRAME} OHLCV for {PAIR} ===")
df = fetch_ohlcv(PAIR, TIMEFRAME)

if df is None:
    print("ERROR: fetch_ohlcv returned None (gap or error)")
    sys.exit(1)

print(f"Candles: {len(df)} | Range: {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")
print(f"Last close: {df['close'].iloc[-1]:.2f}")
print(f"Skip trade flag: {df.attrs.get('skip_trade', False)}")
print()

# 2. Run ReversalAgent
print(f"=== Running ReversalAgent on {PAIR} {TIMEFRAME} ===")
agent = ReversalAgent()
result = agent.run(df)

# 3. Print full results
print()
print(f"Signal      : {result.signal}")
print(f"Confidence  : {result.confidence}")
print(f"Entry Price : {result.entry_price}")
print(f"Reason      : {result.reason}")
print()

if result.ob:
    print("--- Order Block ---")
    print(f"  Bias     : {'Bullish' if result.ob.bias == 1 else 'Bearish'} ({result.ob.bias})")
    print(f"  High     : {result.ob.high:.2f}")
    print(f"  Low      : {result.ob.low:.2f}")
    print(f"  Midpoint : {(result.ob.high + result.ob.low) / 2:.2f}")
    print(f"  Mitigated: {result.ob.mitigated}")
    print(f"  Index    : {result.ob.index}")
else:
    print("--- Order Block: None ---")

print()

if result.fvg:
    print("--- Fair Value Gap ---")
    print(f"  Bias   : {'Bullish' if result.fvg.bias == 1 else 'Bearish'} ({result.fvg.bias})")
    print(f"  Top    : {result.fvg.top:.2f}")
    print(f"  Bottom : {result.fvg.bottom:.2f}")
    print(f"  Filled : {result.fvg.filled}")
    print(f"  Index  : {result.fvg.index}")
else:
    print("--- Fair Value Gap: None ---")

print()

if result.bos_choch:
    print("--- BOS/CHOCH Signal ---")
    print(f"  Type   : {result.bos_choch.type}")
    print(f"  Bias   : {'Bullish' if result.bos_choch.bias == 1 else 'Bearish'} ({result.bos_choch.bias})")
    print(f"  Index  : {result.bos_choch.index}")
    print(f"  Price  : {result.bos_choch.price:.2f}" if hasattr(result.bos_choch, 'price') and result.bos_choch.price else "  Price  : N/A")
else:
    print("--- BOS/CHOCH Signal: None ---")

print()
print("=" * 50)
