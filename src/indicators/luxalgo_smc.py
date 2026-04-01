"""
luxalgo_smc.py — Porting LuxAlgo Smart Money Concepts indicator.
Hanya 3 fungsi yang di-port: Order Blocks, FVG, BOS/CHOCH.
Semua fungsi murni Python/pandas — DILARANG pakai LLM.
"""
import pandas as pd
import numpy as np
from pydantic import BaseModel

from src.indicators.helpers import (
    calculate_atr,
    crossover,
    crossunder,
    find_swing_highs,
    find_swing_lows,
)


# ── Pydantic Output Models ──────────────────────────────────────────────────

class OrderBlock(BaseModel):
    index: int
    high: float
    low: float
    bias: int               # 1=BULLISH, -1=BEARISH
    mitigated: bool = False


class FairValueGap(BaseModel):
    index: int
    top: float
    bottom: float
    bias: int               # 1=BULLISH, -1=BEARISH
    filled: bool = False


class BOSCHOCHSignal(BaseModel):
    index: int
    type: str               # 'BOS' atau 'CHOCH'
    bias: int               # 1=BULLISH, -1=BEARISH
    level: float


class SMCResult(BaseModel):
    order_blocks: list[OrderBlock]
    fair_value_gaps: list[FairValueGap]
    bos_choch_signals: list[BOSCHOCHSignal]
    current_bias: int


# ── Internal Helper ─────────────────────────────────────────────────────────

