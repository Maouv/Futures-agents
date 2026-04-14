# test_onnx.py
import numpy as np
import sys
sys.path.append('/path/to/rl_upload')  # sesuaikan path lu
from src.rl.inference import load_inference_engine

engine = load_inference_engine(
    model_path='data/rl_models/best_model.onnx',
    norm_params_path='data/rl_models/normalization_params.npz'
)

# Dummy state 13 features
dummy_state = np.random.randn(13).astype(np.float32)
action, q_values = engine.select_action(dummy_state)

print(f"Action: {action} (0=SKIP, 1=ENTRY)")
print(f"Q-values: {q_values}")
print(f"Confidence: {engine.get_state_importance(dummy_state):.4f}")
