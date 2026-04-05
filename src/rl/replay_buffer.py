"""
replay_buffer.py — Experience Replay Buffer untuk DQN.

Implementasi menggunakan collections.deque dengan fixed capacity.
Thread-safe untuk digunakan dalam environment parallel.
"""
from collections import deque
from typing import Tuple, NamedTuple
import numpy as np
import random


class Experience(NamedTuple):
    """
    Struktur data untuk menyimpan satu experience tuple.

    Attributes:
        state: State observation dari environment
        action: Action yang diambil
        reward: Reward yang diterima
        next_state: State berikutnya setelah action
        done: Flag episode terminated
    """
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool


class ReplayBuffer:
    """
    Experience Replay Buffer untuk DQN training.

    Menggunakan deque dengan fixed capacity (FIFO).
    Mendukung random sampling untuk batch training.

    Attributes:
        buffer: Deque yang menyimpan experiences
        capacity: Maximum capacity buffer
    """

    def __init__(self, capacity: int = 10000) -> None:
        """
        Initialize replay buffer.

        Args:
            capacity: Maximum jumlah experience yang bisa disimpan (default: 10000)
        """
        self.capacity = capacity
        self.buffer: deque[Experience] = deque(maxlen=capacity)

    def push(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool
    ) -> None:
        """
        Simpan experience ke buffer.

        Jika buffer penuh, experience tertua akan dihapus (FIFO).

        Args:
            state: State observation (numpy array)
            action: Action index (integer)
            reward: Reward scalar (float)
            next_state: Next state observation (numpy array)
            done: Episode terminated flag (boolean)
        """
        experience = Experience(state, action, reward, next_state, done)
        self.buffer.append(experience)

    def sample(self, batch_size: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Random sample batch dari buffer untuk training.

        Args:
            batch_size: Jumlah experience yang di-sample

        Returns:
            Tuple of numpy arrays:
            - states: shape (batch_size, state_dim)
            - actions: shape (batch_size,)
            - rewards: shape (batch_size,)
            - next_states: shape (batch_size, state_dim)
            - dones: shape (batch_size,)

        Raises:
            ValueError: Jika buffer tidak memiliki cukup data
        """
        if not self.is_ready(batch_size):
            raise ValueError(
                f"Buffer hanya memiliki {len(self)} experiences, "
                f"butuh minimal {batch_size} untuk sampling"
            )

        # Random sample dengan replacement
        experiences = random.sample(list(self.buffer), batch_size)

        # Convert ke numpy arrays dengan batch dimension
        states = np.array([exp.state for exp in experiences], dtype=np.float32)
        actions = np.array([exp.action for exp in experiences], dtype=np.int64)
        rewards = np.array([exp.reward for exp in experiences], dtype=np.float32)
        next_states = np.array([exp.next_state for exp in experiences], dtype=np.float32)
        dones = np.array([exp.done for exp in experiences], dtype=np.bool_)

        return states, actions, rewards, next_states, dones

    def is_ready(self, batch_size: int) -> bool:
        """
        Cek apakah buffer sudah memiliki cukup data untuk sampling.

        Args:
            batch_size: Minimum batch size yang dibutuhkan

        Returns:
            True jika buffer size >= batch_size, False sebaliknya
        """
        return len(self) >= batch_size

    def __len__(self) -> int:
        """
        Return jumlah experience yang tersimpan di buffer.

        Returns:
            Current buffer size
        """
        return len(self.buffer)

    def clear(self) -> None:
        """
        Hapus semua experience dari buffer.
        """
        self.buffer.clear()

    def get_capacity(self) -> int:
        """
        Return kapasitas maksimum buffer.

        Returns:
            Maximum capacity
        """
        return self.capacity
