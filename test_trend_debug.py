#!/usr/bin/env python3
"""
Test script untuk debug TrendAgent.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from src.agents.math.trend_agent import TrendAgent
from src.indicators.luxalgo_smc import detect_bos_choch

# Load H4 data
df_h4 = pd.read_csv('data/historical/BTCUSDT-4h-full.csv')

print(f"Total H4 candles: {len(df_h4)}")
print(f"H4 columns: {df_h4.columns.tolist()}")

# Test slice pertama
df_test = df_h4.iloc[0:50].copy()
print(f"\nTest slice length: {len(df_test)}")

# Run detect_bos_choch
print("\nRunning detect_bos_choch()...")
signals = detect_bos_choch(df_test, swing_length=10)

print(f"Signals found: {len(signals)}")
if signals:
    for sig in signals[:5]:  # Print first 5
        bias_label = "BULLISH" if sig.bias == 1 else "BEARISH"
        print(f"  - Index {sig.index}: {sig.type} {bias_label} at {sig.level:.2f}")
else:
    print("  NO SIGNALS FOUND!")

# Run TrendAgent
print("\nRunning TrendAgent...")
agent = TrendAgent()
result = agent.run(df_test)

print(f"Trend: {result.bias_label}")
print(f"Confidence: {result.confidence:.2f}")
print(f"Reason: {result.reason}")
