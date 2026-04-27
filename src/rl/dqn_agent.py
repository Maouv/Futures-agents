"""
DQN Agent dengan Thompson Sampling untuk Exploration.

Module ini dijalankan di Google Colab (bukan VPS production).
Training menggunakan GPU T4 gratis di Colab.

Setelah training selesai, export model ke ONNX format untuk
inference di VPS tanpa perlu install PyTorch.
"""

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from typing import Optional

from src.rl.replay_buffer import ReplayBuffer


class QNetwork(nn.Module):
    """
    Deep Q-Network dengan architecture [input, 128, 64, output].

    Input: 13 features (state_size)
    Hidden layers: 128 -> 64 neurons
    Output: 2 Q-values (action_size: SKIP=0, ENTRY=1)
    Activation: ReLU
    """

    def __init__(self, state_size: int = 13, action_size: int = 2) -> None:
        """
        Initialize Q-Network.

        Args:
            state_size: Dimensi state observation (default: 13)
            action_size: Jumlah actions (default: 2)
        """
        super(QNetwork, self).__init__()

        self.fc1 = nn.Linear(state_size, 128)
        self.fc2 = nn.Linear(128, 64)
        self.fc3 = nn.Linear(64, action_size)
        self.relu = nn.ReLU()

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """
        Forward pass melalui network.

        Args:
            state: Input tensor shape (batch_size, state_size)

        Returns:
            Q-values tensor shape (batch_size, action_size)
        """
        x = self.relu(self.fc1(state))
        x = self.relu(self.fc2(x))
        q_values = self.fc3(x)
        return q_values


