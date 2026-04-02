"""
settings.py — Single source of truth untuk semua konfigurasi.
Menggunakan pydantic-settings untuk validasi otomatis saat startup.
Jika ada env var yang missing, aplikasi akan CRASH dengan ValidationError (by design).
"""
from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # ── System ──────────────────────────────────────────────────────────────
    ENVIRONMENT: str = Field(default="development")
    EXECUTION_MODE: str = Field(default="paper", description="'paper' atau 'live'")
    USE_TESTNET: bool = Field(default=False, description="True = connect ke Binance Testnet")

    # ── Binance Futures (Production) ─────────────────────────────────────────
    BINANCE_REST_URL: HttpUrl = Field(default="https://fapi.binance.com")
    BINANCE_WS_URL: str = Field(default="wss://fstream.binance.com/ws")
    BINANCE_API_KEY: SecretStr = Field(..., description="Binance Futures API Key")
    BINANCE_API_SECRET: SecretStr = Field(..., description="Binance Futures API Secret")

    # ── Binance Testnet ──────────────────────────────────────────────────────
    BINANCE_TESTNET_URL: HttpUrl = Field(default="https://testnet.binancefuture.com")
    BINANCE_TESTNET_WS_URL: str = Field(default="wss://stream.binancefuture.com/ws")
    BINANCE_TESTNET_KEY: SecretStr = Field(..., description="Binance Testnet API Key")
    BINANCE_TESTNET_SECRET: SecretStr = Field(..., description="Binance Testnet API Secret")

    # ── Futures Trading Params ───────────────────────────────────────────────
    FUTURES_MARGIN_TYPE: str = Field(default="isolated", description="'isolated' atau 'cross'")
    FUTURES_DEFAULT_LEVERAGE: int = Field(default=10, ge=1, le=125)

    # ── Trading Strategy Params ───────────────────────────────────────────────
    RISK_PER_TRADE_USD: float = Field(default=10.0, description="Risk per trade dalam USD")
    RISK_REWARD_RATIO: float = Field(default=2.0, description="Risk:Reward ratio (2 = 1:2)")

    # ── LLM: Analyst (Cerebras) ──────────────────────────────────────────────
    CEREBRAS_API_KEY: SecretStr = Field(..., description="Cerebras API Key")
    CEREBRAS_BASE_URL: HttpUrl = Field(default="https://api.cerebras.ai/v1/chat/completions")
    CEREBRAS_MODEL: str = Field(default="qwen-3-235b-a22b-instruct-2507")

    # ── LLM: Commander (Groq) ────────────────────────────────────────────────
    GROQ_API_KEY: SecretStr = Field(..., description="Groq API Key")
    GROQ_BASE_URL: HttpUrl = Field(default="https://api.groq.com/openai/v1/chat/completions")
    GROQ_MODEL: str = Field(default="llama-3.1-8b-instant")

    # ── LLM: Concierge ──────────────────────────────────────────────────────
    CONCIERGE_API_KEY: SecretStr = Field(..., description="API key untuk Concierge model")
    CONCIERGE_BASE_URL: HttpUrl = Field(default="https://api.groq.com/openai/v1/chat/completions")
    CONCIERGE_MODEL: str = Field(default="llama-3.1-8b-instant")

    # ── Telegram ─────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: SecretStr = Field(..., description="Telegram Bot Token")
    TELEGRAM_CHAT_ID: str = Field(..., description="Telegram Chat ID (string, bisa negatif untuk group)")

    # ── Timeouts & Limits ────────────────────────────────────────────────────
    LLM_FAST_TIMEOUT_SEC: int = Field(default=45, description="Timeout Cerebras & Groq")
    CONCIERGE_TIMEOUT_SEC: int = Field(default=600, description="Timeout GLM-5 (lambat)")
    CONCIERGE_MAX_TOKENS: int = Field(default=5000, description="Max tokens GLM-5 reasoning")


# Singleton — import ini di mana saja
settings = Settings()
