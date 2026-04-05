"""
DQN Training Loop untuk Google Colab.

Module ini menjalankan training loop lengkap untuk DQN agent
menggunakan data dari multiple CSV files (semua pairs dan tahun).

Training dijalankan di Google Colab (GPU T4 gratis), bukan di VPS.
Setelah training selesai, model terbaik di-export ke ONNX format.
"""

# ==========================================
# HYPERPARAMETERS
# ==========================================
BATCH_SIZE = 32                 # Batch size untuk training
EPISODES = 500                  # Maximum episodes (atau sampai early stopping)
REPLAY_BUFFER_SIZE = 10000      # Maximum experiences di replay buffer
MIN_BUFFER_SIZE = 100           # Minimum experiences sebelum mulai training
TARGET_UPDATE_FREQ = 10         # Update target network setiap N episodes
LEARNING_RATE = 0.001           # Learning rate untuk Adam optimizer
GAMMA = 0.95                    # Discount factor
SAVE_EVERY = 50                 # Save checkpoint setiap N episodes

# ==========================================

import os
import glob
import random
from pathlib import Path
from typing import List, Dict, Tuple
import numpy as np
import torch
import matplotlib.pyplot as plt
from loguru import logger

from src.rl.environment import TradingEnvironment
from src.rl.dqn_agent import DQNAgent
from src.rl.replay_buffer import ReplayBuffer


