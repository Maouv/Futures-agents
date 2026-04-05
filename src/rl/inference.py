"""
ONNX Inference untuk DQN Model di VPS Production.

Module ini digunakan di VPS untuk menjalankan trained model
tanpa perlu install PyTorch (yang berat untuk VPS 8GB RAM).

Menggunakan onnxruntime yang ringan dan cepat.
"""

import numpy as np
import onnxruntime as ort
from typing import Tuple, Optional
from pathlib import Path


class DQNInference:
    """
    Inference engine untuk DQN model dalam ONNX format.

    Load model dari best_model.onnx dan perform action selection
    berdasarkan Q-values.

    Attributes:
        session: ONNX Runtime inference session
        input_name: Name of input tensor in ONNX model
        output_name: Name of output tensor in ONNX model
        state_mean: Mean untuk state normalization
        state_std: Std untuk state normalization
    """

    def __init__(
        self,
        model_path: str = "data/rl_models/best_model.onnx",
        state_mean: Optional[np.ndarray] = None,
        state_std: Optional[np.ndarray] = None,
        device: str = "cpu"
    ) -> None:
        """
        Initialize DQN Inference engine.

        Args:
            model_path: Path ke ONNX model file (.onnx)
            state_mean: Mean untuk state normalization (shape: (14,))
            state_std: Std untuk state normalization (shape: (14,))
            device: Device untuk inference ('cpu' atau 'cuda')
        """
        self.model_path = Path(model_path)

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file tidak ditemukan: {model_path}")

        # Set inference device
        providers = ['CPUExecutionProvider'] if device == "cpu" else ['CUDAExecutionProvider']

        # Create ONNX Runtime session
        self.session = ort.InferenceSession(str(self.model_path), providers=providers)

        # Get input/output names from model
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

        # State normalization parameters
        # Jika tidak diberikan, gunakan default (no normalization)
        if state_mean is None:
            self.state_mean = np.zeros(14, dtype=np.float32)
        else:
            self.state_mean = state_mean.astype(np.float32)

        if state_std is None:
            self.state_std = np.ones(14, dtype=np.float32)
        else:
            self.state_std = state_std.astype(np.float32)

    def normalize_state(self, state: np.ndarray) -> np.ndarray:
        """
        Normalize state menggunakan mean dan std.

        Penting untuk menjaga konsistensi dengan training.

        Args:
            state: Raw state observation (shape: (14,))

        Returns:
            Normalized state (shape: (14,))
        """
        # Avoid division by zero
        state_std_safe = np.where(self.state_std == 0, 1.0, self.state_std)

        normalized_state = (state - self.state_mean) / state_std_safe
        return normalized_state.astype(np.float32)

    def predict_q_values(self, state: np.ndarray) -> np.ndarray:
        """
        Predict Q-values untuk state yang diberikan.

        Args:
            state: State observation (shape: (14,))

        Returns:
            Q-values array (shape: (2,))
        """
        # Normalize state
        normalized_state = self.normalize_state(state)

        # Add batch dimension (ONNX expects shape: [batch_size, 14])
        state_batch = normalized_state.reshape(1, -1)

        # Run inference
        outputs = self.session.run(
            [self.output_name],
            {self.input_name: state_batch}
        )

        # Extract Q-values (remove batch dimension)
        q_values = outputs[0][0]

        return q_values

    def select_action(
        self,
        state: np.ndarray,
        strategy: str = "greedy"
    ) -> Tuple[int, np.ndarray]:
        """
        Select action berdasarkan Q-values.

        Strategies:
        - greedy: Pilih action dengan Q-value tertinggi (exploitation)
        - epsilon: Tambahkan random exploration (epsilon=0.1)

        Args:
            state: State observation (shape: (14,))
            strategy: Action selection strategy ('greedy' atau 'epsilon')

        Returns:
            Tuple of (action, q_values)
            - action: Selected action (0 atau 1)
            - q_values: Q-values untuk semua actions (shape: (2,))
        """
        # Get Q-values
        q_values = self.predict_q_values(state)

        # Select action
        if strategy == "greedy":
            action = int(np.argmax(q_values))
        elif strategy == "epsilon":
            # Epsilon-greedy dengan epsilon=0.1
            epsilon = 0.1
            if np.random.random() < epsilon:
                action = np.random.randint(0, 2)  # Random action
            else:
                action = int(np.argmax(q_values))
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        return action, q_values

    def get_state_importance(self, state: np.ndarray) -> float:
        """
        Hitung confidence/importance dari Q-values prediction.

        Berguna untuk filtering: hanya ambil action jika confidence tinggi.

        Args:
            state: State observation (shape: (14,))

        Returns:
            Confidence score (semakin tinggi = semakin yakin)
        """
        q_values = self.predict_q_values(state)

        # Confidence = selisih antara Q-value tertinggi dan terendah
        confidence = float(np.max(q_values) - np.min(q_values))

        return confidence

    def batch_predict(self, states: np.ndarray) -> np.ndarray:
        """
        Batch prediction untuk multiple states sekaligus.

        Lebih efisien untuk inference banyak states.

        Args:
            states: Array of states (shape: [N, 14])

        Returns:
            Q-values untuk semua states (shape: [N, 2])
        """
        # Normalize semua states
        normalized_states = self.normalize_state(states)

        # Run batch inference
        outputs = self.session.run(
            [self.output_name],
            {self.input_name: normalized_states}
        )

        q_values = outputs[0]
        return q_values


def load_inference_engine(
    model_path: str = "data/rl_models/best_model.onnx",
    norm_params_path: Optional[str] = None
) -> DQNInference:
    """
    Helper function untuk load inference engine dengan normalization params.

    Args:
        model_path: Path ke ONNX model
        norm_params_path: Path ke normalization parameters (.npz file)

    Returns:
        DQNInference instance yang siap digunakan
    """
    state_mean = None
    state_std = None

    # Load normalization params jika ada
    if norm_params_path is not None:
        norm_path = Path(norm_params_path)
        if norm_path.exists():
            norm_data = np.load(norm_path)
            state_mean = norm_data.get('state_mean')
            state_std = norm_data.get('state_std')

    # Create inference engine
    engine = DQNInference(
        model_path=model_path,
        state_mean=state_mean,
        state_std=state_std
    )

    return engine
