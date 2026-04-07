# 🚀 Panduan RL Training di Google Colab (GPU Gratis)

Panduan lengkap untuk menjalankan Reinforcement Learning training menggunakan Google Colab dengan GPU T4 gratis.

---

## 📋 Prerequisites

Sebelum mulai, pastikan kamu sudah:

1. ✅ Generate training data dari backtest (file CSV di `data/rl_training/`)
2. ✅ Punya Google Account (untuk Google Drive & Colab)
3. ✅ Internet connection yang stabil

---

## 🎯 Overview Workflow

```
Local Machine (VPS)          →  Google Drive        →  Google Colab (GPU)
├─ Run backtest                 ├─ Upload CSV files    ├─ Install dependencies
├─ Generate CSV signals         ├─ Upload src/ code    ├─ Load data from Drive
└─ Export to rl_training/       └─ Organize structure  └─ Run training
                                                              ↓
                                                         Save model to Drive
                                                              ↓
                                                         Download .pth file
```

---

## 📁 Step 1: Prepare Files untuk Upload

### **Files yang Perlu Di-upload ke Google Drive:**

```
📁 MyDrive/
  └── rl_trading/              ← Folder utama (create jika belum ada)
      ├── data/
      │   └── rl_training/
      │       ├── BTCUSDT_2024_signals.csv    ← Training data
      │       ├── ETHUSDT_2024_signals.csv    ← (optional)
      │       └── ...                          ← More CSV files
      │
      └── src/
          ├── rl/
          │   ├── trainer.py          ← Main training script
          │   ├── environment.py      ← RL environment
          │   ├── dqn_agent.py        ← DQN model
          │   └── replay_buffer.py    ← Experience replay
          │
          └── backtest/
              └── metrics.py          ← TradeResult model
```

### **Cara Prepare Files:**

#### **Option A: Manual Upload (Rekomendasi untuk pertama kali)**

