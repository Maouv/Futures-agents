"""
mean_reversion.py — RSI dan Bollinger Bands.
Boleh menggunakan pandas-ta untuk kalkulasi.
"""
import pandas as pd
import pandas_ta as pta
from pydantic import BaseModel


class MeanReversionResult(BaseModel):
    """Container untuk hasil mean reversion indicators."""
    rsi: float                  # 0-100
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_position: float          # -1.0 (bawah lower) sampai +1.0 (atas upper), 0 = middle
    rsi_signal: str             # 'OVERSOLD', 'OVERBOUGHT', 'NEUTRAL'


def calculate_mean_reversion(df: pd.DataFrame, rsi_period: int = 14, bb_period: int = 20, bb_std: float = 2.0) -> MeanReversionResult:
    """
    Hitung RSI(14) dan Bollinger Bands(20, 2.0).
    Parameter default ini WAJIB sama dengan TradingView default.

    Args:
        df: DataFrame dengan kolom 'close', 'high', 'low'
        rsi_period: Periode RSI (default 14)
        bb_period: Periode Bollinger Bands (default 20)
        bb_std: Standard deviation untuk BB (default 2.0)

    Returns:
        MeanReversionResult: Hasil kalkulasi RSI dan Bollinger Bands
    """
    if len(df) < max(rsi_period, bb_period) + 1:
        raise ValueError(f"DataFrame harus memiliki minimal {max(rsi_period, bb_period) + 1} candles")

    # Calculate RSI menggunakan pandas-ta
    rsi_series = pta.rsi(df['close'], length=rsi_period)
    rsi = float(rsi_series.iloc[-1])

    # Calculate Bollinger Bands menggunakan pandas-ta
    # pandas-ta mengembalikan DataFrame dengan kolom: BBL_N_S_S, BBM_N_S_S, BBU_N_S_S
    bb_df = pta.bbands(df['close'], length=bb_period, std=bb_std)

    # Extract values dari baris terakhir
    # Column names have format: BBL_{length}_{std}_{std}
    bb_lower = float(bb_df[f'BBL_{bb_period}_{bb_std}_{bb_std}'].iloc[-1])
    bb_middle = float(bb_df[f'BBM_{bb_period}_{bb_std}_{bb_std}'].iloc[-1])
    bb_upper = float(bb_df[f'BBU_{bb_period}_{bb_std}_{bb_std}'].iloc[-1])

    # Calculate BB position (-1 to +1)
    # -1 = di bawah lower band
    #  0 = di middle band
    # +1 = di atas upper band
    close = float(df['close'].iloc[-1])
    bb_range = bb_upper - bb_lower

    if bb_range > 0:
        bb_position = (close - bb_middle) / (bb_range / 2)
    else:
        bb_position = 0.0

    # Determine RSI signal
    if rsi < 30:
        rsi_signal = 'OVERSOLD'
    elif rsi > 70:
        rsi_signal = 'OVERBOUGHT'
    else:
        rsi_signal = 'NEUTRAL'

    return MeanReversionResult(
        rsi=rsi,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        bb_position=bb_position,
        rsi_signal=rsi_signal
    )
