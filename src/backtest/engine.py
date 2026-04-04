"""
engine.py — Backtest engine for SMC strategy.

Loads historical CSV data, runs Math Agent pipeline, simulates trades.

FIXES v2:
- Bug #1: Position size sekarang fixed risk $10 dengan leverage, bukan % dari balance
- Bug #2: SL/TP sekarang ATR-based sesuai strategi (bukan % flat)
- Bug #3: Exit check pakai high/low candle, bukan close (mencegah look-ahead bias)
"""
import os
import csv
from typing import List, Optional
from pathlib import Path
import pandas as pd
from loguru import logger

from src.agents.math.trend_agent import TrendAgent, TrendResult
from src.agents.math.reversal_agent import ReversalAgent, ReversalResult
from src.agents.math.confirmation_agent import ConfirmationAgent, ConfirmationResult
from src.indicators.helpers import calculate_atr
from src.backtest.metrics import TradeResult, BacktestMetrics, calculate_metrics


# ── Konstanta strategi (sesuai settings.py) ─────────────────────────────────
RISK_PER_TRADE_USD = 1.0       # Fixed $10 risk per trade
LEVERAGE           = 10         # Leverage default
RISK_REWARD_RATIO  = 2.0        # RR 1:2
ATR_SL_MULTIPLIER  = 1.0        # SL = OB edge ± (ATR × 0.5)
FEE_RATE           = 0.0005     # 0.05% taker fee per side
SLIPPAGE           = 0.001      # 0.1% slippage per side
MAX_HOLD_CANDLES   = 48         # Max 48 H1 candles (2 hari)


