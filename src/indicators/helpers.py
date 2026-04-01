"""
helpers.py — Fungsi utility untuk kalkulasi indikator.
Semua fungsi WAJIB pure Python/pandas — DILARANG pakai LLM.
"""
from typing import Optional, Union
import pandas as pd
import numpy as np


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Hitung Average True Range.
    Gunakan EMA (Wilder's smoothing) bukan SMA — sama dengan TradingView default.

    Args:
        df: DataFrame dengan kolom 'high', 'low', 'close'
        period: Periode ATR (default 14)

    Returns:
        pd.Series: Nilai ATR
    """
    # True Range = max(high - low, abs(high - close_prev), abs(low - close_prev))
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder's smoothing (EMA dengan alpha = 1/period)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    return atr


def find_swing_highs(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """
    Identifikasi swing high points.
    Swing high = candle dimana high-nya lebih tinggi dari `lookback` candle di kiri dan kanan.

    Args:
        df: DataFrame dengan kolom 'high'
        lookback: Jumlah candle di kiri dan kanan untuk validasi (default 5)

    Returns:
        pd.Series: Boolean series, True jika candle adalah swing high
    """
    high = df['high']

    # Swing high jika high saat ini > high N candle sebelumnya DAN N candle sesudahnya
    # Karena kita tidak bisa melihat masa depan, kita identifikasi swing high dengan delay
    # Swing high di candle i terdeteksi di candle i+lookback

    is_swing_high = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        current_high = high.iloc[i]

        # Cek apakah lebih tinggi dari lookback candles di kiri
        left_highs = high.iloc[i-lookback:i]
        left_condition = (current_high > left_highs).all()

        # Cek apakah lebih tinggi dari lookback candles di kanan
        right_highs = high.iloc[i+1:i+lookback+1]
        right_condition = (current_high > right_highs).all()

        is_swing_high.iloc[i] = left_condition and right_condition

    return is_swing_high


def find_swing_lows(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """
    Identifikasi swing low points.
    Swing low = candle dimana low-nya lebih rendah dari `lookback` candle di kiri dan kanan.

    Args:
        df: DataFrame dengan kolom 'low'
        lookback: Jumlah candle di kiri dan kanan untuk validasi (default 5)

    Returns:
        pd.Series: Boolean series, True jika candle adalah swing low
    """
    low = df['low']

    is_swing_low = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        current_low = low.iloc[i]

        # Cek apakah lebih rendah dari lookback candles di kiri
        left_lows = low.iloc[i-lookback:i]
        left_condition = (current_low < left_lows).all()

        # Cek apakah lebih rendah dari lookback candles di kanan
        right_lows = low.iloc[i+1:i+lookback+1]
        right_condition = (current_low < right_lows).all()

        is_swing_low.iloc[i] = left_condition and right_condition

    return is_swing_low


def crossover(series: pd.Series, level: Union[pd.Series, float]) -> pd.Series:
    """
    True pada baris dimana series naik melewati level.

    Args:
        series: Series yang akan dicek
        level: Level harga atau Series lain

    Returns:
        pd.Series: Boolean series, True saat crossover terjadi
    """
    if isinstance(level, (int, float)):
        prev_below = series.shift(1) <= level
        curr_above = series > level
    else:
        # level adalah Series
        prev_below = series.shift(1) <= level.shift(1)
        curr_above = series > level

    return prev_below & curr_above


def crossunder(series: pd.Series, level: Union[pd.Series, float]) -> pd.Series:
    """
    True pada baris dimana series turun melewati level.

    Args:
        series: Series yang akan dicek
        level: Level harga atau Series lain

    Returns:
        pd.Series: Boolean series, True saat crossunder terjadi
    """
    if isinstance(level, (int, float)):
        prev_above = series.shift(1) >= level
        curr_below = series < level
    else:
        # level adalah Series
        prev_above = series.shift(1) >= level.shift(1)
        curr_below = series < level

    return prev_above & curr_below