class DQNTrainer:
    """
    DQN Training orchestrator untuk multiple CSV datasets.

    Attributes:
        csv_dir: Directory berisi CSV training files
        output_dir: Directory untuk save models dan plots
        agent: DQN Agent instance
        replay_buffer: Experience replay buffer
        best_reward: Best total reward yang pernah dicapai
        episode_rewards: History of rewards per episode
        episode_win_rates: History of win rates per episode
        episode_pnls: History of PnL per episode
    """

    def __init__(
        self,
        csv_dir: str = "data/rl_training",
        output_dir: str = "data/rl_models",
        state_size: int = 14,
        action_size: int = 2,
        device: str = None
    ) -> None:
        """
        Initialize DQN Trainer.

        Args:
            csv_dir: Directory berisi CSV training files
            output_dir: Directory untuk save models
            state_size: Dimensi state observation
            action_size: Jumlah actions
            device: Device untuk training ('cuda' atau 'cpu')
        """
        self.csv_dir = Path(csv_dir)
        self.output_dir = Path(output_dir)

        # Create output directory jika belum ada
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set device
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        logger.info(f"Training device: {self.device}")

        # Initialize agent dan replay buffer
        self.agent = DQNAgent(
            state_size=state_size,
            action_size=action_size,
            lr=LEARNING_RATE,
            gamma=GAMMA,
            buffer_capacity=REPLAY_BUFFER_SIZE,
            target_update_freq=TARGET_UPDATE_FREQ,
            device=self.device
        )

        self.replay_buffer = ReplayBuffer(capacity=REPLAY_BUFFER_SIZE)

        # Training metrics tracking
        self.best_reward = float('-inf')
        self.episode_rewards: List[float] = []
        self.episode_win_rates: List[float] = []
        self.episode_pnls: List[float] = []

        # Find all CSV files
        self.csv_files = self._find_csv_files()

        if not self.csv_files:
            raise FileNotFoundError(
                f"Tidak ada CSV files di {csv_dir}. "
                "Pastikan sudah ada data untuk training."
            )

        logger.info(f"Ditemukan {len(self.csv_files)} CSV files untuk training")

    def _find_csv_files(self) -> List[Path]:
        """
        Find semua CSV files di csv_dir.

        Returns:
            List of Path objects ke CSV files
        """
        csv_pattern = str(self.csv_dir / "*.csv")
        csv_files = [Path(f) for f in glob.glob(csv_pattern)]
        return sorted(csv_files)

    def train(self) -> Dict[str, float]:
        """
        Run training loop untuk semua episodes.

        Returns:
            Dictionary berisi final metrics
        """
        logger.info("Starting DQN Training...")
        logger.info(f"Total episodes: {EPISODES}")
        logger.info(f"CSV files available: {len(self.csv_files)}")

        for episode in range(1, EPISODES + 1):
            # Select CSV file (cycling through all files)
            csv_file = self.csv_files[(episode - 1) % len(self.csv_files)]

            logger.info(f"\n{'='*60}")
            logger.info(f"Episode {episode}/{EPISODES} - File: {csv_file.name}")
            logger.info(f"{'='*60}")

            # Run one episode
            episode_reward, episode_pnl, win_rate = self._run_episode(csv_file)

            # Track metrics
            self.episode_rewards.append(episode_reward)
            self.episode_pnls.append(episode_pnl)
            self.episode_win_rates.append(win_rate)

            logger.info(
                f"Episode {episode} Results | "
                f"Reward: {episode_reward:.4f} | "
                f"PnL: {episode_pnl:.2f} | "
                f"Win Rate: {win_rate:.2%}"
            )

            # Save best model
            if episode_reward > self.best_reward:
                self.best_reward = episode_reward
                self._save_best_model()
                logger.success(f"✅ New best model saved! Reward: {self.best_reward:.4f}")

            # Save checkpoint
            if episode % SAVE_EVERY == 0:
                self._save_checkpoint(episode)

        # Training complete
        logger.success("\n" + "="*60)
        logger.success("TRAINING COMPLETE!")
        logger.success("="*60)

        # Export best model to ONNX
        onnx_path = self.output_dir / "best_model.onnx"
        self.agent.load_model(str(self.output_dir / "best_model.pth"))
        self.agent.export_to_onnx(str(onnx_path))
        logger.success(f"Best model exported to ONNX: {onnx_path}")

        # Plot training curve
        self._plot_training_curve()

        # Return final metrics
        final_metrics = {
            'best_reward': self.best_reward,
            'avg_reward': np.mean(self.episode_rewards[-100:]),
            'avg_pnl': np.mean(self.episode_pnls[-100:]),
            'avg_win_rate': np.mean(self.episode_win_rates[-100:])
        }

        logger.info(f"Final Metrics: {final_metrics}")

        return final_metrics

    def _run_episode(self, csv_file: Path) -> Tuple[float, float, float]:
        """
        Run satu episode (satu CSV file) dari start to finish.

        Args:
            csv_file: Path ke CSV file untuk episode ini

        Returns:
            Tuple of (total_reward, total_pnl, win_rate)
        """
        # Initialize environment
        env = TradingEnvironment(csv_path=str(csv_file))

        # Reset environment
        state = env.reset()
        done = False

        # Episode tracking
        total_reward = 0.0
        total_pnl = 0.0
        wins = 0
        total_trades = 0

        # Episode loop
        while not done:
            # Select action using Thompson Sampling
            action = self.agent.select_action(state)

            # Take step in environment
            next_state, reward, done, info = env.step(action)

            # Push experience ke replay buffer
            self.replay_buffer.push(state, action, reward, next_state, done)

            # Update Thompson Sampling parameters
            self.agent.update_thompson(action, reward)

            # Learn jika buffer sudah ready
            if self.replay_buffer.is_ready(MIN_BUFFER_SIZE):
                loss = self.agent.learn(batch_size=BATCH_SIZE)
                if loss is not None and total_trades % 100 == 0:
                    logger.debug(f"Loss: {loss:.6f}")

            # Track metrics
            total_reward += reward

            if action == 1:  # ENTRY action
                total_trades += 1
                if reward > 0:
                    wins += 1
                if 'pnl' in info:
                    total_pnl += info['pnl']

            # Move to next state
            state = next_state

        # Calculate win rate
        win_rate = wins / total_trades if total_trades > 0 else 0.0

        # Get episode statistics dari environment
        episode_stats = env.get_episode_stats()
        logger.debug(f"Episode stats: {episode_stats}")

        return total_reward, total_pnl, win_rate

    def _save_best_model(self) -> None:
        """Save best model ke best_model.pth."""
        best_model_path = self.output_dir / "best_model.pth"
        self.agent.save_model(str(best_model_path))

        # Save normalization parameters
        norm_path = self.output_dir / "normalization_params.npz"
        np.savez(
            str(norm_path),
            state_mean=np.zeros(14, dtype=np.float32),  # Placeholder
            state_std=np.ones(14, dtype=np.float32)     # Placeholder
        )

    def _save_checkpoint(self, episode: int) -> None:
        """
        Save checkpoint model.

        Args:
            episode: Current episode number
        """
        checkpoint_path = self.output_dir / f"checkpoint_episode_{episode}.pth"
        self.agent.save_model(str(checkpoint_path))
        logger.info(f"Checkpoint saved: {checkpoint_path}")

    def _plot_training_curve(self) -> None:
        """Plot dan save training curve (reward per episode)."""
        plt.figure(figsize=(12, 6))

        # Plot rewards
        plt.subplot(1, 2, 1)
        plt.plot(self.episode_rewards, label='Total Reward')
        plt.xlabel('Episode')
        plt.ylabel('Reward')
        plt.title('Training Curve - Reward per Episode')
        plt.grid(True, alpha=0.3)

        # Moving average
        if len(self.episode_rewards) >= 10:
            moving_avg = np.convolve(
                self.episode_rewards,
                np.ones(10)/10,
                mode='valid'
            )
            plt.plot(moving_avg, label='Moving Average (10)', linewidth=2)
            plt.legend()

        # Plot win rates
        plt.subplot(1, 2, 2)
        plt.plot(self.episode_win_rates, label='Win Rate', color='green')
        plt.xlabel('Episode')
        plt.ylabel('Win Rate')
        plt.title('Win Rate per Episode')
        plt.grid(True, alpha=0.3)
        plt.legend()

        plt.tight_layout()

        # Save plot
        plot_path = self.output_dir / "training_curve.png"
        plt.savefig(str(plot_path), dpi=150)
        logger.success(f"Training curve saved: {plot_path}")

        plt.close()


def main():
    """
    Main function untuk menjalankan training.

    Usage di Google Colab:
        from src.rl.trainer import main
        main()
    """
    # Set random seeds untuk reproducibility
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)

    # Initialize trainer
    trainer = DQNTrainer(
        csv_dir="data/rl_training",
        output_dir="data/rl_models",
        state_size=14,
        action_size=2
    )

    # Run training
    final_metrics = trainer.train()

    logger.success(f"Training complete! Final metrics: {final_metrics}")


if __name__ == "__main__":
    main()
