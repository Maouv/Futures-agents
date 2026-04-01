"""
validate_indicators.py — Bandingkan output Python vs TradingView manual.
Jalankan ini dan bandingkan hasilnya dengan chart TradingView secara visual.
"""
import sys
from pathlib import Path

# Add project root to sys.path so we can import src module
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import argparse
import pandas as pd
from datetime import datetime

from src.data.ohlcv_fetcher import fetch_and_store_ohlcv
from src.indicators.luxalgo_smc import detect_order_blocks, detect_fvg, detect_bos_choch
from src.indicators.mean_reversion import calculate_mean_reversion
from src.utils.logger import logger, setup_logger


def validate(symbol: str = "BTCUSDT", timeframe: str = "1h", bars: int = 100):
    """
    Validate indicator calculations against TradingView.

    Args:
        symbol: Trading pair (e.g., "BTCUSDT")
        timeframe: Timeframe (e.g., "1h", "15m", "4h")
        bars: Number of bars to analyze
    """
    setup_logger()

    logger.info(f"=== VALIDATING INDICATORS FOR {symbol} {timeframe} ===")
    logger.info(f"Fetching last {bars} candles...")

    # Fetch data
    df = fetch_and_store_ohlcv(symbol, timeframe)

    if df is None:
        logger.error("Failed to fetch data")
        return

    # Take only last N bars
    df = df.tail(bars).reset_index(drop=True)

    logger.info(f"Data fetched: {len(df)} candles")
    logger.info(f"Date range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
    logger.info("")

    # ── MEAN REVERSION INDICATORS ─────────────────────────────────────────────
    logger.info("=== MEAN REVERSION INDICATORS ===")
    try:
        mr_result = calculate_mean_reversion(df)
        logger.info(f"RSI(14): {mr_result.rsi:.2f} | Signal: {mr_result.rsi_signal}")
        logger.info(f"Bollinger Bands(20, 2.0):")
        logger.info(f"  Upper:  {mr_result.bb_upper:.2f}")
        logger.info(f"  Middle: {mr_result.bb_middle:.2f}")
        logger.info(f"  Lower:  {mr_result.bb_lower:.2f}")
        logger.info(f"  Position: {mr_result.bb_position:.2f} (-1 = lower, 0 = middle, +1 = upper)")
        logger.info("")
    except Exception as e:
        logger.error(f"Error calculating mean reversion: {e}")

    # ── SMART MONEY CONCEPTS ─────────────────────────────────────────────────
    logger.info("=== SMART MONEY CONCEPTS ===")

    # Order Blocks
    logger.info("Detecting Order Blocks...")
    try:
        obs = detect_order_blocks(df, lookback=50)

        logger.info(f"Total Order Blocks detected: {len(obs)}")
        logger.info("")

        # Print last 5 OBs
        if obs:
            logger.info("=== LAST 5 ORDER BLOCKS ===")
            for ob in obs[-5:]:
                bias_str = "BULLISH" if ob.bias == 1 else "BEARISH"
                mitigated_str = "MITIGATED" if ob.mitigated else "ACTIVE"
                timestamp = df['timestamp'].iloc[ob.index] if ob.index < len(df) else "N/A"

                logger.info(f"  {bias_str} OB | Index: {ob.index} | Time: {timestamp}")
                logger.info(f"    High: {ob.high:.2f} | Low: {ob.low:.2f}")
                logger.info(f"    Status: {mitigated_str}")
                logger.info("")
        else:
            logger.warning("No Order Blocks detected")
            logger.info("")

    except Exception as e:
        logger.error(f"Error detecting Order Blocks: {e}")
        logger.info("")

    # Fair Value Gaps
    logger.info("Detecting Fair Value Gaps...")
    try:
        fvgs = detect_fvg(df)

        logger.info(f"Total FVGs detected: {len(fvgs)}")
        logger.info("")

        # Print last 5 FVGs
        if fvgs:
            logger.info("=== LAST 5 FAIR VALUE GAPS ===")
            for fvg in fvgs[-5:]:
                bias_str = "BULLISH" if fvg.bias == 1 else "BEARISH"
                filled_str = "FILLED" if fvg.filled else "UNFILLED"
                timestamp = df['timestamp'].iloc[fvg.index] if fvg.index < len(df) else "N/A"

                logger.info(f"  {bias_str} FVG | Index: {fvg.index} | Time: {timestamp}")
                logger.info(f"    Top: {fvg.top:.2f} | Bottom: {fvg.bottom:.2f}")
                logger.info(f"    Gap Size: {fvg.top - fvg.bottom:.2f}")
                logger.info(f"    Status: {filled_str}")
                logger.info("")
        else:
            logger.warning("No Fair Value Gaps detected")
            logger.info("")

    except Exception as e:
        logger.error(f"Error detecting FVGs: {e}")
        logger.info("")

    # BOS/CHOCH
    logger.info("Detecting BOS/CHOCH signals...")
    try:
        signals = detect_bos_choch(df, lookback=50)

        logger.info(f"Total BOS/CHOCH signals detected: {len(signals)}")
        logger.info("")

        # Print last 5 signals
        if signals:
            logger.info("=== LAST 5 BOS/CHOCH SIGNALS ===")
            for signal in signals[-5:]:
                bias_str = "BULLISH" if signal.bias == 1 else "BEARISH"
                timestamp = df['timestamp'].iloc[signal.index] if signal.index < len(df) else "N/A"

                logger.info(f"  {signal.type} {bias_str} | Index: {signal.index} | Time: {timestamp}")
                logger.info(f"    Level Broken: {signal.level:.2f}")
                logger.info("")
        else:
            logger.warning("No BOS/CHOCH signals detected")
            logger.info("")

    except Exception as e:
        logger.error(f"Error detecting BOS/CHOCH: {e}")
        logger.info("")

    # ── VALIDATION INSTRUCTIONS ───────────────────────────────────────────────
    logger.info("=== VALIDATION INSTRUCTIONS ===")
    logger.info("1. Open TradingView and load BTCUSDT Futures chart (BINANCE:BTCUSDT.P)")
    logger.info(f"2. Set timeframe to {timeframe}")
    logger.info("3. Add indicator: LuxAlgo Smart Money Concepts")
    logger.info(f"4. Navigate to the time range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
    logger.info("5. Compare the values above with what you see on TradingView:")
    logger.info("   - Order Blocks: Check if OB positions (high/low) match")
    logger.info("   - FVGs: Check if gaps appear at the same locations")
    logger.info("   - BOS/CHOCH: Check if signals appear at the same candles")
    logger.info("")
    logger.info("CRITERIA FOR PASSING:")
    logger.info("  ✅ Order Block positions (high/low) must match within tolerance < 0.0001")
    logger.info("  ✅ FVG count and positions must match TradingView")
    logger.info("  ✅ BOS/CHOCH must appear on the same candle as TradingView")
    logger.info("")
    logger.info("❌ IF VALUES DO NOT MATCH:")
    logger.info("   - Check indexing (Python 0-based vs PineScript 1-based)")
    logger.info("   - Verify parsedHigh/parsedLow logic (volatility filter)")
    logger.info("   - Ensure swing detection lookback matches")
    logger.info("")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate trading indicators against TradingView")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Trading pair (default: BTCUSDT)")
    parser.add_argument("--timeframe", type=str, default="1h", help="Timeframe (default: 1h)")
    parser.add_argument("--bars", type=int, default=100, help="Number of bars to analyze (default: 100)")

    args = parser.parse_args()

    validate(symbol=args.symbol, timeframe=args.timeframe, bars=args.bars)
