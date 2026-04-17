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
