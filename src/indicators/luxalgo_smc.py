"""
luxalgo_smc.py — Porting LuxAlgo Smart Money Concepts indicator.
Hanya 3 fungsi yang di-port: Order Blocks, FVG, BOS/CHOCH.
Semua fungsi murni Python/pandas — DILARANG pakai LLM.
"""
from typing import Optional
import pandas as pd
import numpy as np

from pydantic import BaseModel
from src.indicators.helpers import calculate_atr, crossover, crossunder


# ── Pydantic Output Models ─────────────────────────────────────────────────────

class OrderBlock(BaseModel):
    """Represents an order block (OB)."""
    index: int              # Index baris di DataFrame
    high: float
    low: float
    bias: int               # 1 = BULLISH, -1 = BEARISH
    mitigated: bool = False # True jika sudah ditembus harga


class FairValueGap(BaseModel):
    """Represents a fair value gap (FVG)."""
    index: int              # Index baris di DataFrame
    top: float
    bottom: float
    bias: int               # 1 = BULLISH, -1 = BEARISH
    filled: bool = False    # True jika sudah terisi harga


class BOSCHOCHSignal(BaseModel):
    """Represents a BOS or CHOCH signal."""
    index: int
    type: str               # 'BOS' atau 'CHOCH'
    bias: int               # 1 = BULLISH, -1 = BEARISH
    level: float            # Level harga yang ditembus


class SMCResult(BaseModel):
    """Container untuk semua output SMC."""
    order_blocks: list[OrderBlock]
    fair_value_gaps: list[FairValueGap]
    bos_choch_signals: list[BOSCHOCHSignal]
    current_bias: int       # Bias trend saat ini: 1, -1, atau 0


# ── Helper Functions ────────────────────────────────────────────────────────────

def _calculate_parsed_highs_lows(df: pd.DataFrame, atr_period: int = 200) -> tuple[pd.Series, pd.Series]:
    """
    Calculate parsedHigh and parsedLow based on volatility filter.
    Jika bar volatile (range >= 2 * ATR), swap high dan low.

    Ini sama dengan logika PineScript:
        atrMeasure = ta.atr(200)
        highVolatilityBar = (high - low) >= (2 * atrMeasure)
        parsedHigh = highVolatilityBar ? low : high
        parsedLow  = highVolatilityBar ? high : low
    """
    atr = calculate_atr(df, period=atr_period)
    high = df['high']
    low = df['low']

    high_volatility_bar = (high - low) >= (2 * atr)

    parsed_high = pd.Series(np.where(high_volatility_bar, low, high), index=df.index)
    parsed_low = pd.Series(np.where(high_volatility_bar, high, low), index=df.index)

    return parsed_high, parsed_low


# ── Main Functions ──────────────────────────────────────────────────────────────