class DQNAgent:
    """
    DQN Agent dengan Thompson Sampling untuk exploration.

    Thompson Sampling menggunakan Beta distribution per action untuk
    adaptive exploration (lebih sophisticated daripada epsilon-greedy).

    Attributes:
        q_network: Main Q-Network untuk training
        target_network: Target network untuk stability
        optimizer: Adam optimizer
        replay_buffer: Experience replay buffer
        beta_params: Beta distribution parameters (alpha, beta) per action
    """

    def __init__(
        self,
        state_size: int = 13,
        action_size: int = 2,
        lr: float = 0.001,
        gamma: float = 0.95,
        buffer_capacity: int = 10000,
        target_update_freq: int = 10,
        device: Optional[str] = None
    ) -> None:
        """
        Initialize DQN Agent.

        Args:
            state_size: Dimensi state (default: 13)
            action_size: Jumlah actions (default: 2)
            lr: Learning rate (default: 0.001)
            gamma: Discount factor (default: 0.95)
            buffer_capacity: Replay buffer capacity (default: 10000)
            target_update_freq: Frekuensi update target network (default: 10)
            device: Device untuk training ('cuda', 'cpu', atau None untuk auto-detect)
        """
        # Set device
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        # Hyperparameters
        self.state_size = state_size
        self.action_size = action_size
        self.lr = lr
        self.gamma = gamma
        self.target_update_freq = target_update_freq

        # Networks
        self.q_network = QNetwork(state_size, action_size).to(self.device)
        self.target_network = QNetwork(state_size, action_size).to(self.device)

        # Initialize target network dengan weights yang sama
        self.target_network.load_state_dict(self.q_network.state_dict())
        self.target_network.eval()  # Target network selalu dalam eval mode

        # Optimizer
        self.optimizer = optim.Adam(self.q_network.parameters(), lr=lr)

        # Replay Buffer
        self.replay_buffer = ReplayBuffer(capacity=buffer_capacity)

        # Thompson Sampling: Beta distribution parameters per action
        # Initialize dengan uniform prior (alpha=1, beta=1)
        self.beta_alpha = np.ones(action_size, dtype=np.float32)
        self.beta_beta = np.ones(action_size, dtype=np.float32)

        # Training counter untuk target network update
        self.training_step = 0

    def select_action(self, state: np.ndarray) -> int:
        """
        Select action menggunakan Thompson Sampling.

        Proses:
        1. Sample dari Beta(alpha[a], beta[a]) untuk setiap action
        2. Pilih action dengan sample value tertinggi
        3. Gunakan Q-Network untuk greedy selection jika diperlukan

        Args:
            state: State observation shape (state_size,)

        Returns:
            Selected action (0 atau 1)
        """
        # Thompson Sampling: sample dari Beta distribution per action
        samples = np.array([
            np.random.beta(self.beta_alpha[a], self.beta_beta[a])
            for a in range(self.action_size)
        ])

        # Pilih action dengan sample tertinggi
        thompson_action = np.argmax(samples)

        # Jika Thompson Sampling memilih action ENTRY (1),
        # gunakan Q-Network untuk konfirmasi (greedy dengan exploration)
        if thompson_action == 1:
            # Convert state ke tensor
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)

            # Get Q-values dari network
            with torch.no_grad():
                q_values = self.q_network(state_tensor)

            # Greedy selection berdasarkan Q-values
            q_action = q_values.argmax(dim=1).item()

            return q_action

        return thompson_action

    def update_thompson(self, action: int, reward: float) -> None:
        """
        Update Beta distribution parameters berdasarkan outcome.

        Thompson Sampling update rule:
        - Jika reward positif: alpha[action] += 1 (success)
        - Jika reward negatif atau zero: beta[action] += 1 (failure)

        Args:
            action: Action yang diambil (0 atau 1)
            reward: Reward yang diterima (bisa positif/negatif)
        """
        if reward > 0:
            self.beta_alpha[action] += 1.0
        else:
            self.beta_beta[action] += 1.0

    def learn(self, batch_size: int = 64) -> Optional[float]:
        """
        Train Q-Network menggunakan batch dari replay buffer.

        Proses:
        1. Sample batch dari replay buffer
        2. Compute current Q-values
        3. Compute target Q-values menggunakan target network
        4. Compute loss (MSE)
        5. Backpropagation
        6. Update target network jika counter mencapai threshold

        Args:
            batch_size: Jumlah samples untuk training batch

        Returns:
            Loss value jika berhasil, None jika buffer belum siap
        """
        # Cek apakah buffer sudah siap
        if not self.replay_buffer.is_ready(batch_size):
            return None

        # Sample batch
        states, actions, rewards, next_states, dones = self.replay_buffer.sample(batch_size)

        # Convert ke tensor dan pindah ke device
        states = torch.FloatTensor(states).to(self.device)
        actions = torch.LongTensor(actions).to(self.device)
        rewards = torch.FloatTensor(rewards).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)
        dones = torch.FloatTensor(dones).to(self.device)

        # Compute current Q-values untuk actions yang diambil
        current_q_values = self.q_network(states).gather(1, actions.unsqueeze(1))
        current_q_values = current_q_values.squeeze(1)

        # Compute target Q-values menggunakan target network
        with torch.no_grad():
            # DQN: max Q-value untuk next state
            next_q_values = self.target_network(next_states).max(dim=1)[0]

            # Target = reward + gamma * max(Q(next_state)) * (1 - done)
            target_q_values = rewards + (self.gamma * next_q_values * (1 - dones))

        # Compute loss (MSE)
        loss = nn.MSELoss()(current_q_values, target_q_values)

        # Backpropagation
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        # Increment training step
        self.training_step += 1

        # Update target network jika mencapai threshold
        if self.training_step % self.target_update_freq == 0:
            self.update_target_network()

        return loss.item()

    def update_target_network(self) -> None:
        """
        Copy weights dari Q-Network ke Target Network.

        Dipanggil setiap target_update_freq steps untuk stabilisasi training.
        """
        self.target_network.load_state_dict(self.q_network.state_dict())

    def save_model(self, filepath: str) -> None:
        """
        Save model weights ke file.

        Args:
            filepath: Path untuk save model (.pt atau .pth)
        """
        torch.save({
            'q_network_state_dict': self.q_network.state_dict(),
            'target_network_state_dict': self.target_network.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'beta_alpha': self.beta_alpha,
            'beta_beta': self.beta_beta,
            'training_step': self.training_step,
            'hyperparameters': {
                'state_size': self.state_size,
                'action_size': self.action_size,
                'lr': self.lr,
                'gamma': self.gamma,
                'target_update_freq': self.target_update_freq
            }
        }, filepath)

    def load_model(self, filepath: str) -> None:
        """
        Load model weights dari file.

        Args:
            filepath: Path ke model file (.pt atau .pth)
        """
        checkpoint = torch.load(filepath, map_location=self.device)

        self.q_network.load_state_dict(checkpoint['q_network_state_dict'])
        self.target_network.load_state_dict(checkpoint['target_network_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.beta_alpha = checkpoint['beta_alpha']
        self.beta_beta = checkpoint['beta_beta']
        self.training_step = checkpoint['training_step']

    def export_to_onnx(self, filepath: str) -> None:
        """
        Export Q-Network ke ONNX format untuk inference di VPS.

        ONNX memungkinkan inference tanpa PyTorch menggunakan onnxruntime
        yang jauh lebih ringan (cocok untuk VPS 8GB RAM).

        Args:
            filepath: Path untuk export ONNX model (.onnx)
        """
        # Set model ke eval mode
        self.q_network.eval()

        # Create dummy input untuk tracing
        dummy_input = torch.randn(1, self.state_size).to(self.device)

        # Export ke ONNX
        torch.onnx.export(
            self.q_network,
            dummy_input,
            filepath,
            export_params=True,
            opset_version=11,
            do_constant_folding=True,
            input_names=['state'],
            output_names=['q_values'],
            dynamic_axes={
                'state': {0: 'batch_size'},
                'q_values': {0: 'batch_size'}
            }
        )

        # Set model kembali ke train mode
        self.q_network.train()