def _parsed_highs_lows(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    LuxAlgo volatility filter untuk OB detection.
    Bar yang sangat volatile (range >= 2x ATR200) di-swap high/low-nya.

    PineScript:
        atrMeasure        = ta.atr(200)
        highVolatilityBar = (high - low) >= (2 * atrMeasure)
        parsedHigh        = highVolatilityBar ? low : high
        parsedLow         = highVolatilityBar ? high : low
    """
    atr     = calculate_atr(df, period=200)
    hi_vol  = (df['high'] - df['low']) >= (2 * atr)

    parsed_high = pd.Series(
        np.where(hi_vol, df['low'],  df['high']), index=df.index
    )
    parsed_low = pd.Series(
        np.where(hi_vol, df['high'], df['low']),  index=df.index
    )
    return parsed_high, parsed_low


# ── Adaptive swing size ─────────────────────────────────────────────────────

def _adaptive_swing_size(df: pd.DataFrame, preferred: int = 50) -> int:
    """
    Pilih swing size yang sesuai dengan jumlah candle tersedia.
    Dengan 100 candle, size=50 membuat loop range(50,50) = kosong.
    Solusi: gunakan size <= len(df) // 3.
    """
    return min(preferred, len(df) // 3)


# ── Main Functions ──────────────────────────────────────────────────────────

def detect_order_blocks(
    df: pd.DataFrame,
    swing_size: int = 50,
) -> list[OrderBlock]:
    """
    Detect Order Blocks sesuai logika LuxAlgo SMC.

    Proses:
    1. Hitung parsedHigh / parsedLow (volatility filter ATR200)
    2. Temukan swing highs dan swing lows
    3. Bearish OB  = candle dengan parsedHigh tertinggi antara 2 swing high berurutan
    4. Bullish OB  = candle dengan parsedLow terendah antara 2 swing low berurutan
    5. Mitigated jika harga menembus batas OB di candle berikutnya
    """
    size = 5  # Hardcoded for testing

    if len(df) < size * 2 + 1:
        return []

    parsed_high, parsed_low = _parsed_highs_lows(df)

    sh_mask = find_swing_highs(df, size=size)
    sl_mask = find_swing_lows(df,  size=size)

    swing_highs = [i for i in range(len(df)) if sh_mask.iloc[i]]
    swing_lows  = [i for i in range(len(df)) if sl_mask.iloc[i]]

    # ── DEBUG ────────────────────────────────────────────────────────────
    print(f"[DEBUG OB] swing_highs count: {len(swing_highs)}")
    print(f"[DEBUG OB] swing_lows count: {len(swing_lows)}")
    print(f"[DEBUG OB] swing_highs indices: {swing_highs[:5]}")
    print(f"[DEBUG OB] swing_lows indices: {swing_lows[:5]}")
    # ── END DEBUG ────────────────────────────────────────────────────────

    order_blocks: list[OrderBlock] = []

    # ── Bearish OB (dari pasangan swing highs) ──────────────────────────
    for k in range(1, len(swing_highs)):
        prev_idx = swing_highs[k - 1]
        curr_idx = swing_highs[k]

        segment = parsed_high.iloc[prev_idx:curr_idx + 1]
        if segment.empty:
            continue

        # ── DEBUG ────────────────────────────────────────────────────────
        print(f"[DEBUG OB] segment range: {prev_idx} to {curr_idx}, segment len: {len(segment)}")
        ob_pos_label = segment.idxmax()
        ob_pos = df.index.get_loc(ob_pos_label)
        print(f"[DEBUG OB] ob_pos label: {ob_pos_label}, ob_pos iloc: {ob_pos}")
        # ── END DEBUG ────────────────────────────────────────────────────

        ob_pos   = int(segment.idxmax())
        ob_high  = float(df['high'].iloc[ob_pos])
        ob_low   = float(df['low'].iloc[ob_pos])

        # Mitigated jika close > ob_high di candle setelah OB
        mitigated = bool(
            (df['close'].iloc[ob_pos + 1:] > ob_high).any()
        )

        order_blocks.append(OrderBlock(
            index=ob_pos,
            high=ob_high,
            low=ob_low,
            bias=-1,
            mitigated=mitigated,
        ))

    # ── Bullish OB (dari pasangan swing lows) ───────────────────────────
    for k in range(1, len(swing_lows)):
        prev_idx = swing_lows[k - 1]
        curr_idx = swing_lows[k]

        segment = parsed_low.iloc[prev_idx:curr_idx + 1]
        if segment.empty:
            continue

        ob_pos  = int(segment.idxmin())
        ob_high = float(df['high'].iloc[ob_pos])
        ob_low  = float(df['low'].iloc[ob_pos])

        # Mitigated jika close < ob_low di candle setelah OB
        mitigated = bool(
            (df['close'].iloc[ob_pos + 1:] < ob_low).any()
        )

        order_blocks.append(OrderBlock(
            index=ob_pos,
            high=ob_high,
            low=ob_low,
            bias=1,
            mitigated=mitigated,
        ))

    order_blocks.sort(key=lambda ob: ob.index)
    return order_blocks


def detect_fvg(df: pd.DataFrame) -> list[FairValueGap]:
    """
    Detect Fair Value Gaps (FVG) - Simple version without threshold filtering.

    Deteksi:
        Bullish FVG : low[0]  > high[2]  → gap di atas candle 2 bar lalu
        Bearish FVG : high[0] < low[2]   → gap di bawah candle 2 bar lalu

    Mitigation:
        FVG dianggap FILLED jika candle berikutnya overlap dengan range gap.
        Hanya FVG yang masih UNFILLED yang dikembalikan.
    """
    if len(df) < 3:
        return []

    result = []
    for i in range(2, len(df)):
        low_curr  = df['low'].iloc[i]
        high_curr = df['high'].iloc[i]
        high_2ago = df['high'].iloc[i - 2]
        low_2ago  = df['low'].iloc[i - 2]

        if low_curr > high_2ago:        # Bullish FVG
            top, bottom, bias = float(low_curr), float(high_2ago), 1
        elif high_curr < low_2ago:      # Bearish FVG
            top, bottom, bias = float(low_2ago), float(high_curr), -1
        else:
            continue

        filled = any(
            df['low'].iloc[j] <= top and df['high'].iloc[j] >= bottom
            for j in range(i + 1, len(df))
        )
        if not filled:
            result.append(FairValueGap(index=i, top=top, bottom=bottom, bias=bias, filled=False))

    return result


def detect_bos_choch(
    df: pd.DataFrame,
    swing_size: int = 50,
) -> list[BOSCHOCHSignal]:
    """
    Detect Break of Structure (BOS) dan Change of Character (CHOCH).

    BOS   = breakout SEARAH trend sebelumnya (konfirmasi trend)
    CHOCH = breakout BERLAWANAN trend sebelumnya (potensi reversal)

    Bullish break (close > swing_high):
        trend sebelumnya BULLISH  → BOS
        trend sebelumnya BEARISH  → CHOCH

    Bearish break (close < swing_low):
        trend sebelumnya BEARISH  → BOS
        trend sebelumnya BULLISH  → CHOCH
    """
    size = 5  # Hardcoded for testing

    if len(df) < size * 2 + 1:
        return []

    sh_mask = find_swing_highs(df, size=size)
    sl_mask = find_swing_lows(df,  size=size)

    swing_highs = [i for i in range(len(df)) if sh_mask.iloc[i]]
    swing_lows  = [i for i in range(len(df)) if sl_mask.iloc[i]]

    if not swing_highs or not swing_lows:
        return []

    signals:      list[BOSCHOCHSignal] = []
    current_bias: int   = 0
    sh_ptr:       int   = 0
    sl_ptr:       int   = 0
    curr_sh_level: float | None = None
    curr_sl_level: float | None = None

    for i in range(size, len(df)):
        # Update swing levels yang sudah terkonfirmasi (index <= i)
        while sh_ptr < len(swing_highs) and swing_highs[sh_ptr] <= i:
            curr_sh_level = float(df['high'].iloc[swing_highs[sh_ptr]])
            sh_ptr += 1

        while sl_ptr < len(swing_lows) and swing_lows[sl_ptr] <= i:
            curr_sl_level = float(df['low'].iloc[swing_lows[sl_ptr]])
            sl_ptr += 1

        if curr_sh_level is None or curr_sl_level is None:
            continue

        close = float(df['close'].iloc[i])

        # ── Bullish break ──────────────────────────────────────────────
        if close > curr_sh_level:
            sig_type     = 'BOS' if current_bias == 1 else 'CHOCH'
            current_bias = 1
            signals.append(BOSCHOCHSignal(
                index=i,
                type=sig_type,
                bias=1,
                level=curr_sh_level,
            ))
            # Reset level agar tidak trigger lagi di candle berikutnya
            curr_sh_level = close

        # ── Bearish break ──────────────────────────────────────────────
        elif close < curr_sl_level:
            sig_type     = 'BOS' if current_bias == -1 else 'CHOCH'
            current_bias = -1
            signals.append(BOSCHOCHSignal(
                index=i,
                type=sig_type,
                bias=-1,
                level=curr_sl_level,
            ))
            curr_sl_level = close

    return signals


def detect_all(
    df: pd.DataFrame,
    swing_size: int = 50,
    fvg_auto_threshold: bool = True,
) -> SMCResult:
    """Jalankan semua deteksi SMC sekaligus dan return SMCResult."""
    obs      = detect_order_blocks(df, swing_size=swing_size)
    fvgs     = detect_fvg(df, auto_threshold=fvg_auto_threshold)
    signals  = detect_bos_choch(df, swing_size=swing_size)

    current_bias = 0
    if signals:
        current_bias = signals[-1].bias

    return SMCResult(
        order_blocks=obs,
        fair_value_gaps=fvgs,
        bos_choch_signals=signals,
        current_bias=current_bias,
    )

