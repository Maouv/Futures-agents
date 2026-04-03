"""
engine.py — Backtest engine for SMC strategy.

Loads historical CSV data, runs Math Agent pipeline, simulates trades.
"""
import os
from typing import List, Optional
import pandas as pd
from loguru import logger

from src.agents.math.trend_agent import TrendAgent, TrendResult
from src.agents.math.reversal_agent import ReversalAgent, ReversalResult
from src.agents.math.confirmation_agent import ConfirmationAgent, ConfirmationResult
from src.backtest.metrics import TradeResult, BacktestMetrics, calculate_metrics


class BacktestEngine:
    """
    Backtest engine untuk strategi SMC multi-timeframe.

    Flow:
      1. Load H4, H1 data dari CSV
      2. Iterate setiap candle H1
      3. Di setiap candle, jalankan:
         - TrendAgent(H4) → TrendResult
         - ReversalAgent(H1) → ReversalResult
         - ConfirmationAgent(15m) → ConfirmationResult (skip jika tidak ada 15m)
      4. Jika semua signal valid → Entry
      5. Simulate exit (TP/SL/Timeout)
      6. Calculate metrics
    """

    def __init__(
        self,
        h4_csv_path: str,
        h1_csv_path: str,
        m15_csv_path: Optional[str] = None,
        initial_balance: float = 10000.0,
        risk_per_trade: float = 0.01,      # 1% per trade
        fee_rate: float = 0.0005,           # 0.05% taker fee
        slippage: float = 0.001,            # 0.1% slippage
        tp_percent: float = 0.02,           # 2% TP
        sl_percent: float = 0.01,           # 1% SL
        max_hold_candles: int = 24,         # Max 24 H1 candles (24 hours)
    ):
        """
        Initialize backtest engine.

        Args:
            h4_csv_path: Path ke CSV H4
            h1_csv_path: Path ke CSV H1
            m15_csv_path: Path ke CSV 15m (optional)
            initial_balance: Starting balance in USDT
            risk_per_trade: Risk percentage per trade (0.01 = 1%)
            fee_rate: Trading fee per side (0.0005 = 0.05%)
            slippage: Slippage percentage (0.001 = 0.1%)
            tp_percent: Take profit percentage from entry
            sl_percent: Stop loss percentage from entry
            max_hold_candles: Maximum candles to hold position
        """
        self.h4_csv_path = h4_csv_path
        self.h1_csv_path = h1_csv_path
        self.m15_csv_path = m15_csv_path
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.tp_percent = tp_percent
        self.sl_percent = sl_percent
        self.max_hold_candles = max_hold_candles

        # Agents
        self.trend_agent = TrendAgent()
        self.reversal_agent = ReversalAgent()
        self.confirmation_agent = ConfirmationAgent()

        # Results
        self.trades: List[TradeResult] = []

    def load_csv(self, path: str) -> pd.DataFrame:
        """
        Load CSV dengan format Binance OHLCV.

        Args:
            path: Path ke CSV file

        Returns:
            DataFrame dengan columns: open_time, open, high, low, close, volume
        """
        if not os.path.exists(path):
            logger.error(f"CSV not found: {path}")
            return pd.DataFrame()

        df = pd.read_csv(path)

        # Standardize columns
        df = df.rename(columns={
            'open_time': 'timestamp',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume'
        })

        # Ensure timestamp is int
        df['timestamp'] = df['timestamp'].astype(int)

        logger.info(f"Loaded {len(df)} candles from {path}")
        return df

    def run(self, year: Optional[int] = None) -> BacktestMetrics:
        """
        Run backtest.

        Args:
            year: Filter by year (optional)

        Returns:
            BacktestMetrics hasil backtest
        """
        logger.info("Starting backtest...")

        # Load data
        df_h4 = self.load_csv(self.h4_csv_path)
        df_h1 = self.load_csv(self.h1_csv_path)
        df_m15 = self.load_csv(self.m15_csv_path) if self.m15_csv_path else None

        if df_h4.empty or df_h1.empty:
            logger.error("Failed to load required data")
            return calculate_metrics([])

        # Filter by year if specified
        if year:
            start_ts = int(pd.Timestamp(f"{year}-01-01").timestamp() * 1000)
            end_ts = int(pd.Timestamp(f"{year}-12-31 23:59:59").timestamp() * 1000)

            df_h1 = df_h1[(df_h1['timestamp'] >= start_ts) & (df_h1['timestamp'] <= end_ts)]
            logger.info(f"Filtered H1 data: {len(df_h1)} candles for year {year}")

        # Iterate setiap candle H1
        balance = self.initial_balance
        position = None  # Track open position
        total_candles = len(df_h1)

        # Debug counters
        debug_counters = {
            'trend_ranging': 0,
            'reversal_none': 0,
            'trend_mismatch': 0,
            'not_confirmed': 0,
            'signals_found': 0
        }

        for i in range(100, total_candles):  # Start from 100 to have enough history
            # Progress logging setiap 100 candle
            if i % 100 == 0:
                logger.info(f"Progress: {i}/{total_candles} candles ({i/total_candles*100:.1f}%)")

            current_time = df_h1['timestamp'].iloc[i]
            current_price = df_h1['close'].iloc[i]

            # Check exit if in position
            if position:
                exit_result = self._check_exit(
                    position=position,
                    current_price=current_price,
                    current_time=current_time,
                    i=i
                )

                if exit_result:
                    # Close position
                    trade = self._close_position(
                        position=position,
                        exit_price=exit_result['price'],
                        exit_time=current_time,
                        exit_reason=exit_result['reason']
                    )
                    self.trades.append(trade)
                    balance += trade.pnl
                    position = None

            # Skip jika masih dalam position
            if position:
                continue

            # Get H4 data (last 50 candles)
            # Map H1 to H4: 4 H1 candles = 1 H4 candle
            h1_to_h4_ratio = 4
            h4_index = i // h1_to_h4_ratio

            if h4_index < 20:
                continue

            df_h4_slice = df_h4.iloc[max(0, h4_index - 50):h4_index + 1].copy()

            # Debug: log slice info setiap 1000 candle
            if i % 1000 == 0:
                logger.debug(f"Candle {i}: h4_index={h4_index}, H4 slice length={len(df_h4_slice)}")

            # Get H1 data (last 50 candles)
            df_h1_slice = df_h1.iloc[max(0, i - 50):i + 1].copy()

            # Run TrendAgent on H4
            trend_result = self.trend_agent.run(df_h4_slice)

            # Skip jika ranging
            if trend_result.bias == 0:
                debug_counters['trend_ranging'] += 1
                continue

            # Run ReversalAgent on H1
            reversal_result = self.reversal_agent.run(df_h1_slice)

            # Skip jika tidak ada signal
            if reversal_result.signal == "NONE":
                debug_counters['reversal_none'] += 1
                continue

            # Check trend alignment
            if trend_result.bias == 1 and reversal_result.signal != "LONG":
                debug_counters['trend_mismatch'] += 1
                continue
            if trend_result.bias == -1 and reversal_result.signal != "SHORT":
                debug_counters['trend_mismatch'] += 1
                continue

            # Run ConfirmationAgent jika ada 15m data
            confirmed = True
            if df_m15 is not None:
                # Map H1 to 15m: 1 H1 candle = 4 15m candles
                # Find 15m candles for this H1 candle
                h1_start_ts = df_h1['timestamp'].iloc[i]
                h1_end_ts = h1_start_ts + 3600000  # +1 hour in ms

                m15_slice = df_m15[
                    (df_m15['timestamp'] >= h1_start_ts - 7200000) &  # Last 2 hours
                    (df_m15['timestamp'] < h1_end_ts)
                ].copy()

                if len(m15_slice) >= 50:
                    confirmation_result = self.confirmation_agent.run(
                        df_15m=m15_slice,
                        h1_signal=reversal_result.signal
                    )
                    confirmed = confirmation_result.confirmed

            if not confirmed:
                debug_counters['not_confirmed'] += 1
                continue

            debug_counters['signals_found'] += 1

            # Entry signal confirmed!
            logger.info(f"Entry signal at candle {i}: {reversal_result.signal}")

            # Calculate position size
            entry_price = reversal_result.entry_price or current_price
            position_size = self._calculate_position_size(
                balance=balance,
                entry_price=entry_price,
                sl_percent=self.sl_percent
            )

            # Calculate TP/SL
            if reversal_result.signal == "LONG":
                tp_price = entry_price * (1 + self.tp_percent)
                sl_price = entry_price * (1 - self.sl_percent)
            else:  # SHORT
                tp_price = entry_price * (1 - self.tp_percent)
                sl_price = entry_price * (1 + self.sl_percent)

            # Open position
            position = {
                'entry_time': current_time,
                'entry_price': entry_price,
                'entry_index': i,
                'side': reversal_result.signal,
                'size': position_size,
                'tp_price': tp_price,
                'sl_price': sl_price,
                'balance_at_entry': balance
            }

        # Calculate metrics
        metrics = calculate_metrics(self.trades)

        # Print debug counters
        logger.info("=" * 60)
        logger.info("DEBUG: Signal Flow Analysis")
        logger.info("=" * 60)
        logger.info(f"Trend ranging (skipped):     {debug_counters['trend_ranging']}")
        logger.info(f"Reversal NONE (skipped):     {debug_counters['reversal_none']}")
        logger.info(f"Trend mismatch (skipped):    {debug_counters['trend_mismatch']}")
        logger.info(f"Not confirmed (skipped):     {debug_counters['not_confirmed']}")
        logger.info(f"Signals found (passed):      {debug_counters['signals_found']}")
        logger.info("=" * 60)

        logger.info(f"Backtest completed: {metrics.total_trades} trades")
        logger.info(f"Win Rate: {metrics.win_rate:.2f}%")
        logger.info(f"Total PnL: {metrics.total_pnl:.2f} USDT")
        logger.info(f"Profit Factor: {metrics.profit_factor:.2f}")
        logger.info(f"Max Drawdown: {metrics.max_drawdown:.2f}%")

        return metrics

    def _calculate_position_size(
        self,
        balance: float,
        entry_price: float,
        sl_percent: float
    ) -> float:
        """
        Calculate position size based on risk.

        Args:
            balance: Current balance
            entry_price: Entry price
            sl_percent: Stop loss percentage

        Returns:
            Position size in BTC
        """
        risk_amount = balance * self.risk_per_trade
        sl_distance = entry_price * sl_percent

        # Position size = Risk Amount / SL Distance
        position_size = risk_amount / sl_distance if sl_distance > 0 else 0.0

        return position_size

    def _check_exit(
        self,
        position: dict,
        current_price: float,
        current_time: int,
        i: int
    ) -> Optional[dict]:
        """
        Check if position should exit.

        Args:
            position: Open position dict
            current_price: Current price
            current_time: Current timestamp
            i: Current candle index

        Returns:
            Exit dict with 'price' and 'reason' or None
        """
        side = position['side']
        tp_price = position['tp_price']
        sl_price = position['sl_price']
        entry_index = position['entry_index']

        # Check TP
        if side == "LONG" and current_price >= tp_price:
            return {'price': tp_price, 'reason': 'TP'}
        if side == "SHORT" and current_price <= tp_price:
            return {'price': tp_price, 'reason': 'TP'}

        # Check SL
        if side == "LONG" and current_price <= sl_price:
            return {'price': sl_price, 'reason': 'SL'}
        if side == "SHORT" and current_price >= sl_price:
            return {'price': sl_price, 'reason': 'SL'}

        # Check timeout
        candles_held = i - entry_index
        if candles_held >= self.max_hold_candles:
            return {'price': current_price, 'reason': 'TIMEOUT'}

        return None

    def _close_position(
        self,
        position: dict,
        exit_price: float,
        exit_time: int,
        exit_reason: str
    ) -> TradeResult:
        """
        Close position dan calculate PnL.

        Args:
            position: Open position dict
            exit_price: Exit price
            exit_time: Exit timestamp
            exit_reason: Exit reason ('TP', 'SL', 'TIMEOUT')

        Returns:
            TradeResult
        """
        entry_price = position['entry_price']
        entry_time = position['entry_time']
        side = position['side']
        size = position['size']

        # Apply slippage
        if side == "LONG":
            actual_entry = entry_price * (1 + self.slippage)
            actual_exit = exit_price * (1 - self.slippage)
        else:  # SHORT
            actual_entry = entry_price * (1 - self.slippage)
            actual_exit = exit_price * (1 + self.slippage)

        # Calculate PnL
        if side == "LONG":
            pnl = (actual_exit - actual_entry) * size
        else:  # SHORT
            pnl = (actual_entry - actual_exit) * size

        # Calculate fee
        fee = (size * actual_entry * self.fee_rate) + (size * actual_exit * self.fee_rate)
        pnl -= fee

        # Calculate PnL percentage
        pnl_percent = (pnl / position['balance_at_entry']) * 100

        return TradeResult(
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=actual_entry,
            exit_price=actual_exit,
            side=side,
            size=size,
            pnl=pnl,
            pnl_percent=pnl_percent,
            fee=fee,
            exit_reason=exit_reason
        )
