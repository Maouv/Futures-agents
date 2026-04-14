
# 🔒 ENV_AND_SECRETS_RULE.md

**TARGET AUDIENCE:** AI Coding Assistants (Claude, GPT-4, Cursor, Aider, dll)
**SEVERITY:** CRITICAL — Pelanggaran aturan ini akan menyebabkan *Security Breach* atau *System Crash*.

Kamu **DILARANG KERAS** menulis string literal untuk hal-hal di bawah ini. Semua harus dirujuk dari Environment Variables (`.env`) yang dikelola melalui Pydantic Settings.

---

## 1. 🚫 ZERO-TOLERANCE HARDCODING

Dalam kondisi apapun, **JANGAN PERNAH** menulis kode seperti ini:
```python
# ❌ DILARANG KERAS!
api_key = "BNBxxxxxxx..."
telegram_token = "123456:ABC-DEF..."
base_url = "https://fapi.binance.com" # URL Futures
model_endpoint = "https://api.cerebras.ai/v1"
leverage = 5
```

**ATURAN MUTLAK:** Satu-satunya cara yang diperbolehkan untuk mengakses konfigurasi adalah dengan memanggil objek `Settings` yang sudah dibuat di `src/config/settings.py`.

---

## 2. 🏗️ ARSITEKTUR KONFIGURASI (Pydantic Settings)

Project ini **WAJIB** menggunakan `pydantic-settings` untuk memvalidasi `.env` saat startup.
Semua env vars harus didefinisikan di **satu tempat saja**: `src/config/settings.py`.

**Kamu WAJIB mengikuti pola ini jika diminta menambah env var baru:**

```python
# src/config/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, HttpUrl, SecretStr

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True # Force exact match
    )

    # --- CONTOH PENULISAN YANG WAJIB DITIRU ---
    
    # 1. Secrets (Wajib pakai SecretStr agar tidak ke-print di logs)
    BINANCE_API_KEY: SecretStr = Field(..., description="Binance API Key")
    BINANCE_API_SECRET: SecretStr = Field(..., description="Binance API Secret")
    TELEGRAM_BOT_TOKEN: SecretStr = Field(..., description="Telegram Bot Token")
    
    # 2. URLs (Wajib pakai HttpUrl untuk validasi format otomatis)
    BINANCE_REST_URL: HttpUrl = Field(default="https://fapi.binance.com") # Default Futures API
    
    # 3. LLM Endpoints (Wajib HttpUrl)
    CEREBRAS_BASE_URL: HttpUrl = Field(default="https://api.cerebras.ai/v1")
    GROQ_BASE_URL: HttpUrl = Field(default="https://api.groq.com/openai/v1")
    MODAL_CONCIERGE_URL: HttpUrl = Field(...) # Endpoint custom dari Modal
    
    # 4. Execution & Futures Config (Enum/Literal untuk mencegah typo)
    EXECUTION_MODE: str = Field(default="paper") # Hanya menerima "paper" atau "live"
    FUTURES_MARGIN_TYPE: str = Field(default="isolated") # Hanya "isolated" atau "cross"
    FUTURES_DEFAULT_LEVERAGE: int = Field(default=5)
    
    # 5. LLM Specific Configs
    LLM_FAST_TIMEOUT_SEC: int = Field(default=45) # Untuk Cerebras & Groq
    CONCIERGE_TIMEOUT_SEC: int = Field(default=120) # KHUSUS untuk GLM-5 (Lambat)
    CONCIERGE_MAX_TOKENS: int = Field(default=2500) # KHUSUS untuk GLM-5 Reasoning

# Singleton instance
settings = Settings()
```

---

## 3. 🔑 CARA MENGGUNAKAN SECRETS DI KODE

Jika kamu perlu menggunakan API Key di file manapun, **WAJIB** seperti ini:

```python
from src.config.settings import settings

# ❌ SALAH: Langsung pakai os.getenv
# import os; key = os.getenv("BINANCE_API_KEY")

# ✅ BENAR: Pakai objek settings + .get_secret_value()
exchange = ccxt.binanceusdm({ # PERHATIKAN: binanceusdm BUKAN binance
    "apiKey": settings.BINANCE_API_KEY.get_secret_value(),
    "secret": settings.BINANCE_API_SECRET.get_secret_value(),
    "options": {"defaultType": "future"}
})
```

