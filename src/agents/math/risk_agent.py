"""
risk_agent.py — Kalkulasi risk management (SL, TP, position size).

OB Midpoint Overlap Handling:
- Jika harga sudah melewati OB midpoint tapi MASIH di dalam OB zone
  → adjust entry ke current_price, recalculate SL/TP dari current_price
- Jika harga sudah di LUAR OB zone → raise OverlapSkipError (trade di-skip)
- Minimum SL buffer = 0.5 * ATR agar SL tidak terlalu dekat
"""
import pandas as pd
from pydantic import BaseModel
from typing import Optional

from src.agents.math.base_agent import BaseAgent
from src.config.settings import settings
from src.indicators.helpers import calculate_atr
from src.indicators.luxalgo_smc import OrderBlock


class OverlapSkipError(ValueError):
    """Harga sudah di luar OB zone — trade harus di-skip."""
    pass


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
    entry_adjusted: bool = False  # True jika entry di-adjust dari midpoint ke current price


class RiskAgent(BaseAgent):
    """
    Kalkulasi risk management berdasarkan ATR dan settings.

    Input: signal, OrderBlock, DataFrame untuk ATR
    Output: RiskResult

    OB Midpoint Overlap Logic:
        - Midpoint = ideal entry (OB high+low / 2)
        - Jika current_price melewati midpoint tapi masih di dalam OB zone
          → adjust entry ke current_price, SL tetap di OB boundary - ATR
        - Jika current_price sudah di luar OB zone → raise OverlapSkipError
    """

    def run(
        self,
        signal: str,
        order_block: OrderBlock,
        df: pd.DataFrame,
        current_price: Optional[float] = None,
        atr_period: int = 14
    ) -> RiskResult:
        """
        Jalankan risk calculation.

        Args:
            signal: 'LONG' atau 'SHORT'
            order_block: OrderBlock yang relevan
            df: DataFrame untuk kalkulasi ATR
            current_price: Harga terbaru (close 15m). Jika None, pakai OB midpoint.
            atr_period: Period untuk ATR

        Returns:
            RiskResult dengan SL, TP, dan position size

        Raises:
            OverlapSkipError: Jika harga sudah di luar OB zone (trade harus di-skip)
            ValueError: Jika input tidak valid atau risk distance terlalu kecil
        """
        if signal not in ["LONG", "SHORT"]:
            raise ValueError(f"Signal harus 'LONG' atau 'SHORT', dapat: {signal}")

        if df.empty or len(df) < atr_period:
            raise ValueError(f"Data tidak cukup untuk ATR (minimal {atr_period} candle)")

        # Calculate ATR
        atr_series = calculate_atr(df, period=atr_period)
        atr = atr_series.iloc[-1]

        # OB boundaries
        ob_midpoint = (order_block.high + order_block.low) / 2
        ob_high = order_block.high
        ob_low = order_block.low

        # ── 4-State OB Entry Logic ──────────────────────────────────────
        # State 1: Belum masuk OB → limit di OB edge
        # State 2: Dalam OB, sebelum midpoint → limit di current_price
        # State 3: Lewat midpoint, masih dalam OB → market di current_price
        # State 4: Keluar OB (invalidated) → OverlapSkipError
        entry_price = ob_midpoint  # default (tidak pernah dipakai langsung)
        entry_adjusted = False

        if current_price is not None:
            if signal == "LONG":
                if current_price < ob_low:
                    # State 4: price tembus bawah OB — invalidated
                    raise OverlapSkipError(
                        f"LONG: price {current_price:.2f} di bawah OB low {ob_low:.2f} — OB invalidated"
                    )
                elif current_price >= ob_midpoint:
                    # State 1 (price > ob_high) atau State 2 (ob_midpoint <= price <= ob_high)
                    # Limit di ob_high — first touch point saat retrace
                    entry_price = ob_high
                    entry_adjusted = False
                    self._log(f"OB State 1/2 LONG: limit di ob.high {ob_high:.2f}")
                else:
                    # State 3: ob_low < price < ob_midpoint — sudah lewat midpoint, masih dalam OB
                    entry_price = current_price
                    entry_adjusted = True
                    self._log(f"OB State 3 LONG: market di current_price {current_price:.2f}")

            elif signal == "SHORT":
                if current_price > ob_high:
                    # State 4: price tembus atas OB — invalidated
                    raise OverlapSkipError(
                        f"SHORT: price {current_price:.2f} di atas OB high {ob_high:.2f} — OB invalidated"
                    )
                elif current_price <= ob_midpoint:
                    # State 1 (price < ob_low) atau State 2 (ob_low <= price <= ob_midpoint)
                    # Limit di ob_low — first touch point saat retrace naik
                    entry_price = ob_low
                    entry_adjusted = False
                    self._log(f"OB State 1/2 SHORT: limit di ob.low {ob_low:.2f}")
                else:
                    # State 3: ob_midpoint < price < ob_high — sudah lewat midpoint, masih dalam OB
                    entry_price = current_price
                    entry_adjusted = True
                    self._log(f"OB State 3 SHORT: market di current_price {current_price:.2f}")

        # Calculate SL based on signal direction
        # SL selalu dihitung dari OB boundary (bukan entry) untuk menjaga consistency
        if signal == "LONG":
            sl_price = ob_low - (atr * 1.0)
        else:  # SHORT
            sl_price = ob_high + (atr * 1.0)

        # Minimum SL buffer: pastikan SL tidak terlalu dekat dengan entry
        min_sl_distance = atr * 0.5
        if signal == "LONG" and (entry_price - sl_price) < min_sl_distance:
            sl_price = entry_price - min_sl_distance
            self._log(
                f"SL buffer diperkecil: SL dipindah ke {sl_price:.2f} (min distance {min_sl_distance:.2f})"
            )
        elif signal == "SHORT" and (sl_price - entry_price) < min_sl_distance:
            sl_price = entry_price + min_sl_distance
            self._log(
                f"SL buffer diperkecil: SL dipindah ke {sl_price:.2f} (min distance {min_sl_distance:.2f})"
            )

        # Calculate risk distance
        risk_distance = abs(entry_price - sl_price)

        # Validate risk distance
        if risk_distance == 0 or risk_distance < (atr * 0.3):
            raise ValueError(f"Risk distance terlalu kecil atau nol: {risk_distance}")

        # Calculate TP based on Risk:Reward ratio from settings
        rr_ratio = settings.RISK_REWARD_RATIO
        if signal == "LONG":
            tp_price = entry_price + (risk_distance * rr_ratio)
        else:  # SHORT
            tp_price = entry_price - (risk_distance * rr_ratio)

        # Calculate position size
        # Formula: Risk USD / risk_distance (leverage tidak mempengaruhi position size)
        leverage = settings.FUTURES_DEFAULT_LEVERAGE
        risk_usd = settings.RISK_PER_TRADE_USD
        position_size = risk_usd / risk_distance

        # Calculate margin required
        # Margin = (Position Size * Entry Price) / Leverage
        margin_required = (position_size * entry_price) / leverage

        # Calculate actual reward
        reward_usd = risk_usd * rr_ratio

        self._log(
            f"Signal: {signal} | Entry: {entry_price:.2f} | "
            f"SL: {sl_price:.2f} | TP: {tp_price:.2f} | "
            f"Risk: ${risk_usd:.2f} | Reward: ${reward_usd:.2f} | "
            f"Size: {position_size:.4f} | Leverage: {leverage}x"
            f"{' [ADJUSTED]' if entry_adjusted else ''}"
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
            margin_required=margin_required,
            entry_adjusted=entry_adjusted
        )
