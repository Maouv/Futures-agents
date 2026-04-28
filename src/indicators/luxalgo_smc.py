"""
luxalgo_smc.py — Adapter atas smartmoneyconcepts library (joshyattridge/smart-money-concepts).

Strategi porting:
  - Backend kalkulasi: _smc_core.smc (vectorized numpy, teruji, tanpa debug prints)
  - Output: Pydantic models yang sama persis dengan Phase 2 schema
  - 3 fungsi publik: detect_order_blocks, detect_fvg, detect_bos_choch
  - 1 fungsi aggregator: detect_all

Alasan ganti dari implementasi manual:
  - Implementasi sebelumnya punya bug kritis: segment.idxmax() mengembalikan label
    (bisa datetime) bukan integer posisi, menyebabkan crash saat index bukan RangeIndex.
  - _smc_core sudah divalidasi terhadap TradingView di unit test upstream.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from src.indicators._smc_core import smc as _smc

# ── Pydantic Output Models (tidak berubah dari Phase 2) ─────────────────────

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
    broken_index: int       # Index candle konfirmasi (confirmation candle)
    type: str               # 'BOS' atau 'CHOCH'
    bias: int               # 1=BULLISH, -1=BEARISH
    level: float


class SMCResult(BaseModel):
    order_blocks: list[OrderBlock]
    fair_value_gaps: list[FairValueGap]
    bos_choch_signals: list[BOSCHOCHSignal]
    current_bias: int


# ── Internal: pastikan kolom volume ada ─────────────────────────────────────

def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare DataFrame untuk _smc_core — reset index, pastikan RangeIndex.

    Fix untuk pandas 3.0.2 compatibility:
    - Reset index ke RangeIndex (hindari iloc return DataFrame)
    - Lowercase semua kolom
    - Pastikan hanya kolom OHLCV yang dikirim
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    df = df.reset_index(drop=True)

    # Pastikan kolom yang diperlukan ada
    required_cols = ['open', 'high', 'low', 'close']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Tambah volume jika tidak ada
    if 'volume' not in df.columns:
        df['volume'] = 1000.0

    return df[['open', 'high', 'low', 'close', 'volume']].copy()


def _ensure_volume(df: pd.DataFrame) -> pd.DataFrame:
    """Deprecated: gunakan _prepare_df() instead."""
    if "volume" not in df.columns:
        df = df.copy()
        df["volume"] = 1000.0
    return df


# ── Public Functions ─────────────────────────────────────────────────────────

def detect_order_blocks(
    df: pd.DataFrame,
    swing_length: int = 5,
) -> list[OrderBlock]:
    df = _prepare_df(df)
    swing_hl = _smc.swing_highs_lows(df, swing_length=swing_length)
    ob_df    = _smc.ob(df, swing_hl)

    result: list[OrderBlock] = []
    for i in range(len(ob_df)):
        ob_val = ob_df["OB"].iloc[i]
        if np.isnan(ob_val):
            continue
        mit_idx   = ob_df["MitigatedIndex"].iloc[i]
        mitigated = not np.isnan(mit_idx) and int(mit_idx) != 0
        result.append(OrderBlock(
            index=i,
            high=float(ob_df["Top"].iloc[i]),
            low=float(ob_df["Bottom"].iloc[i]),
            bias=int(ob_val),
            mitigated=mitigated,
        ))
    return result


def detect_fvg(df: pd.DataFrame) -> list[FairValueGap]:
    df = _prepare_df(df)
    fvg_df = _smc.fvg(df)

    result: list[FairValueGap] = []
    for i in range(len(fvg_df)):
        fvg_val = fvg_df["FVG"].iloc[i]
        if np.isnan(fvg_val):
            continue
        mit_idx = fvg_df["MitigatedIndex"].iloc[i]
        filled  = not np.isnan(mit_idx) and int(mit_idx) != 0
        result.append(FairValueGap(
            index=i,
            top=float(fvg_df["Top"].iloc[i]),
            bottom=float(fvg_df["Bottom"].iloc[i]),
            bias=int(fvg_val),
            filled=filled,
        ))
    return result


def detect_bos_choch(
    df: pd.DataFrame,
    swing_length: int = 10,
) -> list[BOSCHOCHSignal]:
    df = _prepare_df(df)
    swing_hl = _smc.swing_highs_lows(df, swing_length=swing_length)
    bc_df    = _smc.bos_choch(df, swing_hl)

    result: list[BOSCHOCHSignal] = []

    # Filter rows where BOS or CHOCH != 0 (vectorized approach)
    # Handle NaN: replace with 0 for comparison
    bos_series = bc_df["BOS"].fillna(0)
    choch_series = bc_df["CHOCH"].fillna(0)

    signals_df = bc_df[(bos_series != 0) | (choch_series != 0)].copy()

    # Iterate over filtered signals
    for idx, row in signals_df.iterrows():
        bos_val = row["BOS"]
        choch_val = row["CHOCH"]
        level_val = row["Level"]

        # Guard FLAG 1: BrokenIndex adalah float64, cek NaN sebelum convert ke int
        broken_raw = row["BrokenIndex"]
        safe_broken_index = int(broken_raw) if (not np.isnan(broken_raw) and broken_raw > 0) else idx

        # Check if BOS signal
        if not np.isnan(bos_val) and bos_val != 0:
            result.append(BOSCHOCHSignal(
                index=idx,
                broken_index=safe_broken_index,
                type="BOS",
                bias=int(bos_val),
                level=float(level_val)
            ))
        # Else check if CHOCH signal
        elif not np.isnan(choch_val) and choch_val != 0:
            result.append(BOSCHOCHSignal(
                index=idx,
                broken_index=safe_broken_index,
                type="CHOCH",
                bias=int(choch_val),
                level=float(level_val)
            ))

    result.sort(key=lambda s: s.index)
    return result


def detect_all(
    df: pd.DataFrame,
    swing_length_ob: int = 5,
    swing_length_bos: int = 10,
) -> SMCResult:
    obs     = detect_order_blocks(df, swing_length=swing_length_ob)
    fvgs    = detect_fvg(df)
    signals = detect_bos_choch(df, swing_length=swing_length_bos)

    current_bias = signals[-1].bias if signals else 0

    return SMCResult(
        order_blocks=obs,
        fair_value_gaps=fvgs,
        bos_choch_signals=signals,
        current_bias=current_bias,
    )
