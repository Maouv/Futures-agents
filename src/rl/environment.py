"""
Trading Environment untuk Reinforcement Learning.

Generic environment yang dapat digunakan untuk berbagai trading strategy.
Mengikuti OpenAI Gym interface untuk kompatibilitas dengan berbagai RL libraries.
"""

import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any
from pathlib import Path


class TradingEnvironment:
    """
    Trading environment untuk reinforcement learning.

    State vector terdiri dari semua kolom kecuali timestamp, pair, outcome, pnl, strategy_name.
    Action space binary: 0=SKIP, 1=ENTRY.
    Reward shaping berdasarkan keputusan dan outcome.
    """

    # Mapping untuk encoding kategorical features
    TREND_BIAS_MAP = {
        'BULLISH': 1,
        'BEARISH': -1,
        'RANGING': 0
    }

    BOS_TYPE_MAP = {
        'BULLISH_BOS': 1,
        'BEARISH_BOS': -1,
        'RANGING': 0,
        'NONE': 0
    }

    def __init__(self, csv_path: str, strategy_name: str = 'SMC'):
        """
        Inisialisasi trading environment.

        Args:
            csv_path: Path ke file CSV signals
            strategy_name: Identifier untuk strategy (default='SMC')
        """
        self.csv_path = Path(csv_path)
        self.strategy_name = strategy_name

        # Load dan preprocess data
        self._load_data()

        # State tracking
        self.current_step = 0
        self.max_steps = len(self.data)

        # State feature columns (exclude metadata columns)
        self.state_columns = [
            'trend_bias', 'bos_type',
            'ob_high', 'ob_low', 'ob_size', 'distance_to_ob',
            'atr', 'fvg_present', 'candle_body_ratio',
            'hour_of_day', 'consecutive_losses',
            'time_since_last_trade', 'current_drawdown_pct'
        ]

        # Normalization parameters (akan di-update per episode)
        self.state_min = None
        self.state_max = None

    def _load_data(self) -> None:
        """Load CSV data dan sort by timestamp."""
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")

        self.data = pd.read_csv(self.csv_path)

        # Sort by timestamp untuk memastikan sequential order
        self.data = self.data.sort_values('timestamp').reset_index(drop=True)

        # Encode categorical features
        self._encode_categorical()

    def _encode_categorical(self) -> None:
        """Encode categorical features ke numerik."""
        # Encode trend_bias
        self.data['trend_bias'] = self.data['trend_bias'].map(self.TREND_BIAS_MAP)

        # Encode bos_type
        self.data['bos_type'] = self.data['bos_type'].map(self.BOS_TYPE_MAP)

        # Encode fvg_present ke binary
        self.data['fvg_present'] = self.data['fvg_present'].astype(int)

        # Handle missing values jika ada
        self.data = self.data.fillna(0)

    def _normalize_state(self, state: np.ndarray) -> np.ndarray:
        """
        Normalisasi state vector ke range 0-1 menggunakan min-max normalization.

        Args:
            state: Raw state vector

        Returns:
            Normalized state vector
        """
        if self.state_min is None or self.state_max is None:
            # Hitung min-max dari episode data
            episode_data = self.data[self.state_columns]
            self.state_min = episode_data.min().values
            self.state_max = episode_data.max().values

            # Hindari division by zero
            range_vals = self.state_max - self.state_min
            range_vals[range_vals == 0] = 1.0  # Jika range = 0, set ke 1

            self.state_range = range_vals

        # Normalisasi
        normalized = (state - self.state_min) / self.state_range

        # Clip ke range [0, 1] untuk menghindari out-of-range values
        normalized = np.clip(normalized, 0, 1)

        return normalized

    def reset(self) -> np.ndarray:
        """
        Reset environment ke awal episode.

        Returns:
            Initial state vector (normalized)
        """
        self.current_step = 0

        # Reset normalization parameters untuk episode baru
        self.state_min = None
        self.state_max = None
        self.state_range = None

        # Return initial state
        return self._get_state()

    def _get_state(self) -> np.ndarray:
        """
        Extract state vector dari current step.

        Returns:
            Normalized state vector
        """
        if self.current_step >= self.max_steps:
            return np.zeros(len(self.state_columns))

        # Extract state features
        state = self.data.iloc[self.current_step][self.state_columns].values

        # Normalize
        normalized_state = self._normalize_state(state)

        return normalized_state.astype(np.float32)

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        Execute one step dalam environment.

        Args:
            action: 0=SKIP, 1=ENTRY

        Returns:
            Tuple of (next_state, reward, done, info)
        """
        if self.current_step >= self.max_steps:
            raise RuntimeError("Episode ended. Call reset() to start new episode.")

        # Get current row data
        current_row = self.data.iloc[self.current_step]
        outcome = current_row['outcome']
        pnl = current_row['pnl']

        # Calculate reward berdasarkan action dan outcome
        reward = self._calculate_reward(action, outcome, pnl)

        # Move to next step
        self.current_step += 1

        # Check if episode done
        done = self.current_step >= self.max_steps

        # Get next state
        next_state = self._get_state()

        # Info dict untuk debugging
        info = {
            'step': self.current_step,
            'action': action,
            'outcome': outcome,
            'pnl': pnl,
            'reward': reward,
            'strategy': self.strategy_name
        }

        return next_state, reward, done, info

    def _calculate_reward(self, action: int, outcome: str, pnl: float) -> float:
        """
        Calculate reward berdasarkan action dan outcome.

        Reward shaping:
        - ENTRY+TP → pnl (positif)
        - ENTRY+SL/TIMEOUT → pnl (negatif)
        - SKIP+TP → -0.5 (missed opportunity)
        - SKIP+SL/TIMEOUT → +0.3 (avoided loss)
        - SKIP+SKIPPED → 0 (neutral)

        Args:
            action: 0=SKIP, 1=ENTRY
            outcome: 'TP', 'SL', 'TIMEOUT', 'SKIPPED'
            pnl: Profit/loss value

        Returns:
            Reward value
        """
        if action == 1:  # ENTRY
            # Entry mengambil actual pnl
            return float(pnl)

        else:  # SKIP
            if outcome == 'TP':
                # Missed profit opportunity
                return -0.5
            elif outcome in ['SL', 'TIMEOUT']:
                # Avoided loss
                return 0.3
            elif outcome == 'SKIPPED':
                # Neutral, tidak ada sinyal
                return 0.0
            else:
                # Unknown outcome, default ke 0
                return 0.0

    def get_episode_stats(self) -> Dict[str, Any]:
        """
        Get statistik episode saat ini.

        Returns:
            Dictionary berisi episode statistics
        """
        if self.current_step == 0:
            return {
                'total_steps': 0,
                'strategy': self.strategy_name,
                'csv_path': str(self.csv_path)
            }

        episode_data = self.data.iloc[:self.current_step]

        return {
            'total_steps': self.current_step,
            'strategy': self.strategy_name,
            'csv_path': str(self.csv_path),
            'total_signals': len(episode_data),
            'tp_count': len(episode_data[episode_data['outcome'] == 'TP']),
            'sl_count': len(episode_data[episode_data['outcome'] == 'SL']),
            'timeout_count': len(episode_data[episode_data['outcome'] == 'TIMEOUT']),
            'skipped_count': len(episode_data[episode_data['outcome'] == 'SKIPPED']),
            'total_pnl': episode_data['pnl'].sum(),
            'mean_pnl': episode_data['pnl'].mean(),
            'win_rate': len(episode_data[episode_data['outcome'] == 'TP']) / max(len(episode_data), 1)
        }

    def render(self, mode: str = 'console') -> None:
        """
        Render current state (untuk debugging/visualization).

        Args:
            mode: Rendering mode ('console' only for now)
        """
        if mode == 'console':
            if self.current_step >= self.max_steps:
                print(f"Episode ended. Total steps: {self.current_step}")
                return

            current_row = self.data.iloc[self.current_step]
            print(f"\n=== Step {self.current_step + 1}/{self.max_steps} ===")
            print(f"Pair: {current_row['pair']}")
            print(f"Trend Bias: {current_row['trend_bias']}")
            print(f"ATR: {current_row['atr']:.2f}")
            print(f"FVG Present: {bool(current_row['fvg_present'])}")
            print(f"Outcome: {current_row['outcome']}")
            print(f"PNL: {current_row['pnl']:.4f}")
        else:
            raise NotImplementedError(f"Render mode '{mode}' not supported")

    def close(self) -> None:
        """Cleanup environment resources."""
        # Tidak ada resource khusus yang perlu di-cleanup
        pass

    @property
    def observation_space(self) -> int:
        """Return dimension of state vector."""
        return len(self.state_columns)

    @property
    def action_space(self) -> int:
        """Return number of possible actions."""
        return 2  # 0=SKIP, 1=ENTRY
