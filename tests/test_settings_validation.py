"""
test_settings_validation.py — Unit tests untuk BUG #6 fix.
Test validator credentials dengan berbagai kombinasi EXECUTION_MODE dan USE_TESTNET.
"""
import pytest
from pydantic import ValidationError, SecretStr
from src.config.settings import Settings


def test_paper_mode_no_credentials_needed():
    """
    Paper mode tidak butuh credentials sama sekali.
    Harusnya tidak error meski credentials None.
    """
    # Should NOT raise error even with None credentials
    settings = Settings(
        EXECUTION_MODE='paper',
        USE_TESTNET=False,
        BINANCE_API_KEY=None,
        BINANCE_API_SECRET=None,
        BINANCE_TESTNET_KEY=None,
        BINANCE_TESTNET_SECRET=None,
        CEREBRAS_API_KEY=SecretStr('test_cerebras'),
        GROQ_API_KEY=SecretStr('test_groq'),
        CONCIERGE_API_KEY=SecretStr('test_concierge'),
        TELEGRAM_BOT_TOKEN=SecretStr('test_token'),
        TELEGRAM_CHAT_ID='12345'
    )
    assert settings.EXECUTION_MODE == 'paper'
    assert settings.BINANCE_API_KEY is None
    assert settings.BINANCE_TESTNET_KEY is None


def test_live_mode_production_credentials_required():
    """
    Live mode dengan USE_TESTNET=False wajib punya production credentials.
    Harusnya ValidationError jika None.
    """
    # Should raise ValidationError
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            EXECUTION_MODE='live',
            USE_TESTNET=False,
            BINANCE_API_KEY=None,
            BINANCE_API_SECRET=None,
            BINANCE_TESTNET_KEY=None,
            BINANCE_TESTNET_SECRET=None,
            CEREBRAS_API_KEY=SecretStr('test_cerebras'),
            GROQ_API_KEY=SecretStr('test_groq'),
            CONCIERGE_API_KEY=SecretStr('test_concierge'),
            TELEGRAM_BOT_TOKEN=SecretStr('test_token'),
            TELEGRAM_CHAT_ID='12345'
        )

    # Check error message
    error_str = str(exc_info.value)
    assert 'BINANCE_API_KEY' in error_str or 'BINANCE_API_SECRET' in error_str
    assert 'EXECUTION_MODE=live' in error_str


def test_live_mode_testnet_credentials_required():
    """
    Live mode dengan USE_TESTNET=True wajib punya testnet credentials.
    Harusnya ValidationError jika None.
    """
    # Should raise ValidationError
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            EXECUTION_MODE='live',
            USE_TESTNET=True,
            BINANCE_API_KEY=None,
            BINANCE_API_SECRET=None,
            BINANCE_TESTNET_KEY=None,
            BINANCE_TESTNET_SECRET=None,
            CEREBRAS_API_KEY=SecretStr('test_cerebras'),
            GROQ_API_KEY=SecretStr('test_groq'),
            CONCIERGE_API_KEY=SecretStr('test_concierge'),
            TELEGRAM_BOT_TOKEN=SecretStr('test_token'),
            TELEGRAM_CHAT_ID='12345'
        )

    # Check error message
    error_str = str(exc_info.value)
    assert 'BINANCE_TESTNET_KEY' in error_str or 'BINANCE_TESTNET_SECRET' in error_str
    assert 'EXECUTION_MODE=live' in error_str


def test_live_mode_with_production_credentials_ok():
    """
    Live mode dengan production credentials yang valid harusnya OK.
    """
    # Should NOT raise error
    settings = Settings(
        EXECUTION_MODE='live',
        USE_TESTNET=False,
        BINANCE_API_KEY=SecretStr('prod_key_123'),
        BINANCE_API_SECRET=SecretStr('prod_secret_456'),
        BINANCE_TESTNET_KEY=None,
        BINANCE_TESTNET_SECRET=None,
        CEREBRAS_API_KEY=SecretStr('test_cerebras'),
        GROQ_API_KEY=SecretStr('test_groq'),
        CONCIERGE_API_KEY=SecretStr('test_concierge'),
        TELEGRAM_BOT_TOKEN=SecretStr('test_token'),
        TELEGRAM_CHAT_ID='12345'
    )
    assert settings.EXECUTION_MODE == 'live'
    assert settings.USE_TESTNET is False
    assert settings.BINANCE_API_KEY.get_secret_value() == 'prod_key_123'


def test_live_mode_with_testnet_credentials_ok():
    """
    Live mode dengan testnet credentials yang valid harusnya OK.
    """
    # Should NOT raise error
    settings = Settings(
        EXECUTION_MODE='live',
        USE_TESTNET=True,
        BINANCE_API_KEY=None,
        BINANCE_API_SECRET=None,
        BINANCE_TESTNET_KEY=SecretStr('testnet_key_789'),
        BINANCE_TESTNET_SECRET=SecretStr('testnet_secret_012'),
        CEREBRAS_API_KEY=SecretStr('test_cerebras'),
        GROQ_API_KEY=SecretStr('test_groq'),
        CONCIERGE_API_KEY=SecretStr('test_concierge'),
        TELEGRAM_BOT_TOKEN=SecretStr('test_token'),
        TELEGRAM_CHAT_ID='12345'
    )
    assert settings.EXECUTION_MODE == 'live'
    assert settings.USE_TESTNET is True
    assert settings.BINANCE_TESTNET_KEY.get_secret_value() == 'testnet_key_789'

