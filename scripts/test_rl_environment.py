"""
Test untuk Trading Environment.

Memverifikasi:
1. Data loading dan preprocessing
2. Categorical encoding
3. State normalization
4. Reward shaping
5. Episode flow (reset, step, done)
"""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from src.rl.environment import TradingEnvironment


class TestTradingEnvironment:
    """Test suite untuk TradingEnvironment class."""

    @pytest.fixture
    def sample_csv(self, tmp_path):
        """Create sample CSV data untuk testing."""
        data = pd.DataFrame({
            'timestamp': [
                1728565200000, 1728561600000, 1728874800000,
                1728950400000, 1729036800000
            ],
            'pair': ['BTCUSDT'] * 5,
            'trend_bias': ['BULLISH', 'BULLISH', 'BULLISH', 'BULLISH', 'BEARISH'],
            'bos_type': ['BULLISH_BOS', 'BULLISH_BOS', 'BULLISH_BOS', 'BULLISH_BOS', 'BEARISH_BOS'],
            'ob_high': [60959.90, 60959.90, 62875.10, 65843.40, 65000.00],
            'ob_low': [60600.00, 60600.00, 62420.00, 65520.00, 64500.00],
            'ob_size': [359.90, 359.90, 455.10, 323.40, 500.00],
            'distance_to_ob': [130.25, 154.05, 1634.05, 223.50, 100.00],
            'atr': [362.47, 341.81, 403.54, 457.08, 400.00],
            'fvg_present': [False, False, True, True, False],
            'candle_body_ratio': [0.0000, 0.5360, 0.9444, 0.0000, 0.5000],
            'hour_of_day': [13, 12, 3, 0, 10],
            'consecutive_losses': [0, 0, 1, 0, 2],
            'time_since_last_trade': [0, 0, 5220, 1260, 3600],
            'current_drawdown_pct': [0.00, 1.35, 1.35, 0.00, 0.50],
            'outcome': ['SKIPPED', 'SL', 'TP', 'SKIPPED', 'TIMEOUT'],
            'pnl': [0.00, -1.35, 2.70, 0.00, -0.80]
        })

        csv_path = tmp_path / "test_signals.csv"
        data.to_csv(csv_path, index=False)
        return csv_path

    def test_environment_initialization(self, sample_csv):
        """Test environment initialization."""
        env = TradingEnvironment(str(sample_csv), strategy_name='SMC')

        assert env.strategy_name == 'SMC'
        assert env.max_steps == 5
        assert env.observation_space == 13
        assert env.action_space == 2

    def test_categorical_encoding(self, sample_csv):
        """Test encoding categorical features ke numerik."""
        env = TradingEnvironment(str(sample_csv))

        # Check trend_bias encoding
        assert env.data['trend_bias'].iloc[0] == 1  # BULLISH
        assert env.data['trend_bias'].iloc[4] == -1  # BEARISH

        # Check bos_type encoding
        assert env.data['bos_type'].iloc[0] == 1  # BULLISH_BOS
        assert env.data['bos_type'].iloc[4] == -1  # BEARISH_BOS

        # Check fvg_present encoding
        assert env.data['fvg_present'].iloc[0] == 0  # False
        assert env.data['fvg_present'].iloc[2] == 1  # True

    def test_state_normalization(self, sample_csv):
        """Test state normalization ke range 0-1."""
        env = TradingEnvironment(str(sample_csv))
        state = env.reset()

        # Check shape
        assert state.shape == (13,)

        # Check normalized range
        assert np.all(state >= 0.0)
        assert np.all(state <= 1.0)

        # Check data type
        assert state.dtype == np.float32

    def test_reset(self, sample_csv):
        """Test reset functionality."""
        env = TradingEnvironment(str(sample_csv))

        state = env.reset()

        assert env.current_step == 0
        assert state is not None
        assert isinstance(state, np.ndarray)

    def test_step_skip_action(self, sample_csv):
        """Test step dengan SKIP action (0)."""
        env = TradingEnvironment(str(sample_csv))
        env.reset()

        # Setelah sorting by timestamp:
        # Step 1: timestamp 1728561600000 → SL outcome → reward = +0.3
        next_state, reward, done, info = env.step(0)  # SKIP

        assert next_state is not None
        assert reward == 0.3  # SKIP+SL = avoided loss
        assert done is False
        assert info['action'] == 0
        assert info['outcome'] == 'SL'

        # Step 2: timestamp 1728565200000 → SKIPPED outcome → reward = 0.0
        next_state, reward, done, info = env.step(0)  # SKIP

        assert reward == 0.0  # SKIP+SKIPPED = neutral

        # Step 3: timestamp 1728874800000 → TP outcome → reward = -0.5
        next_state, reward, done, info = env.step(0)  # SKIP

        assert reward == -0.5  # SKIP+TP = missed opportunity

    def test_step_entry_action(self, sample_csv):
        """Test step dengan ENTRY action (1)."""
        env = TradingEnvironment(str(sample_csv))
        env.reset()

        # Step 1: ENTRY on SL outcome → reward = pnl (-1.35)
        next_state, reward, done, info = env.step(1)  # ENTRY

        assert reward == -1.35  # ENTRY+SL = negative pnl
        assert info['pnl'] == -1.35

        # Step 2: ENTRY on SKIPPED outcome → reward = pnl (0.0)
        next_state, reward, done, info = env.step(1)  # ENTRY

        assert reward == 0.0  # ENTRY+SKIPPED = 0
        assert info['pnl'] == 0.0

        # Step 3: ENTRY on TP outcome → reward = pnl (2.70)
        next_state, reward, done, info = env.step(1)  # ENTRY

        assert reward == 2.70  # ENTRY+TP = positive pnl
        assert info['pnl'] == 2.70

    def test_episode_completion(self, sample_csv):
        """Test episode completion."""
        env = TradingEnvironment(str(sample_csv))
        env.reset()

        done = False
        steps = 0

        while not done:
            _, _, done, _ = env.step(0)  # SKIP all
            steps += 1

        assert steps == 5
        assert env.current_step == 5

        # Check stats
        stats = env.get_episode_stats()
        assert stats['total_steps'] == 5
        assert stats['strategy'] == 'SMC'

    def test_reward_shaping_all_cases(self, sample_csv):
        """Test semua reward shaping cases."""
        env = TradingEnvironment(str(sample_csv))
        env.reset()

        # Setelah sorting by timestamp, urutan: SL, SKIPPED, TP, SKIPPED, TIMEOUT

        # Case 1: SKIP + SL → +0.3 (avoided loss)
        _, reward, _, info = env.step(0)
        assert reward == 0.3
        assert info['outcome'] == 'SL'

        # Case 2: ENTRY + SKIPPED → 0.0
        _, reward, _, info = env.step(1)
        assert reward == 0.0
        assert info['outcome'] == 'SKIPPED'

        # Case 3: SKIP + TP → -0.5 (missed opportunity)
        _, reward, _, info = env.step(0)
        assert reward == -0.5
        assert info['outcome'] == 'TP'

        # Case 4: ENTRY + SKIPPED → 0.0
        _, reward, _, info = env.step(1)
        assert reward == 0.0
        assert info['outcome'] == 'SKIPPED'

        # Case 5: SKIP + TIMEOUT → +0.3
        _, reward, done, info = env.step(0)
        assert reward == 0.3
        assert info['outcome'] == 'TIMEOUT'
        assert done is True

    def test_render_console(self, sample_csv, capsys):
        """Test console rendering."""
        env = TradingEnvironment(str(sample_csv))
        env.reset()

        env.render(mode='console')
        captured = capsys.readouterr()

        assert 'Step 1/5' in captured.out
        assert 'BTCUSDT' in captured.out
        assert 'Outcome' in captured.out

    def test_episode_stats(self, sample_csv):
        """Test episode statistics."""
        env = TradingEnvironment(str(sample_csv))
        env.reset()

        # Run all steps
        for _ in range(5):
            env.step(0)

        stats = env.get_episode_stats()

        assert stats['total_steps'] == 5
        assert stats['strategy'] == 'SMC'
        assert stats['tp_count'] == 1
        assert stats['sl_count'] == 1
        assert stats['timeout_count'] == 1
        assert stats['skipped_count'] == 2
        assert stats['total_pnl'] == pytest.approx(0.55, 0.01)

    def test_sequential_timestamps(self, tmp_path):
        """Test data sorting by timestamp."""
        # Create unsorted data
        data = pd.DataFrame({
            'timestamp': [300, 100, 200],
            'pair': ['BTCUSDT'] * 3,
            'trend_bias': ['BULLISH'] * 3,
            'bos_type': ['BULLISH_BOS'] * 3,
            'ob_high': [60000.0] * 3,
            'ob_low': [59000.0] * 3,
            'ob_size': [1000.0] * 3,
            'distance_to_ob': [100.0] * 3,
            'atr': [300.0] * 3,
            'fvg_present': [True] * 3,
            'candle_body_ratio': [0.5] * 3,
            'hour_of_day': [10] * 3,
            'consecutive_losses': [0] * 3,
            'time_since_last_trade': [0] * 3,
            'current_drawdown_pct': [0.0] * 3,
            'outcome': ['TP'] * 3,
            'pnl': [1.0] * 3
        })

        csv_path = tmp_path / "unsorted.csv"
        data.to_csv(csv_path, index=False)

        env = TradingEnvironment(str(csv_path))

        # Check sorted order
        assert env.data['timestamp'].iloc[0] == 100
        assert env.data['timestamp'].iloc[1] == 200
        assert env.data['timestamp'].iloc[2] == 300

    def test_file_not_found(self):
        """Test error handling untuk file not found."""
        with pytest.raises(FileNotFoundError):
            TradingEnvironment("nonexistent.csv")

    def test_multiple_reset(self, sample_csv):
        """Test multiple reset calls."""
        env = TradingEnvironment(str(sample_csv))

        state1 = env.reset()
        env.step(0)
        env.step(0)

        state2 = env.reset()

        # Should reset to step 0
        assert env.current_step == 0

        # States should be similar (same normalization)
        np.testing.assert_array_almost_equal(state1, state2)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
