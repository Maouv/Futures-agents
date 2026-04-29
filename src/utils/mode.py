"""Centralized mode resolution — single source of truth for execution mode."""

from src.config.settings import settings


def get_current_mode() -> str:
    """Return execution mode tag: 'paper', 'testnet', or 'mainnet'."""
    if settings.EXECUTION_MODE != "live":
        return "paper"
    return "testnet" if settings.USE_TESTNET else "mainnet"


def get_mode_label() -> str:
    """Return uppercase mode label for display: 'PAPER', 'TESTNET', 'MAINNET'."""
    return get_current_mode().upper()


def get_mode_emoji() -> str:
    """Return emoji label per mode untuk Telegram notification."""
    mode = get_current_mode()
    return {
        "paper": "📄",
        "testnet": "🟡",
        "mainnet": "🟢",
    }.get(mode, "❓")


def get_mode_tag() -> str:
    """Return text tag per mode untuk Telegram notification."""
    mode = get_current_mode()
    return {
        "paper": "[PAPER]",
        "testnet": "[TESTNET]",
        "mainnet": "[MAINNET]",
    }.get(mode, "[UNKNOWN]")


def init_mode() -> None:
    """Initialize and log execution mode at startup."""
    mode = get_current_mode()
    label = get_mode_label()
    from src.utils.logger import logger
    logger.info(f"Execution mode initialized: {label} ({mode})")