def detect_order_blocks(df: pd.DataFrame, lookback: int = 50) -> list[OrderBlock]:
    """
    Detect Order Blocks berdasarkan LuxAlgo SMC logic.

    Logika:
    1. Identifikasi swing high dan swing low
    2. Untuk swing high baru (bearish leg):
       - Cari candle dengan parsedHigh tertinggi antara swing sebelumnya dan sekarang
       - Itu adalah Bearish Order Block
    3. Untuk swing low baru (bullish leg):
       - Cari candle dengan parsedLow terendah antara swing sebelumnya dan sekarang
       - Itu adalah Bullish Order Block
    4. Tandai OB sebagai 'mitigated' jika harga menembus level OB

    Args:
        df: DataFrame dengan kolom 'high', 'low', 'close'
        lookback: Jumlah candle untuk identifikasi swing (default 50)

    Returns:
        list[OrderBlock]: Daftar order blocks yang terdeteksi
    """
    if len(df) < lookback * 2:
        return []

    # Calculate parsed highs/lows
    parsed_high, parsed_low = _calculate_parsed_highs_lows(df)

    # Identify swing points
    # Swing high: high > lookback bars ke kiri dan kanan
    # Swing low: low < lookback bars ke kiri dan kanan
    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(df) - lookback):
        # Check swing high
        is_swing_high = True
        for j in range(1, lookback + 1):
            if df['high'].iloc[i] <= df['high'].iloc[i-j] or df['high'].iloc[i] <= df['high'].iloc[i+j]:
                is_swing_high = False
                break
        if is_swing_high:
            swing_highs.append((i, df['high'].iloc[i]))

        # Check swing low
        is_swing_low = True
        for j in range(1, lookback + 1):
            if df['low'].iloc[i] >= df['low'].iloc[i-j] or df['low'].iloc[i] >= df['low'].iloc[i+j]:
                is_swing_low = False
                break
        if is_swing_low:
            swing_lows.append((i, df['low'].iloc[i]))

    # Detect order blocks
    order_blocks = []

    # Bearish OB dari swing highs
    for i in range(1, len(swing_highs)):
        swing_idx, swing_price = swing_highs[i]
        prev_swing_idx, _ = swing_highs[i-1]

        # Cari index dengan parsedHigh tertinggi antara prev_swing_idx dan swing_idx
        range_highs = parsed_high.iloc[prev_swing_idx:swing_idx+1]
        ob_idx = range_highs.idxmax()

        if range_highs.loc[ob_idx] > 0:  # Valid OHLC data
            # Cek mitigasi: jika close > ob.high
            ob_high = df['high'].loc[ob_idx]
            ob_low = df['low'].loc[ob_idx]
            mitigated = False

            # Cek apakah sudah mitigasi di candle setelah OB
            for j in range(ob_idx + 1, len(df)):
                if df['close'].iloc[j] > ob_high:
                    mitigated = True
                    break

            order_blocks.append(OrderBlock(
                index=int(ob_idx),
                high=float(ob_high),
                low=float(ob_low),
                bias=-1,  # BEARISH
                mitigated=mitigated
            ))

    # Bullish OB dari swing lows
    for i in range(1, len(swing_lows)):
        swing_idx, swing_price = swing_lows[i]
        prev_swing_idx, _ = swing_lows[i-1]

        # Cari index dengan parsedLow terendah antara prev_swing_idx dan swing_idx
        range_lows = parsed_low.iloc[prev_swing_idx:swing_idx+1]
        ob_idx = range_lows.idxmin()

        if range_lows.loc[ob_idx] > 0:  # Valid OHLC data
            ob_high = df['high'].loc[ob_idx]
            ob_low = df['low'].loc[ob_idx]
            mitigated = False

            # Cek mitigasi: jika close < ob.low
            for j in range(ob_idx + 1, len(df)):
                if df['close'].iloc[j] < ob_low:
                    mitigated = True
                    break

            order_blocks.append(OrderBlock(
                index=int(ob_idx),
                high=float(ob_high),
                low=float(ob_low),
                bias=1,  # BULLISH
                mitigated=mitigated
            ))

    # Sort by index
    order_blocks.sort(key=lambda ob: ob.index)

    return order_blocks


def detect_fvg(df: pd.DataFrame) -> list[FairValueGap]:
    """
    Detect Fair Value Gaps (FVG).

    Bullish FVG: candle[-1].low > candle[-3].high (ada gap di atas candle 2 bars lalu)
    Bearish FVG: candle[-1].high < candle[-3].low (ada gap di bawah candle 2 bars lalu)

    Args:
        df: DataFrame dengan kolom 'high', 'low', 'close'

    Returns:
        list[FairValueGap]: Daftar FVG yang terdeteksi
    """
    if len(df) < 3:
        return []

    fvgs = []

    # Loop mulai dari candle ke-3 (index 2)
    for i in range(2, len(df)):
        # Bullish FVG: low candle saat ini > high candle 2 bar lalu
        # Dalam Python indexing: df['low'].iloc[i] > df['high'].iloc[i-2]
        if df['low'].iloc[i] > df['high'].iloc[i-2]:
            # Gap antara candle[i-2].high dan candle[i].low
            top = df['low'].iloc[i]
            bottom = df['high'].iloc[i-2]

            # Cek apakah sudah filled (harga masuk ke gap)
            filled = False
            for j in range(i+1, len(df)):
                if df['low'].iloc[j] < top and df['high'].iloc[j] > bottom:
                    filled = True
                    break

            fvgs.append(FairValueGap(
                index=i,
                top=float(top),
                bottom=float(bottom),
                bias=1,  # BULLISH
                filled=filled
            ))

        # Bearish FVG: high candle saat ini < low candle 2 bar lalu
        elif df['high'].iloc[i] < df['low'].iloc[i-2]:
            # Gap antara candle[i].high dan candle[i-2].low
            top = df['low'].iloc[i-2]
            bottom = df['high'].iloc[i]

            # Cek filled
            filled = False
            for j in range(i+1, len(df)):
                if df['low'].iloc[j] < top and df['high'].iloc[j] > bottom:
                    filled = True
                    break

            fvgs.append(FairValueGap(
                index=i,
                top=float(top),
                bottom=float(bottom),
                bias=-1,  # BEARISH
                filled=filled
            ))

    return fvgs