**PERINGATAN:** Jika kamu lupa menulis `.get_secret_value()`, Pydantic akan mengembalikan string `"*******"` dan API Binance akan langsung menolak request dengan error `Invalid API Key`. **Jangan pernah lupa `.get_secret_value()`.**

---

## 4. 🤖 ATURAN KHUSUS: AI MODEL ENDPOINTS

Jika diminta menambah integrasi model AI, aturan tambahannya:

1. **Base URL Model:** Harus didefinisikan sebagai `HttpUrl` di `Settings`.
2. **Model Name:** Harus berupa string biasa di `.env` (contoh: `CEREBRAS_MODEL="qwen-3-235b..."`, `GROQ_MODEL="llama-3.1-8b-instant"`). **JANGAN HARDCODE nama model** di dalam logic agent.
3. **Timeout:** Gunakan variabel dari Settings (`settings.LLM_FAST_TIMEOUT_SEC` untuk Cerebras/Groq, `settings.CONCIERGE_TIMEOUT_SEC` untuk GLM-5). **JANGAN TULIS angka 45 atau 120 langsung di kode.**

```python
# Cara yang BENAR saat membuat client AI
import openai

# Untuk Analyst (Cerebras)
client_analyst = openai.OpenAI(
    api_key=settings.CEREBRAS_API_KEY.get_secret_value(), 
    base_url=str(settings.CEREBRAS_BASE_URL), 
    timeout=settings.LLM_FAST_TIMEOUT_SEC
)

# Untuk Concierge (Modal GLM-5)
client_concierge = openai.OpenAI(
    api_key=settings.MODAL_TOKEN.get_secret_value(), 
    base_url=str(settings.MODAL_CONCIERGE_URL), 
    timeout=settings.CONCIERGE_TIMEOUT_SEC # Wajib pakai timeout khusus GLM-5
)
```

---

## 5. 📡 ATURAN KHUSUS: API BASE URLs

Endpoint API tidak boleh ditulis di tempat lain. Binance memiliki banyak URL (Prod, Testnet, Spot, Futures). Jika salah menulis, bot bisa mengirim order ke *wrong environment*.

**Tabel Sumber Kebenaran URL (Hanya boleh ada di `.env`):**
| Variable Name | Nilai Default | Keterangan |
|---------------|---------------|------------|
| `BINANCE_REST_URL` | `https://fapi.binance.com` | FUTURES Production (fapi) |
| `BINANCE_TESTNET_URL`| `https://testnet.binancefuture.com` | FUTURES Testnet |
| `CEREBRAS_BASE_URL` | `https://api.cerebras.ai/v1` | Analyst LLM |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Commander LLM |

*Contoh Implementasi:*
```python
# ❌ SALAH:
# url = "https://testnet.binancefuture.com/api/v3/ticker/price"

# ✅ BENAR:
url = f"{settings.BINANCE_TESTNET_URL}/fapi/v1/ticker/price"
```

---

## 6. 🛡️ FAIL-FAST MECHANISM

Jika user meminta kamu membuat kode yang membaca env var, dan env var tersebut **tidak ada** di file `.env.example` atau di class `Settings`, kamu **WAJIB MENOLAK** dan memberikan respons:

> "⚠️ **ENV VAR MISSING**: Saya diminta menggunakan `[NAMA_VAR]`, tapi variabel tersebut belum didefinisikan di `src/config/settings.py`. Tolong tambahkan ke `.env.example` dan class `Settings` terlebih dahulu, lalu beritahu saya nilai default-nya."

Jangan pernah menulis fallback yang berbahaya seperti:
```python
# ❌ DILARANG! Jangan pernah fallback ke string kosong atau "default" untuk Secrets
api_key = os.getenv("BINANCE_KEY", "default_key") 
```

Jika sebuah secret tidak ada saat `Settings()` di-instantiate, **BIARKAN PYDANTIC MENCRASH APLIKASI** (throw `ValidationError`). Ini jauh lebih baik daripada bot berjalan dengan kredensial salah dan gagal saat live trading.
