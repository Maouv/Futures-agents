"""
risk_agent.py — Kalkulasi risk management (SL, TP, position size).
"""
import pandas as pd
from pydantic import BaseModel
from typing import Optional

from src.agents.math.base_agent import BaseAgent
from src.config.settings import settings
from src.indicators.helpers import calculate_atr
from src.indicators.luxalgo_smc import OrderBlock


class RiskResult(BaseModel):
    """Output dari RiskAgent."""
    entry_price: float
    sl_price: float
    tp_price: float
    position_size: float    # Dalam kontrak/qty
    risk_usd: float         # Actual risk dalam USD
    reward_usd: float       # Potential reward dalam USD
    rr_ratio: float         # Actual RR
    leverage: int
    margin_required: float  # Modal yang dibutuhkan


class RiskAgent(BaseAgent):
    """
    Kalkulasi risk management berdasarkan ATR dan settings.

    Input: signal, OrderBlock, DataFrame untuk ATR
    Output: RiskResult
    """

    def run(
        self,
        signal: str,
        order_block: OrderBlock,
        df: pd.DataFrame,
        atr_period: int = 14
    ) -> RiskResult:
        """
        Jalankan risk calculation.

        Args:
            signal: 'LONG' atau 'SHORT'
            order_block: OrderBlock yang relevan
            df: DataFrame untuk kalkulasi ATR
            atr_period: Period untuk ATR

        Returns:
            RiskResult dengan SL, TP, dan position size
        """
        if signal not in ["LONG", "SHORT"]:
            raise ValueError(f"Signal harus 'LONG' atau 'SHORT', dapat: {signal}")

        if df.empty or len(df) < atr_period:
            raise ValueError(f"Data tidak cukup untuk ATR (minimal {atr_period} candle)")

        # Calculate ATR
        atr_series = calculate_atr(df, period=atr_period)
        atr = atr_series.iloc[-1]

        # Entry price = OB midpoint
        entry_price = (order_block.high + order_block.low) / 2

        # Calculate SL based on signal direction
        if signal == "LONG":
            sl_price = order_block.low - (atr * 0.5)
        else:  # SHORT
            sl_price = order_block.high + (atr * 0.5)

        # Calculate risk distance
        risk_distance = abs(entry_price - sl_price)

        # Validate risk distance
        if risk_distance == 0 or risk_distance < 0.01:
            raise ValueError(f"Risk distance terlalu kecil atau nol: {risk_distance}")

        # Calculate TP based on Risk:Reward ratio from settings
        rr_ratio = settings.RISK_REWARD_RATIO
        if signal == "LONG":
            tp_price = entry_price + (risk_distance * rr_ratio)
        else:  # SHORT
            tp_price = entry_price - (risk_distance * rr_ratio)

        # Calculate position size
        # Formula: (Risk USD * leverage) / risk_distance
        leverage = settings.FUTURES_DEFAULT_LEVERAGE
        risk_usd = settings.RISK_PER_TRADE_USD
        position_size = (risk_usd * leverage) / risk_distance

        # Calculate margin required
        margin_required = (position_size * entry_price) / leverage

        # Calculate actual reward
        reward_usd = risk_usd * rr_ratio

        self._log(
            f"Signal: {signal} | Entry: {entry_price:.2f} | "
            f"SL: {sl_price:.2f} | TP: {tp_price:.2f} | "
            f"Risk: ${risk_usd:.2f} | Reward: ${reward_usd:.2f} | "
            f"Size: {position_size:.4f} | Leverage: {leverage}x"
        )

        return RiskResult(
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            position_size=position_size,
            risk_usd=risk_usd,
            reward_usd=reward_usd,
            rr_ratio=rr_ratio,
            leverage=leverage,
            margin_required=margin_required
        )