class BacktestEngine:
    """
    Backtest engine untuk strategi SMC multi-timeframe.

    Flow:
      1. Load H4, H1 data dari CSV
      2. Iterate setiap candle H1
      3. Di setiap candle, jalankan:
         - TrendAgent(H4) → TrendResult
         - ReversalAgent(H1) → ReversalResult
      4. Jika semua signal valid → Entry dengan ATR-based SL/TP
      5. Simulate exit dengan high/low candle (bukan close)
      6. Calculate metrics
    """

    def __init__(
        self,
        h4_csv_path: str,
        h1_csv_path: str,
        m15_csv_path: Optional[str] = None,
        initial_balance: float = 10.,
        risk_per_trade: float = 0.01,
        fee_rate: float = 0.0005,
        slippage: float = 0.001,
        tp_percent: float = 0.02,
        sl_percent: float = 0.01,
        use_confirmation: bool = False,
    ):
        self.h4_csv_path  = h4_csv_path
        self.h1_csv_path  = h1_csv_path
        self.m15_csv_path = m15_csv_path
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.tp_percent = tp_percent
        self.sl_percent = sl_percent
        self.use_confirmation = use_confirmation

        self.trend_agent        = TrendAgent()
        self.reversal_agent     = ReversalAgent()
        self.confirmation_agent = ConfirmationAgent()

        self.trades: List[TradeResult] = []

    # ── Data loading ─────────────────────────────────────────────────────────

    def load_csv(self, path: str) -> pd.DataFrame:
        if not os.path.exists(path):
            logger.error(f"CSV not found: {path}")
            return pd.DataFrame()

        df = pd.read_csv(path)
        df = df.rename(columns={'open_time': 'timestamp'})
        df['timestamp'] = df['timestamp'].astype(int)

        # Pastikan kolom numerik
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        df = df.reset_index(drop=True)

        logger.info(f"Loaded {len(df)} candles from {path}")
        return df

    # ── Main backtest loop ───────────────────────────────────────────────────

    def run(self, year: Optional[int] = None, month: Optional[int] = None) -> BacktestMetrics:
        logger.info("Starting backtest...")

        df_h4  = self.load_csv(self.h4_csv_path)
        df_h1  = self.load_csv(self.h1_csv_path)

        if df_h4.empty or df_h1.empty:
            logger.error("Failed to load required data")
            return calculate_metrics([])

        # Load 15m data jika use_confirmation=True
        df_m15 = None
        if self.use_confirmation:
            if self.m15_csv_path is None:
                logger.error("use_confirmation=True but m15_csv_path not provided")
                return calculate_metrics([])

            df_m15 = self.load_csv(self.m15_csv_path)
            if df_m15.empty:
                logger.error("Failed to load 15m data")
                return calculate_metrics([])

            logger.info("Confirmation Agent ENABLED - using 15m timeframe filter")
        else:
            logger.info("Confirmation Agent DISABLED - running without 15m filter")

        # Filter by year/month
        if year:
            start_ts = int(pd.Timestamp(f"{year}-01-01").timestamp() * 1000)
            end_ts   = int(pd.Timestamp(f"{year}-12-31 23:59:59").timestamp() * 1000)
            if month:
                start_ts = int(pd.Timestamp(f"{year}-{month:02d}-01").timestamp() * 1000)
                if month == 12:
                    end_ts = int(pd.Timestamp(f"{year}-12-31 23:59:59").timestamp() * 1000)
                else:
                    end_ts = int(pd.Timestamp(f"{year}-{month+1:02d}-01").timestamp() * 1000) - 1
                logger.info(f"Filtering H1: {year}-{month:02d}")
            else:
                logger.info(f"Filtering H1: year {year}")

            df_h1 = df_h1[
                (df_h1['timestamp'] >= start_ts) & (df_h1['timestamp'] <= end_ts)
            ].reset_index(drop=True)
            logger.info(f"Filtered H1 data: {len(df_h1)} candles")

        total_candles = len(df_h1)
        position      = None
        balance       = self.initial_balance  # Starting balance (untuk tracking saja, bukan untuk position size)

        debug_counters = {
            'trend_ranging':  0,
            'reversal_none':  0,
            'trend_mismatch': 0,
            'no_ob':          0,
            'confirmation_failed': 0,
            'signals_found':  0,
        }

        logger.disable("src.agents.math")
        logger.disable("src.indicators")

        for i in range(100, total_candles):
            if i % 500 == 0:
                pct = i / total_candles * 100
                logger.info(f"Progress: {i}/{total_candles} ({pct:.1f}%) | Trades: {len(self.trades)}")

            current_time  = df_h1['timestamp'].iloc[i]
            current_close = df_h1['close'].iloc[i]
            candle_high   = df_h1['high'].iloc[i]
            candle_low    = df_h1['low'].iloc[i]

            # ── Cek exit posisi yang sedang terbuka ───────────────────────
            if position is not None:
                exit_result = self._check_exit(
                    position=position,
                    candle_high=candle_high,
                    candle_low=candle_low,
                    current_close=current_close,
                    current_time=current_time,
                    i=i,
                )
                if exit_result:
                    trade = self._close_position(
                        position=position,
                        exit_price=exit_result['price'],
                        exit_time=current_time,
                        exit_reason=exit_result['reason'],
                        exit_index=i,
                    )
                    self.trades.append(trade)
                    balance += trade.pnl
                    position = None

            # Skip kalau masih ada posisi terbuka
            if position is not None:
                continue

            # ── Map H1 ke H4 ─────────────────────────────────────────────
            h4_index = i // 4
            if h4_index < 50:
                continue

            df_h4_slice = df_h4.iloc[max(0, h4_index - 200): h4_index + 1].reset_index(drop=True)
            df_h1_slice = df_h1.iloc[max(0, i - 100): i + 1].reset_index(drop=True)

            # ── TrendAgent ────────────────────────────────────────────────
            trend_result = self.trend_agent.run(df_h4_slice)
            if trend_result.bias == 0:
                debug_counters['trend_ranging'] += 1
                continue

            # ── ReversalAgent ─────────────────────────────────────────────
            reversal_result = self.reversal_agent.run(df_h1_slice, swing_size=3)
            if reversal_result.signal == "NONE":
                debug_counters['reversal_none'] += 1
                continue

            # Trend harus align dengan signal
            expected_signal = "LONG" if trend_result.bias == 1 else "SHORT"
            if reversal_result.signal != expected_signal:
                debug_counters['trend_mismatch'] += 1
                continue

            # OB harus tersedia untuk ATR-based SL/TP
            if reversal_result.ob is None:
                debug_counters['no_ob'] += 1
                continue

            # ── ConfirmationAgent (opsional) ───────────────────────────────
            if self.use_confirmation and df_m15 is not None:
                # Map H1 index ke M15 index (1 H1 = 4 M15)
                m15_index = i * 4
                if m15_index < 50:
                    continue

                df_m15_slice = df_m15.iloc[max(0, m15_index - 200): m15_index + 1].reset_index(drop=True)
                confirmation_result = self.confirmation_agent.run(df_m15_slice, reversal_result.signal)

                if not confirmation_result.confirmed:
                    debug_counters['confirmation_failed'] += 1
                    continue

            # ── Hitung ATR dan SL/TP ──────────────────────────────────────
            atr_series = calculate_atr(df_h1_slice, period=14)
            if atr_series.empty or pd.isna(atr_series.iloc[-1]):
                continue
            atr = float(atr_series.iloc[-1])

            ob      = reversal_result.ob
            signal  = reversal_result.signal
            entry_price = (ob.high + ob.low) / 2.0  # OB midpoint

            if signal == "LONG":
                sl_price = ob.low - (atr * ATR_SL_MULTIPLIER)
                tp_price = entry_price + (abs(entry_price - sl_price) * RISK_REWARD_RATIO)
            else:  # SHORT
                sl_price = ob.high + (atr * ATR_SL_MULTIPLIER)
                tp_price = entry_price - (abs(entry_price - sl_price) * RISK_REWARD_RATIO)

            risk_distance = abs(entry_price - sl_price)
            if risk_distance < 1.0:  # Minimum $1 risk distance untuk BTC
                continue

            # ── Hitung position size (fixed risk) ─────────────────────
            # Formula: risk_usd / risk_distance (leverage tidak mempengaruhi position size)
            # Leverage hanya mempengaruhi margin requirement, bukan risk
            risk_usd = self.initial_balance * self.risk_per_trade
            position_size = risk_usd / risk_distance
            margin_required = (position_size * entry_price) / LEVERAGE

            debug_counters['signals_found'] += 1
            logger.info(
                f"Entry [{signal}] candle {i} | "
                f"Entry: {entry_price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f} | "
                f"Size: {position_size:.6f} | Margin: ${margin_required:.2f}"
            )

            position = {
                'entry_time':    current_time,
                'entry_price':   entry_price,
                'entry_index':   i,
                'side':          signal,
                'size':          position_size,
                'tp_price':      tp_price,
                'sl_price':      sl_price,
                'balance_at_entry': balance,
                # Additional metadata for CSV export
                'atr':           atr,
                'ob_high':       ob.high,
                'ob_low':        ob.low,
                'trend_bias':    trend_result.bias_label,
                'confidence':    reversal_result.confidence,
            }

        # ── Hitung metrics ────────────────────────────────────────────────
        metrics = calculate_metrics(self.trades, initial_balance=self.initial_balance)

        logger.enable("src.agents.math")
        logger.enable("src.indicators")

        logger.info("")
        logger.info("=" * 60)
        logger.info("BACKTEST COMPLETED")
        logger.info("=" * 60)
        logger.info(f"Total Trades:      {metrics.total_trades}")
        logger.info(f"Win Rate:          {metrics.win_rate:.2f}%")
        logger.info(f"Total PnL:         {metrics.total_pnl:.2f} USDT")
        logger.info(f"Profit Factor:     {metrics.profit_factor:.2f}")
        logger.info(f"Max Drawdown:      {metrics.max_drawdown:.2f}%")
        logger.info("")
        logger.info("Signal Filters:")
        logger.info(f"  - Trend RANGING:    {debug_counters['trend_ranging']:,}")
        logger.info(f"  - Reversal NONE:    {debug_counters['reversal_none']:,}")
        logger.info(f"  - Trend Mismatch:   {debug_counters['trend_mismatch']:,}")
        logger.info(f"  - No OB:            {debug_counters['no_ob']:,}")
        if self.use_confirmation:
            logger.info(f"  - Confirmation Failed: {debug_counters['confirmation_failed']:,}")
        logger.info(f"  - Signals Passed:   {debug_counters['signals_found']:,}")
        logger.info("=" * 60)

        return metrics

    # ── Exit check ───────────────────────────────────────────────────────────

    def _check_exit(
        self,
        position: dict,
        candle_high: float,
        candle_low: float,
        current_close: float,
        current_time: int,
        i: int,
    ) -> Optional[dict]:
        """
        FIX Bug #3: Cek exit menggunakan HIGH/LOW candle, bukan close price.
        Ini lebih realistis — SL/TP bisa kena di tengah candle.

        Catatan: jika dalam 1 candle baik TP maupun SL bisa kena (spike),
        kita asumsikan SL yang kena dulu (worst case, lebih konservatif).
        """
        side      = position['side']
        tp_price  = position['tp_price']
        sl_price  = position['sl_price']
        entry_idx = position['entry_index']

        candles_held = i - entry_idx

        if side == "LONG":
            # Worst case: cek SL dulu
            if candle_low <= sl_price:
                return {'price': sl_price, 'reason': 'SL'}
            if candle_high >= tp_price:
                return {'price': tp_price, 'reason': 'TP'}
        else:  # SHORT
            if candle_high >= sl_price:
                return {'price': sl_price, 'reason': 'SL'}
            if candle_low <= tp_price:
                return {'price': tp_price, 'reason': 'TP'}

        # Timeout
        if candles_held >= MAX_HOLD_CANDLES:
            return {'price': current_close, 'reason': 'TIMEOUT'}

        return None

    # ── Close position ───────────────────────────────────────────────────────

    def _close_position(
        self,
        position: dict,
        exit_price: float,
        exit_time: int,
        exit_reason: str,
        exit_index: int,
    ) -> TradeResult:
        """
        Hitung PnL dengan slippage dan fee dinamis.

        Fee formula: position_size × price × fee_rate (per side)
        """
        entry_price = position['entry_price']
        side        = position['side']
        size        = position['size']

        # Apply slippage
        if side == "LONG":
            actual_entry = entry_price * (1 + self.slippage)
            actual_exit  = exit_price  * (1 - self.slippage)
            pnl = (actual_exit - actual_entry) * size
        else:
            actual_entry = entry_price * (1 - self.slippage)
            actual_exit  = exit_price  * (1 + self.slippage)
            pnl = (actual_entry - actual_exit) * size

        # Fee dinamis: (qty × harga) × tarif — dua sisi
        fee_entry = size * actual_entry * self.fee_rate
        fee_exit  = size * actual_exit  * self.fee_rate
        total_fee = fee_entry + fee_exit

        net_pnl     = pnl - total_fee
        pnl_percent = (net_pnl / position['balance_at_entry']) * 100

        # Calculate candles held
        candles_held = exit_index - position['entry_index']

        return TradeResult(
            entry_time=position['entry_time'],
            exit_time=exit_time,
            entry_price=actual_entry,
            exit_price=actual_exit,
            side=side,
            size=size,
            pnl=net_pnl,
            pnl_percent=pnl_percent,
            fee=total_fee,
            exit_reason=exit_reason,
            sl_price=position['sl_price'],
            tp_price=position['tp_price'],
            candles_held=candles_held,
            atr=position.get('atr', 0.0),
            ob_high=position.get('ob_high', 0.0),
            ob_low=position.get('ob_low', 0.0),
            trend_bias=position.get('trend_bias', 'RANGING'),
            confidence=position.get('confidence', 0),
        )

    # ── Export to CSV ─────────────────────────────────────────────────────────

    def export_to_csv(self, output_path: str, pair: str = "BTCUSDT", year: Optional[int] = None) -> str:
        """
        Export trades to CSV file.

        Args:
            output_path: Directory path untuk menyimpan CSV
            pair: Trading pair (e.g., 'BTCUSDT')
            year: Year filter untuk filename

        Returns:
            Full path ke CSV file yang dibuat
        """
        if not self.trades:
            logger.warning("No trades to export")
            return ""

        # Create output directory jika belum ada
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        year_str = str(year) if year else "all"
        filename = f"{pair}_{year_str}_signals.csv"
        filepath = output_dir / filename

        # Define CSV columns
        fieldnames = [
            'timestamp_entry',
            'timestamp_exit',
            'pair',
            'signal',
            'entry_price',
            'sl_price',
            'tp_price',
            'outcome',
            'pnl',
            'candles_held',
            'atr',
            'ob_high',
            'ob_low',
            'trend_bias',
            'confidence'
        ]

        # Write to CSV
        try:
            with open(filepath, 'w', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for trade in self.trades:
                    writer.writerow({
                        'timestamp_entry': trade.entry_time,
                        'timestamp_exit': trade.exit_time,
                        'pair': pair,
                        'signal': trade.side,
                        'entry_price': f"{trade.entry_price:.2f}",
                        'sl_price': f"{trade.sl_price:.2f}",
                        'tp_price': f"{trade.tp_price:.2f}",
                        'outcome': trade.exit_reason,
                        'pnl': f"{trade.pnl:.2f}",
                        'candles_held': trade.candles_held,
                        'atr': f"{trade.atr:.2f}",
                        'ob_high': f"{trade.ob_high:.2f}",
                        'ob_low': f"{trade.ob_low:.2f}",
                        'trend_bias': trade.trend_bias,
                        'confidence': trade.confidence,
                    })

            logger.info(f"Exported {len(self.trades)} trades to {filepath}")
            return str(filepath)

        except Exception as e:
            logger.error(f"Failed to export CSV: {e}")
            return ""