1. Buka [Google Drive](https://drive.google.com)
2. Create folder: `rl_trading` di root MyDrive
3. Inside `rl_trading`, create:
   ```
   rl_trading/
   ├── data/rl_training/
   └── src/rl/
   ```

4. Upload files:

   **a. Training Data (CSV files):**
   ```bash
   # Di local machine (VPS)
   # Download CSV files dari VPS ke komputer lokal
   scp root@your-vps:/root/futures-agents/data/rl_training/*.csv ./
   
   # Lalu upload manual ke Google Drive:
   # MyDrive > rl_trading > data > rl_training
   ```

   **b. Source Code:**
   ```bash
   # Download dari VPS
   scp -r root@your-vps:/root/futures-agents/src/rl ./
   
   # Also download metrics.py
   scp root@your-vps:/root/futures-agents/src/backtest/metrics.py ./src/backtest/
   
   # Upload ke Google Drive:
   # MyDrive > rl_trading > src
   ```

#### **Option B: Upload via Google Colab (Lebih cepat)**

Lihat di Step 3 bagian upload.

---

## 📓 Step 2: Create New Colab Notebook

1. Buka [Google Colab](https://colab.research.google.com)
2. Klik **"New Notebook"** atau **"File > New notebook"**
3. Rename notebook: `RL_Training_Futures_Agents.ipynb`

---

## 🐍 Step 3: Colab Notebook Code (Copy-Paste)

### **Cell 1: Mount Google Drive**

```python
from google.colab import drive
import sys
import os

# Mount Google Drive
drive.mount('/content/drive')

# Add project path ke Python path
project_path = '/content/drive/MyDrive/rl_trading'
sys.path.append(project_path)

# Verify path exists
if os.path.exists(project_path):
    print(f"✅ Project path found: {project_path}")
else:
    print(f"❌ Project path NOT found: {project_path}")
    print("Please create folder 'rl_trading' in your Google Drive root")

# Check contents
print("\n📁 Folder contents:")
!ls -la "$project_path"
```

**Expected Output:**
```
✅ Project path found: /content/drive/MyDrive/rl_trading

📁 Folder contents:
total 8
drwx------ 2 root root 4096 Apr  7 06:45 data
drwx------ 2 root root 4096 Apr  7 06:45 src
```

---

### **Cell 2: Install Dependencies**

```python
# Install required packages
!pip install torch pandas numpy loguru pydantic matplotlib -q

# Verify installations
import torch
import pandas as pd
import numpy as np
from loguru import logger

print(f"✅ PyTorch version: {torch.__version__}")
print(f"✅ Pandas version: {pd.__version__}")
print(f"✅ NumPy version: {np.__version__}")
```

**Expected Output:**
```
✅ PyTorch version: 2.1.0+cu121
✅ Pandas version: 2.0.3
✅ NumPy version: 1.25.2
```

---

### **Cell 3: Check GPU Availability**

```python
import torch

print("=" * 60)
print("GPU INFORMATION")
print("=" * 60)

if torch.cuda.is_available():
    print(f"✅ CUDA available: {torch.cuda.is_available()}")
    print(f"✅ CUDA version: {torch.version.cuda}")
    print(f"✅ GPU device: {torch.cuda.get_device_name(0)}")
    print(f"✅ GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
    device = "cuda"
else:
    print("⚠️ CUDA not available, using CPU")
    print("Go to: Runtime > Change runtime type > GPU")
    device = "cpu"

print("=" * 60)
print(f"🎯 Using device: {device}")
print("=" * 60)
```

**Expected Output (Jika GPU aktif):**
```
============================================================
GPU INFORMATION
============================================================
✅ CUDA available: True
✅ CUDA version: 12.1
✅ GPU device: Tesla T4
✅ GPU memory: 15.75 GB
============================================================
🎯 Using device: cuda
============================================================
```

**⚠️ Jika GPU tidak aktif:**
1. Klik menu: **Runtime > Change runtime type**
2. Pilih: **GPU** di "Hardware accelerator"
3. Klik **Save**
4. Run Cell 3 lagi

---

### **Cell 4: Upload Files (Jika Belum Ada di Drive)**

**Skip cell ini kalau sudah upload manual di Step 1.**

```python
# Upload CSV training data
from google.colab import files
import shutil
import os

# Create directories
os.makedirs(f"{project_path}/data/rl_training", exist_ok=True)
os.makedirs(f"{project_path}/src/rl", exist_ok=True)
os.makedirs(f"{project_path}/src/backtest", exist_ok=True)

print("📤 Upload CSV files (dari local machine)")
print("=" * 60)

uploaded_csv = files.upload()

for fn in uploaded_csv.keys():
    # Move to correct location
    src_path = f"/content/{fn}"
    dst_path = f"{project_path}/data/rl_training/{fn}"
    shutil.move(src_path, dst_path)
    print(f"✅ Moved: {fn} → {dst_path}")

print("\n📤 Upload source code files (trainer.py, environment.py, dll)")
print("=" * 60)

uploaded_src = files.upload()

for fn in uploaded_src.keys():
    if fn.endswith('.py'):
        if 'metrics' in fn:
            dst_path = f"{project_path}/src/backtest/{fn}"
        else:
            dst_path = f"{project_path}/src/rl/{fn}"
        
        src_path = f"/content/{fn}"
        shutil.move(src_path, dst_path)
        print(f"✅ Moved: {fn} → {dst_path}")

print("\n📁 Current structure:")
!tree "$project_path" -L 3
```

---

### **Cell 5: Verify Training Data**

```python
import pandas as pd
import glob

# Find all CSV files
csv_dir = f"{project_path}/data/rl_training"
csv_files = glob.glob(f"{csv_dir}/*.csv")

print("=" * 60)
print("TRAINING DATA VERIFICATION")
print("=" * 60)

if not csv_files:
    print("❌ No CSV files found!")
    print(f"Please upload CSV files to: {csv_dir}")
else:
    print(f"✅ Found {len(csv_files)} CSV files:\n")
    
    total_trades = 0
    for csv_file in sorted(csv_files):
        df = pd.read_csv(csv_file)
        filename = os.path.basename(csv_file)
        
        print(f"📄 {filename}")
        print(f"   - Rows: {len(df)}")
        print(f"   - Columns: {len(df.columns)}")
        
        # Check required columns
        required_cols = [
            'timestamp', 'signal', 'outcome', 'pnl',
            'trend_bias', 'bos_type', 'ob_high', 'ob_low',
            'ob_size', 'distance_to_ob', 'atr', 'fvg_present',
            'candle_body_ratio', 'hour_of_day', 'consecutive_losses',
            'time_since_last_trade', 'current_drawdown_pct'
        ]
        
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            print(f"   ❌ Missing columns: {missing_cols}")
        else:
            print(f"   ✅ All RL features present")
        
        total_trades += len(df)
        print()
    
    print("=" * 60)
    print(f"📊 Total trades: {total_trades}")
    print("=" * 60)
```

**Expected Output:**
```
============================================================
TRAINING DATA VERIFICATION
============================================================
✅ Found 2 CSV files:

📄 BTCUSDT_2024_signals.csv
   - Rows: 127
   - Columns: 23
   ✅ All RL features present

📄 ETHUSDT_2024_signals.csv
   - Rows: 89
   - Columns: 23
   ✅ All RL features present

============================================================
📊 Total trades: 216
============================================================
```

---

### **Cell 6: Configure Training Parameters**

```python
# ==========================================
# TRAINING HYPERPARAMETERS
# ==========================================

# Training settings
BATCH_SIZE = 32                 # Batch size untuk training
EPISODES = 500                  # Maximum episodes (atau sampai early stopping)
REPLAY_BUFFER_SIZE = 10000      # Maximum experiences di replay buffer
MIN_BUFFER_SIZE = 100           # Minimum experiences sebelum mulai training
TARGET_UPDATE_FREQ = 10         # Update target network setiap N episodes
LEARNING_RATE = 0.001           # Learning rate untuk Adam optimizer
GAMMA = 0.95                    # Discount factor
SAVE_EVERY = 50                 # Save checkpoint setiap N episodes

# Directories
CSV_DIR = f"{project_path}/data/rl_training"
OUTPUT_DIR = f"{project_path}/data/rl_models"

# Create output directory
import os
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Device
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# State/Action dimensions
STATE_SIZE = 13  # Number of RL features
ACTION_SIZE = 2  # SKIP=0, ENTRY=1

print("=" * 60)
print("TRAINING CONFIGURATION")
print("=" * 60)
print(f"Device: {DEVICE}")
print(f"State size: {STATE_SIZE}")
print(f"Action size: {ACTION_SIZE}")
print(f"Episodes: {EPISODES}")
print(f"Batch size: {BATCH_SIZE}")
print(f"Learning rate: {LEARNING_RATE}")
print(f"CSV directory: {CSV_DIR}")
print(f"Output directory: {OUTPUT_DIR}")
print("=" * 60)
```

---

### **Cell 7: Initialize Trainer**

```python
# Import modules
from src.rl.trainer import DQNTrainer

# Initialize trainer
trainer = DQNTrainer(
    csv_dir=CSV_DIR,
    output_dir=OUTPUT_DIR,
    state_size=STATE_SIZE,
    action_size=ACTION_SIZE,
    device=DEVICE
)

print("✅ Trainer initialized successfully!")
print(f"\n📊 Training will use data from:")
print(f"   {CSV_DIR}")
print(f"\n💾 Models will be saved to:")
print(f"   {OUTPUT_DIR}")
```

**Expected Output:**
```
✅ Trainer initialized successfully!

📊 Training will use data from:
   /content/drive/MyDrive/rl_trading/data/rl_training

💾 Models will be saved to:
   /content/drive/MyDrive/rl_trading/data/rl_models
```

---

### **Cell 8: Run Training 🚀**

```python
import time

print("=" * 60)
print("🚀 STARTING RL TRAINING")
print("=" * 60)
print("⏱️ This may take a while...")
print("💡 You can monitor progress in the output below")
print("=" * 60)

# Start training
start_time = time.time()

try:
    final_metrics = trainer.train()
    
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = int(elapsed_time % 60)
    
    print("\n" + "=" * 60)
    print("✅ TRAINING COMPLETED!")
    print("=" * 60)
    print(f"⏱️ Total time: {minutes}m {seconds}s")
    print(f"\n📊 Final Metrics:")
    for key, value in final_metrics.items():
        if isinstance(value, float):
            print(f"   {key}: {value:.2f}")
        else:
            print(f"   {key}: {value}")
    print("=" * 60)
    
except KeyboardInterrupt:
    print("\n⚠️ Training interrupted by user")
    print("💾 Model checkpoints saved to Google Drive")
    
except Exception as e:
    print(f"\n❌ Error during training: {e}")
    import traceback
    traceback.print_exc()
```

**Expected Output (During Training):**
```
============================================================
🚀 STARTING RL TRAINING
============================================================
⏱️ This may take a while...
💡 You can monitor progress in the output below
============================================================

Training device: cuda
Found 2 CSV files: ['BTCUSDT_2024_signals.csv', 'ETHUSDT_2024_signals.csv']
Loaded 216 total samples from all CSV files

Episode 50/500 | Avg Reward: 45.2 | Win Rate: 62.3% | Epsilon: 0.15
Episode 100/500 | Avg Reward: 52.8 | Win Rate: 65.7% | Epsilon: 0.12
Episode 150/500 | Avg Reward: 61.3 | Win Rate: 68.1% | Epsilon: 0.09
...
```

**Training akan berjalan selama:**
- 200-500 trades: ~15-30 menit (GPU T4)
- 1000+ trades: ~1-2 jam (GPU T4)

---

### **Cell 9: Check Saved Models**

```python
import glob

print("=" * 60)
print("SAVED MODELS")
print("=" * 60)

# List all saved files
model_files = glob.glob(f"{OUTPUT_DIR}/*.pth")
plot_files = glob.glob(f"{OUTPUT_DIR}/*.png")

if model_files:
    print(f"\n✅ Found {len(model_files)} model files:\n")
    for f in sorted(model_files):
        size_mb = os.path.getsize(f) / (1024 * 1024)
        filename = os.path.basename(f)
        print(f"   📄 {filename} ({size_mb:.2f} MB)")
else:
    print("\n❌ No model files found")

if plot_files:
    print(f"\n📈 Found {len(plot_files)} plot files:\n")
    for f in sorted(plot_files):
        filename = os.path.basename(f)
        print(f"   📊 {filename}")

print("\n" + "=" * 60)
```

---

### **Cell 10: Download Best Model**

```python
from google.colab import files

best_model_path = f"{OUTPUT_DIR}/best_dqn_model.pth"
plot_path = f"{OUTPUT_DIR}/training_progress.png"

print("=" * 60)
print("DOWNLOAD RESULTS")
print("=" * 60)

# Download best model
if os.path.exists(best_model_path):
    print(f"\n⬇️ Downloading: best_dqn_model.pth")
    files.download(best_model_path)
    print("✅ Download complete!")
else:
    print("\n❌ Best model file not found")

# Download training plot
if os.path.exists(plot_path):
    print(f"\n⬇️ Downloading: training_progress.png")
    files.download(plot_path)
    print("✅ Download complete!")

print("\n" + "=" * 60)
```

---

## 📊 Step 4: Monitor Training Progress

Selama training berjalan, kamu akan melihat output seperti ini:

```
Episode 50/500 | Avg Reward: 45.2 | Win Rate: 62.3% | Epsilon: 0.15
Episode 100/500 | Avg Reward: 52.8 | Win Rate: 65.7% | Epsilon: 0.12
Episode 150/500 | Avg Reward: 61.3 | Win Rate: 68.1% | Epsilon: 0.09
...
```

### **Metrics Explanation:**

| Metric | Meaning | Target |
|--------|---------|--------|
| **Avg Reward** | Rata-rata total reward per episode | Meningkat seiring waktu |
| **Win Rate** | Persentase keputusan profit | Di atas 60% |
| **Epsilon** | Exploration rate | Menurun dari 1.0 ke 0.01 |

### **Expected Behavior:**

✅ **GOOD Training:**
- Avg Reward naik secara gradual
- Win Rate stabil di 60-75%
- Tidak ada crash atau error

❌ **BAD Training:**
- Avg Reward stagnan atau turun
- Win Rate < 50%
- Error messages

---

## 🎯 Step 5: Analyze Results

Setelah training selesai, check:

### **1. Training Plot**

File: `training_progress.png`

Plot akan menampilkan:
- Reward per episode (naik/turun)
- Win rate per episode
- Loss values

### **2. Model Quality**

```python
# Check best model performance
best_reward = trainer.best_reward
total_episodes = len(trainer.episode_rewards)

print(f"Best reward achieved: {best_reward:.2f}")
print(f"Total episodes trained: {total_episodes}")

# Calculate average of last 50 episodes
if len(trainer.episode_rewards) >= 50:
    last_50_avg = sum(trainer.episode_rewards[-50:]) / 50
    print(f"Average reward (last 50 episodes): {last_50_avg:.2f}")
```

---

## 🔧 Troubleshooting

### **Problem 1: "ModuleNotFoundError: No module named 'src'"**

**Solution:**
```python
# Add this to Cell 1 (after mounting drive)
import sys
sys.path.append('/content/drive/MyDrive/rl_trading')
```

---

### **Problem 2: "CUDA out of memory"**

**Solution:**
```python
# Reduce batch size
BATCH_SIZE = 16  # Instead of 32

# Or use CPU
DEVICE = "cpu"
```

---

### **Problem 3: "FileNotFoundError: CSV files not found"**

**Solution:**
```python
# Check if files uploaded correctly
!ls -la "/content/drive/MyDrive/rl_trading/data/rl_training/"

# If empty, re-upload files using Cell 4
```

---

### **Problem 4: Training sangat lambat**

**Solutions:**

1. **Check GPU aktif:**
   ```python
   !nvidia-smi
   ```
   Should show Tesla T4 or similar

2. **Reduce episodes:**
   ```python
   EPISODES = 200  # Instead of 500
   ```

3. **Use smaller batch size:**
   ```python
   BATCH_SIZE = 16
   ```

---

## 📥 Step 6: Deploy ke VPS

Setelah download model dari Colab:

### **1. Upload ke VPS:**

```bash
# Di local machine
scp best_dqn_model.pth root@your-vps:/root/futures-agents/data/rl_models/
```

### **2. Test Inference di VPS:**

```python
# Di VPS
from src.rl.dqn_agent import DQNAgent
import torch

# Load model
agent = DQNAgent(state_size=13, action_size=2, device="cpu")
agent.q_network.load_state_dict(
    torch.load('/root/futures-agents/data/rl_models/best_dqn_model.pth')
)
agent.q_network.eval()

# Test inference
import numpy as np
test_state = np.random.rand(13).astype(np.float32)
action = agent.act(test_state, training=False)
print(f"Recommended action: {'ENTRY' if action == 1 else 'SKIP'}")
```

---

## 🎓 Tips & Best Practices

### **1. Training Data Quality:**

- ✅ Minimal 200+ trades untuk training yang meaningful
- ✅ Combine multiple pairs dan years
- ✅ Pastikan tidak ada missing values

### **2. Hyperparameter Tuning:**

```python
# Experiment dengan:
LEARNING_RATE = 0.0005   # Lower = slower but stable
GAMMA = 0.98             # Higher = more future-focused
BATCH_SIZE = 64          # Larger = more stable gradients
```

### **3. Save Strategy:**

Models di-save otomatis ke Google Drive, jadi:
- ✅ Tidak perlu khawatir session timeout
- ✅ Bisa resume training nanti
- ✅ Safe dari crash

### **4. Session Limits:**

Google Colab free tier:
- ⏱️ Max 12 hours per session
- 💡 Solution: Train in chunks (save checkpoints)

---

## 🆘 Getting Help

Kalau ada masalah:

1. **Check Error Message:** Copy-paste ke Google
2. **Verify Files:** Pastikan semua files uploaded dengan benar
3. **Check GPU:** Runtime > Change runtime type > GPU
4. **Restart Runtime:** Runtime > Restart runtime

---

## 🎉 Summary

**Yang sudah kamu lakukan:**

1. ✅ Prepare training data dari backtest
2. ✅ Upload ke Google Drive
3. ✅ Setup Colab environment
4. ✅ Run RL training dengan GPU
5. ✅ Download trained model
6. ✅ Ready to deploy ke VPS!

**Next Steps:**

- Test model dengan data baru
- Integrate ke live trading system
- Monitor performance
- Retrain periodically dengan data terbaru

---

## 📚 Additional Resources

- [Google Colab FAQ](https://research.google.com/colaboratory/faq.html)
- [PyTorch Documentation](https://pytorch.org/docs/)
- [Reinforcement Learning Basics](https://www.youtube.com/watch?v=Wcribes_E)

---

**Happy Training! 🚀**
