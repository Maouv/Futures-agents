"""
helpers.py — Fungsi utility untuk kalkulasi indikator.
Semua fungsi WAJIB pure Python/pandas — DILARANG pakai LLM.
"""
from typing import Union
import pandas as pd


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


def find_swing_highs(df: pd.DataFrame, size: int = 5) -> pd.Series:
    """
    Port ta.pivothigh(size, size) dari PineScript.
    Pivot high di candle i jika:
    - high[i] > semua high di i-size sampai i-1 (kiri)
    - high[i] > semua high di i+1 sampai i+size (kanan)
    Deteksi delayed — pivot di candle i baru diketahui di candle i+size.
    """
    high = df['high']
    n = len(df)
    is_swing_high = pd.Series(False, index=df.index)

    for i in range(size, n - size):
        candidate = high.iloc[i]
        left_ok  = all(candidate > high.iloc[i - size : i])
        right_ok = all(candidate > high.iloc[i + 1 : i + size + 1])
        if left_ok and right_ok:
            is_swing_high.iloc[i] = True

    return is_swing_high


def find_swing_lows(df: pd.DataFrame, size: int = 5) -> pd.Series:
    """
    Port ta.pivotlow(size, size) dari PineScript.
    Pivot low di candle i jika:
    - low[i] < semua low di i-size sampai i-1 (kiri)
    - low[i] < semua low di i+1 sampai i+size (kanan)
    Deteksi delayed — pivot di candle i baru diketahui di candle i+size.
    """
    low = df['low']
    n = len(df)
    is_swing_low = pd.Series(False, index=df.index)

    for i in range(size, n - size):
        candidate = low.iloc[i]
        left_ok  = all(candidate < low.iloc[i - size : i])
        right_ok = all(candidate < low.iloc[i + 1 : i + size + 1])
        if left_ok and right_ok:
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

