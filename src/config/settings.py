"""
settings.py — Configuration hub. Secrets from .env, everything else from config.json.

Migration: Non-secret fields now live in config.json, accessed via config_loader.
Secrets (SecretStr) remain loaded from .env via pydantic-settings, with fallback
to config.json secrets section (for ${ENV_VAR} interpolation).

All existing `settings.XXX` access patterns work unchanged.
"""
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra='ignore',  # Ignore env vars that moved to config.json
    )

    # ── Binance Secrets (from .env only) ─────────────────────────────────────
    BINANCE_API_KEY: Optional[SecretStr] = Field(None, description="Binance Futures API Key")
    BINANCE_API_SECRET: Optional[SecretStr] = Field(None, description="Binance Futures API Secret")
    BINANCE_TESTNET_KEY: Optional[SecretStr] = Field(None, description="Binance Testnet API Key")
    BINANCE_TESTNET_SECRET: Optional[SecretStr] = Field(None, description="Binance Testnet API Secret")

    # ── Telegram Secret (from .env only) ─────────────────────────────────────
    TELEGRAM_BOT_TOKEN: SecretStr = Field(..., description="Telegram Bot Token")

    # ── LLM API Keys (from .env, fallback to config.json secrets) ────────────
    CEREBRAS_API_KEY: Optional[SecretStr] = Field(None, description="Cerebras API Key")
    GROQ_API_KEY: Optional[SecretStr] = Field(None, description="Groq API Key")
    CONCIERGE_API_KEY: Optional[SecretStr] = Field(None, description="Concierge API Key")

    @field_validator('BINANCE_API_KEY', 'BINANCE_API_SECRET')
    @classmethod
    def validate_production_credentials(cls, v, info):
        """Pastikan credential production ada jika live+mainnet."""
        from src.config.config_loader import load_system_config
        system = load_system_config()
        execution_mode = system['execution_mode']
        use_testnet = system['use_testnet']

        if execution_mode == 'live' and not use_testnet:
            if v is None:
                raise ValueError(
                    'BINANCE_API_KEY dan BINANCE_API_SECRET wajib jika '
                    'execution_mode=live dan use_testnet=False'
                )
        return v

    @field_validator('BINANCE_TESTNET_KEY', 'BINANCE_TESTNET_SECRET')
    @classmethod
    def validate_testnet_credentials(cls, v, info):
        """Pastikan credential testnet ada jika live+testnet."""
        from src.config.config_loader import load_system_config
        system = load_system_config()
        execution_mode = system['execution_mode']
        use_testnet = system['use_testnet']

        if execution_mode == 'live' and use_testnet:
            if v is None:
                raise ValueError(
                    'BINANCE_TESTNET_KEY dan BINANCE_TESTNET_SECRET wajib jika '
                    'execution_mode=live dan use_testnet=True'
                )
        return v

    def model_post_init(self, __context) -> None:
        """
        Resolve LLM API keys: if .env doesn't have them, try config.json secrets.
        This runs after pydantic has loaded .env values.
        """
        from src.config.config_loader import load_secrets_config
        secrets = load_secrets_config()

        # CEREBRAS_API_KEY
        if self.CEREBRAS_API_KEY is None:
            val = secrets['cerebras_api_key']
            if val:
                object.__setattr__(self, 'CEREBRAS_API_KEY', SecretStr(val))

        # GROQ_API_KEY
        if self.GROQ_API_KEY is None:
            val = secrets['groq_api_key']
            if val:
                object.__setattr__(self, 'GROQ_API_KEY', SecretStr(val))

        # CONCIERGE_API_KEY
        if self.CONCIERGE_API_KEY is None:
            val = secrets['concierge_api_key']
            if val:
                object.__setattr__(self, 'CONCIERGE_API_KEY', SecretStr(val))

    # ── System Properties (from config.json) ────────────────────────────────

    @property
    def EXECUTION_MODE(self) -> str:
        override = getattr(self, '_execution_mode_override', None)
        if override is not None:
            return override
        from src.config.config_loader import load_system_config
        return load_system_config()['execution_mode']

    @EXECUTION_MODE.setter
    def EXECUTION_MODE(self, value: str):
        """Allow runtime override (e.g., /mode command)."""
        self._execution_mode_override = value

    @property
    def USE_TESTNET(self) -> bool:
        override = getattr(self, '_use_testnet_override', None)
        if override is not None:
            return override
        from src.config.config_loader import load_system_config
        return load_system_config()['use_testnet']

    @USE_TESTNET.setter
    def USE_TESTNET(self, value: bool):
        """Allow runtime override (e.g., /mode command)."""
        self._use_testnet_override = value

    @property
    def ENVIRONMENT(self) -> str:
        from src.config.config_loader import load_system_config
        return load_system_config()['environment']

    @property
    def CONFIRM_MAINNET(self) -> bool:
        from src.config.config_loader import load_system_config
        return load_system_config()['confirm_mainnet']

    @property
    def TELEGRAM_CHAT_ID(self) -> str:
        from src.config.config_loader import load_system_config
        return load_system_config()['telegram_chat_id']

    @property
    def BINANCE_REST_URL(self) -> str:
        from src.config.config_loader import load_system_config
        return load_system_config()['binance_rest_url']

    @property
    def BINANCE_WS_URL(self) -> str:
        from src.config.config_loader import load_system_config
        return load_system_config()['binance_ws_url']

    @property
    def BINANCE_TESTNET_URL(self) -> str:
        from src.config.config_loader import load_system_config
        return load_system_config()['binance_testnet_url']

    @property
    def BINANCE_TESTNET_WS_URL(self) -> str:
        from src.config.config_loader import load_system_config
        return load_system_config()['binance_testnet_ws_url']

    # ── Trading Properties (from config.json) ───────────────────────────────

    @property
    def FUTURES_DEFAULT_LEVERAGE(self) -> int:
        from src.config.config_loader import load_trading_config
        return load_trading_config()['leverage']

    @property
    def FUTURES_MARGIN_TYPE(self) -> str:
        from src.config.config_loader import load_trading_config
        return load_trading_config()['margin_type']

    @property
    def RISK_PER_TRADE_USD(self) -> float:
        from src.config.config_loader import load_trading_config
        return load_trading_config()['risk_per_trade_usd']

    @property
    def RISK_REWARD_RATIO(self) -> float:
        from src.config.config_loader import load_trading_config
        return load_trading_config()['risk_reward_ratio']

    @property
    def MAX_OPEN_POSITIONS(self) -> int:
        from src.config.config_loader import load_trading_config
        return load_trading_config()['max_open_positions']

    @property
    def ORDER_EXPIRY_CANDLES(self) -> int:
        from src.config.config_loader import load_trading_config
        return load_trading_config()['order_expiry_candles']

    @property
    def DISABLE_SESSION_FILTER(self) -> bool:
        from src.config.config_loader import load_trading_config
        return load_trading_config()['disable_session_filter']

    @property
    def TRAILING_STOP_ENABLED(self) -> bool:
        from src.config.config_loader import load_trailing_stop_config
        return load_trailing_stop_config()['enabled']

    @property
    def TRAILING_STOP_STEPS(self) -> list:
        from src.config.config_loader import load_trailing_stop_config
        return load_trailing_stop_config()['steps']

    # ── LLM Properties (from config.json) ──────────────────────────────────

    @property
    def CEREBRAS_BASE_URL(self) -> str:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['cerebras']['base_url']

    @property
    def CEREBRAS_MODEL(self) -> str:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['cerebras']['model']

    @property
    def LLM_CEREBRAS_MAX_CONCURRENT(self) -> int:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['cerebras']['max_concurrent']

    @property
    def LLM_CEREBRAS_RPM(self) -> int:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['cerebras']['rpm']

    @property
    def LLM_CEREBRAS_MIN_INTERVAL(self) -> float:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['cerebras']['min_interval']

    @property
    def LLM_RETRY_ON_429(self) -> int:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['cerebras']['retry_on_429']

    @property
    def LLM_GROQ_MAX_CONCURRENT(self) -> int:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['groq']['max_concurrent']

    @property
    def LLM_GROQ_RPM(self) -> int:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['groq']['rpm']

    @property
    def LLM_GROQ_MIN_INTERVAL(self) -> float:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['groq']['min_interval']

    @property
    def GROQ_BASE_URL(self) -> str:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['groq']['base_url']

    @property
    def GROQ_MODEL(self) -> str:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['groq']['model']

    @property
    def CONCIERGE_BASE_URL(self) -> str:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['concierge']['base_url']

    @property
    def CONCIERGE_MODEL(self) -> str:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['concierge']['model']

    @property
    def CONCIERGE_TIMEOUT_SEC(self) -> int:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['concierge']['timeout_sec']

    @property
    def CONCIERGE_MAX_TOKENS(self) -> int:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['concierge']['max_tokens']

    @property
    def LLM_FAST_TIMEOUT_SEC(self) -> int:
        from src.config.config_loader import load_llm_config
        return load_llm_config()['cerebras']['timeout_sec']


# Singleton — import ini di mana saja
settings = Settings()