def detect_bos_choch(df: pd.DataFrame, lookback: int = 50) -> list[BOSCHOCHSignal]:
    """
    Detect Break of Structure (BOS) dan Change of Character (CHOCH).

    BOS: Breakout yang searah dengan trend
    CHOCH: Breakout yang berlawanan dengan trend (reversal signal)

    Logika:
    - Bullish BOS: close crossover swingHigh.currentLevel DAN trend sebelumnya BULLISH
    - Bearish BOS: close crossunder swingLow.currentLevel DAN trend sebelumnya BEARISH
    - Bullish CHOCH: close crossover swingHigh.currentLevel DAN trend sebelumnya BEARISH
    - Bearish CHOCH: close crossunder swingLow.currentLevel DAN trend sebelumnya BULLISH

    Args:
        df: DataFrame dengan kolom 'high', 'low', 'close'
        lookback: Jumlah candle untuk identifikasi swing (default 50)

    Returns:
        list[BOSCHOCHSignal]: Daftar sinyal BOS/CHOCH
    """
    if len(df) < lookback * 2:
        return []

    signals = []

    # Identify swing points (similar to detect_order_blocks)
    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(df) - lookback):
        # Check swing high
        is_swing_high = True
        for j in range(1, lookback + 1):
            if df['high'].iloc[i] <= df['high'].iloc[i-j] or df['high'].iloc[i] <= df['high'].iloc[i+j]:
                is_swing_high = False
                break
        if is_swing_high:
            swing_highs.append((i, df['high'].iloc[i]))

        # Check swing low
        is_swing_low = True
        for j in range(1, lookback + 1):
            if df['low'].iloc[i] >= df['low'].iloc[i-j] or df['low'].iloc[i] >= df['low'].iloc[i+j]:
                is_swing_low = False
                break
        if is_swing_low:
            swing_lows.append((i, df['low'].iloc[i]))

    # Track current trend bias
    current_bias = 0  # 0 = neutral, 1 = bullish, -1 = bearish

    # Track current swing levels
    current_swing_high = None
    current_swing_low = None

    swing_high_idx = 0
    swing_low_idx = 0

    # Process each candle
    for i in range(lookback, len(df)):
        # Update current swing levels
        while swing_high_idx < len(swing_highs) and swing_highs[swing_high_idx][0] <= i:
            current_swing_high = swing_highs[swing_high_idx][1]
            swing_high_idx += 1

        while swing_low_idx < len(swing_lows) and swing_lows[swing_low_idx][0] <= i:
            current_swing_low = swing_lows[swing_low_idx][1]
            swing_low_idx += 1

        # Skip jika belum ada swing levels
        if current_swing_high is None or current_swing_low is None:
            continue

        close = df['close'].iloc[i]

        # Check for bullish break (close > swing high)
        if close > current_swing_high:
            # BOS jika trend sebelumnya bullish, CHOCH jika bearish
            signal_type = 'BOS' if current_bias == 1 else 'CHOCH'
            signals.append(BOSCHOCHSignal(
                index=i,
                type=signal_type,
                bias=1,  # BULLISH
                level=float(current_swing_high)
            ))
            current_bias = 1

        # Check for bearish break (close < swing low)
        elif close < current_swing_low:
            # BOS jika trend sebelumnya bearish, CHOCH jika bullish
            signal_type = 'BOS' if current_bias == -1 else 'CHOCH'
            signals.append(BOSCHOCHSignal(
                index=i,
                type=signal_type,
                bias=-1,  # BEARISH
                level=float(current_swing_low)
            ))
            current_bias = -1

    return signals
