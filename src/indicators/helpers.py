"""
helpers.py — Fungsi utility untuk kalkulasi indikator.
Semua fungsi WAJIB pure Python/pandas — DILARANG pakai LLM.
"""
from typing import Union
import pandas as pd
import numpy as np


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Hitung Average True Range menggunakan Wilder's smoothing (EMA).
    Sama dengan TradingView default.
    """
    high  = df['high']
    low   = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low  - close.shift(1)).abs()

    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()

    return atr


def find_swing_highs(df: pd.DataFrame, size: int = 50) -> pd.Series:
    """
    Port dari fungsi leg() LuxAlgo PineScript.

    PineScript asli:
        newLegHigh = high[size] > ta.highest(size)
        → high pada 'size' bar lalu LEBIH TINGGI dari highest dalam 'size' bar terakhir

    Artinya: candle di posisi i adalah swing high jika
        high[i] > max(high[i+1 .. i+size])   ← lebih tinggi dari semua candle SETELAHNYA
        high[i] > max(high[i-size .. i-1])   ← lebih tinggi dari semua candle SEBELUMNYA

    PENTING: size=50 butuh minimal 100 candle (50 kiri + 50 kanan).
    Gunakan size=5 jika data < 200 candle untuk mendapat hasil yang reasonable.
    """
    high           = df['high']
    n              = len(df)
    is_swing_high  = pd.Series(False, index=df.index)

    for i in range(size, n - size):
        candidate      = high.iloc[i]
        left_window    = high.iloc[i - size : i]        # size candle di kiri
        right_window   = high.iloc[i + 1   : i + size + 1]  # size candle di kanan

        if candidate > left_window.max() and candidate > right_window.max():
            is_swing_high.iloc[i] = True

    return is_swing_high


def find_swing_lows(df: pd.DataFrame, size: int = 50) -> pd.Series:
    """
    Port dari fungsi leg() LuxAlgo PineScript — sisi low.

    Candle di posisi i adalah swing low jika
        low[i] < min(low[i+1 .. i+size])
        low[i] < min(low[i-size .. i-1])
    """
    low           = df['low']
    n             = len(df)
    is_swing_low  = pd.Series(False, index=df.index)

    for i in range(size, n - size):
        candidate     = low.iloc[i]
        left_window   = low.iloc[i - size : i]
        right_window  = low.iloc[i + 1   : i + size + 1]

        if candidate < left_window.min() and candidate < right_window.min():
            is_swing_low.iloc[i] = True

    return is_swing_low


def crossover(series: pd.Series, level: Union[pd.Series, float]) -> pd.Series:
    """True pada bar dimana series naik melewati level."""
    if isinstance(level, (int, float)):
        prev_below = series.shift(1) <= level
        curr_above = series > level
    else:
        prev_below = series.shift(1) <= level.shift(1)
        curr_above = series > level
    return prev_below & curr_above


def crossunder(series: pd.Series, level: Union[pd.Series, float]) -> pd.Series:
    """True pada bar dimana series turun melewati level."""
    if isinstance(level, (int, float)):
        prev_above = series.shift(1) >= level
        curr_below = series < level
    else:
        prev_above = series.shift(1) >= level.shift(1)
        curr_below = series < level
    return prev_above & curr_below

