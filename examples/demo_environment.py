"""
Demo script untuk menggunakan TradingEnvironment.

Contoh penggunaan dasar untuk RL training.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rl.environment import TradingEnvironment
import numpy as np


def demo_basic_usage():
    """Demo penggunaan dasar TradingEnvironment."""
    print("=" * 60)
    print("TRADING ENVIRONMENT DEMO")
    print("=" * 60)

    # Initialize environment dengan CSV data
    csv_path = "data/rl_training/BTCUSDT_2024.csv"
    env = TradingEnvironment(csv_path, strategy_name='SMC')

    print(f"\n📊 Environment Info:")
    print(f"  - Strategy: {env.strategy_name}")
    print(f"  - Total Steps: {env.max_steps}")
    print(f"  - Observation Space: {env.observation_space}")
    print(f"  - Action Space: {env.action_space} (0=SKIP, 1=ENTRY)")

    # Reset environment
    print(f"\n🔄 Resetting environment...")
    state = env.reset()
    print(f"  - Initial State Shape: {state.shape}")
    print(f"  - State Range: [{state.min():.3f}, {state.max():.3f}]")

    # Run episode dengan random policy
    print(f"\n🎯 Running Episode (Random Policy):")
    print("-" * 60)

    done = False
    step = 0
    total_reward = 0.0
    actions_taken = []

    while not done:
        # Random action (0 atau 1)
        action = np.random.randint(0, 2)

        # Execute step
        next_state, reward, done, info = env.step(action)

        total_reward += reward
        actions_taken.append(action)

        # Print step info
        outcome = info['outcome']
        pnl = info['pnl']
        print(f"Step {step+1:2d} | Action: {action} ({'SKIP' if action==0 else 'ENTRY'}) | "
              f"Outcome: {outcome:8s} | Reward: {reward:+6.3f} | PnL: {pnl:+6.3f}")

        step += 1

    print("-" * 60)

    # Episode statistics
    stats = env.get_episode_stats()
    print(f"\n📈 Episode Statistics:")
    print(f"  - Total Steps: {stats['total_steps']}")
    print(f"  - Total Reward: {total_reward:.3f}")
    print(f"  - Win Rate: {stats['win_rate']:.2%}")
    print(f"  - Total PnL: {stats['total_pnl']:.3f}")
    print(f"  - TP Count: {stats['tp_count']}")
    print(f"  - SL Count: {stats['sl_count']}")
    print(f"  - Timeout Count: {stats['timeout_count']}")
    print(f"  - Skipped Count: {stats['skipped_count']}")

    # Action distribution
    skip_count = actions_taken.count(0)
    entry_count = actions_taken.count(1)
    print(f"\n🎯 Action Distribution:")
    print(f"  - SKIP: {skip_count} ({skip_count/len(actions_taken):.1%})")
    print(f"  - ENTRY: {entry_count} ({entry_count/len(actions_taken):.1%})")


def demo_custom_policy():
    """Demo dengan simple threshold-based policy."""
    print("\n" + "=" * 60)
    print("CUSTOM POLICY DEMO (RSI Threshold)")
    print("=" * 60)

    csv_path = "data/rl_training/BTCUSDT_2024.csv"
    env = TradingEnvironment(csv_path, strategy_name='SMC')

    # Reset
    state = env.reset()
    done = False
    step = 0
    total_reward = 0.0

    print("\nPolicy: ENTRY jika RSI < 40, SKIP jika RSI >= 40")
    print("-" * 60)

    while not done:
        # Get current row untuk check RSI
        current_row = env.data.iloc[env.current_step]
        rsi_value = current_row['rsi']

        # Simple policy: ENTRY jika RSI oversold
        action = 1 if rsi_value < 40 else 0

        # Execute
        next_state, reward, done, info = env.step(action)
        total_reward += reward

        outcome = info['outcome']
        print(f"Step {step+1:2d} | RSI: {rsi_value:5.2f} | Action: {action} | "
              f"Outcome: {outcome:8s} | Reward: {reward:+6.3f}")

        step += 1

    print("-" * 60)
    print(f"\n📈 Total Reward: {total_reward:.3f}")

    stats = env.get_episode_stats()
    print(f"  - Win Rate: {stats['win_rate']:.2%}")
    print(f"  - Total PnL: {stats['total_pnl']:.3f}")


if __name__ == '__main__':
    try:
        demo_basic_usage()
        demo_custom_policy()
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
        print("Pastikan file CSV training data tersedia di data/rl_training/")
