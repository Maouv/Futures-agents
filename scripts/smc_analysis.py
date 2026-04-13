#!/usr/bin/env python3
"""SMC (Smart Money Concepts) Analysis untuk semua pairs di pairs.json."""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.data.ohlcv_fetcher import fetch_ohlcv
from src.indicators.luxalgo_smc import detect_all


BIAS_LABEL = {1: "BULLISH", -1: "BEARISH", 0: "NEUTRAL"}


def analyze_pair(symbol: str, timeframe: str = "1h"):
    """Run SMC analysis for a single pair and return structured results."""
    print(f"\nFetching {symbol} {timeframe}...")
    df = fetch_ohlcv(symbol, timeframe)

    if df is None or df.empty:
        print(f"  [SKIP] Gagal fetch data untuk {symbol}")
        return None

    print(f"  Got {len(df)} candles")

    result = detect_all(df)

    # ── ORDER BLOCKS ─────────────────────────────────────────────
    unmitigated_obs = [ob for ob in result.order_blocks if not ob.mitigated]
    mitigated_obs = [ob for ob in result.order_blocks if ob.mitigated]

    print(f"\n{'='*60}")
    print(f"  SMC ANALYSIS: {symbol} ({timeframe.upper()})")
    print(f"  Current Bias: {BIAS_LABEL.get(result.current_bias, '?')}")
    print(f"  Price: {df.iloc[-1]['close']:.2f}")
    print(f"{'='*60}")

    print(f"\n  ORDER BLOCKS — Unmitigated: {len(unmitigated_obs)} / Total: {len(result.order_blocks)}")
    print(f"  {'Type':<10} {'Bias':<10} {'High':>12} {'Low':>12} {'Mid':>12} {'Dist%':>8}")
    print(f"  {'-'*64}")

    current_price = df.iloc[-1]["close"]
    for ob in unmitigated_obs[-15:]:  # Show last 15
        mid = (ob.high + ob.low) / 2
        dist_pct = ((mid - current_price) / current_price) * 100
        print(f"  {'Bull OB' if ob.bias == 1 else 'Bear OB':<10} {BIAS_LABEL[ob.bias]:<10} {ob.high:>12.2f} {ob.low:>12.2f} {mid:>12.2f} {dist_pct:>+7.2f}%")

    # ── FAIR VALUE GAPS ──────────────────────────────────────────
    unfilled_fvgs = [fvg for fvg in result.fair_value_gaps if not fvg.filled]
    filled_fvgs = [fvg for fvg in result.fair_value_gaps if fvg.filled]

    print(f"\n  FAIR VALUE GAPS — Unfilled: {len(unfilled_fvgs)} / Total: {len(result.fair_value_gaps)}")
    print(f"  {'Type':<10} {'Bias':<10} {'Top':>12} {'Bottom':>12} {'Size':>12} {'Dist%':>8}")
    print(f"  {'-'*64}")

    for fvg in unfilled_fvgs[-15:]:
        size = fvg.top - fvg.bottom
        mid = (fvg.top + fvg.bottom) / 2
        dist_pct = ((mid - current_price) / current_price) * 100
        print(f"  {'Bull FVG' if fvg.bias == 1 else 'Bear FVG':<10} {BIAS_LABEL[fvg.bias]:<10} {fvg.top:>12.2f} {fvg.bottom:>12.2f} {size:>12.2f} {dist_pct:>+7.2f}%")

    # ── BOS / CHOCH ──────────────────────────────────────────────
    recent_signals = result.bos_choch_signals[-20:] if result.bos_choch_signals else []

    print(f"\n  BOS/CHOCH SIGNALS — Recent {len(recent_signals)}:")
    print(f"  {'Type':<8} {'Bias':<10} {'Level':>12} {'Idx':>6} {'Time'}")
    print(f"  {'-'*56}")

    for sig in recent_signals:
        # Get timestamp from index
        if sig.index < len(df):
            ts = df.iloc[sig.index]["timestamp"] if "Timestamp" in df.columns else df.iloc[sig.index].name
            ts_str = str(ts)[:16] if ts is not None else "N/A"
        else:
            ts_str = "N/A"
        print(f"  {sig.type:<8} {BIAS_LABEL[sig.bias]:<10} {sig.level:>12.2f} {sig.index:>6} {ts_str}")

    # ── INTERPRETATION ───────────────────────────────────────────
    print(f"\n  {'─'*60}")
    print(f"  INTERPRETATION — {symbol}")
    print(f"  {'─'*60}")

    # Closest OB
    if unmitigated_obs:
        closest_ob = min(unmitigated_obs, key=lambda ob: abs((ob.high + ob.low) / 2 - current_price))
        ob_mid = (closest_ob.high + closest_ob.low) / 2
        ob_type = "Bullish" if closest_ob.bias == 1 else "Bearish"
        direction = "above" if ob_mid > current_price else "below"
        print(f"  * Closest OB: {ob_type} OB [{closest_ob.low:.2f} - {closest_ob.high:.2f}]")
        print(f"    Midpoint: {ob_mid:.2f} ({direction} current price {current_price:.2f})")

        # If bullish OB below price = demand zone, bearish OB above = supply zone
        if closest_ob.bias == 1 and ob_mid < current_price:
            print(f"    → Demand zone (support) — price could bounce here if it drops")
        elif closest_ob.bias == -1 and ob_mid > current_price:
            print(f"    → Supply zone (resistance) — price could reject here if it rises")
        elif closest_ob.bias == 1 and ob_mid > current_price:
            print(f"    → Bullish OB above price — potential resistance flip to support on breakout")
        elif closest_ob.bias == -1 and ob_mid < current_price:
            print(f"    → Bearish OB below price — potential support flip to resistance on breakdown")

    # Closest FVG
    if unfilled_fvgs:
        closest_fvg = min(unfilled_fvgs, key=lambda fvg: abs((fvg.top + fvg.bottom) / 2 - current_price))
        fvg_mid = (closest_fvg.top + closest_fvg.bottom) / 2
        fvg_type = "Bullish" if closest_fvg.bias == 1 else "Bearish"
        print(f"\n  * Closest FVG: {fvg_type} [{closest_fvg.bottom:.2f} - {closest_fvg.top:.2f}]")
        print(f"    Midpoint: {fvg_mid:.2f}")

    # Bias from last BOS/CHOCH
    if result.bos_choch_signals:
        last_sig = result.bos_choch_signals[-1]
        print(f"\n  * Last BOS/CHOCH: {last_sig.type} {BIAS_LABEL[last_sig.bias]} at {last_sig.level:.2f}")
        if last_sig.type == "CHOCH":
            print(f"    → CHANGE OF CHARACTER detected — bias may be shifting {BIAS_LABEL[last_sig.bias]}")
        else:
            print(f"    → Break of Structure confirms {BIAS_LABEL[last_sig.bias]} continuation")

    # Confluence zones (OB + FVG overlap)
    confluences = []
    for ob in unmitigated_obs:
        for fvg in unfilled_fvgs:
            # Check if OB zone overlaps with FVG zone
            overlap_top = min(ob.high, fvg.top)
            overlap_bottom = max(ob.low, fvg.bottom)
            if overlap_top > overlap_bottom:
                confluences.append({
                    "ob": ob,
                    "fvg": fvg,
                    "zone_top": overlap_top,
                    "zone_bottom": overlap_bottom,
                })

    if confluences:
        print(f"\n  * CONFLUENCE ZONES (OB + FVG overlap): {len(confluences)}")
        for c in confluences[-5:]:
            ob_bias = BIAS_LABEL[c["ob"].bias]
            fvg_bias = BIAS_LABEL[c["fvg"].bias]
            mid = (c["zone_top"] + c["zone_bottom"]) / 2
            print(f"    Zone [{c['zone_bottom']:.2f} - {c['zone_top']:.2f}] — OB:{ob_bias} + FVG:{fvg_bias} → Mid: {mid:.2f}")
    else:
        print(f"\n  * No OB+FVG confluence zones found")

    # Potential entry
    if unmitigated_obs:
        # Find OB aligned with current bias
        aligned_obs = [ob for ob in unmitigated_obs if ob.bias == result.current_bias]
        if aligned_obs:
            entry_ob = min(aligned_obs, key=lambda ob: abs((ob.high + ob.low) / 2 - current_price))
            entry_mid = (entry_ob.high + entry_ob.low) / 2
            print(f"\n  * POTENTIAL ENTRY (aligned with {BIAS_LABEL[result.current_bias]} bias):")
            print(f"    OB Zone: [{entry_ob.low:.2f} - {entry_ob.high:.2f}]")
            print(f"    Entry at OB Midpoint: {entry_mid:.2f}")
            if result.current_bias == 1:
                print(f"    SL below OB Low: {entry_ob.low:.2f}")
                print(f"    → Wait for price to pull back to OB zone, then LONG")
            elif result.current_bias == -1:
                print(f"    SL above OB High: {entry_ob.high:.2f}")
                print(f"    → Wait for price to pull back to OB zone, then SHORT")
        else:
            print(f"\n  * No OB aligned with current {BIAS_LABEL[result.current_bias]} bias — no clear entry setup")

    return result


DEFAULT_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="SMC Analysis for crypto futures pairs")
    parser.add_argument("pairs", nargs="*", default=DEFAULT_PAIRS,
                        help="Pairs to analyze (default: all from pairs.json)")
    parser.add_argument("--tf", "--timeframe", default="1h", dest="timeframe",
                        help="Timeframe (default: 1h)")
    args = parser.parse_args()

    pairs = [p.upper() for p in args.pairs]

    header = " + ".join(pairs) if len(pairs) <= 3 else f"{len(pairs)} pairs"
    print(f"╔══════════════════════════════════════════════════════════╗")
    print(f"║        SMC ANALYSIS — {header:<33s}║")
    print(f"╚══════════════════════════════════════════════════════════╝")

    for symbol in pairs:
        try:
            analyze_pair(symbol, timeframe=args.timeframe)
        except Exception as e:
            print(f"\n  [ERROR] {symbol}: {e}")

    print("\n" + "="*60)
    print("  ANALYSIS COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()
