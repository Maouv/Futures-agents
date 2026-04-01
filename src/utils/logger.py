"""
logger.py — Loguru setup terpusat.
Semua modul WAJIB import logger dari sini. DILARANG pakai print().
"""
import sys
from loguru import logger


def setup_logger(log_level: str = "INFO") -> None:
    """Configure loguru dengan format standar project."""
    logger.remove()  # Hapus default handler

    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>",
        level=log_level,
        colorize=True,
    )

    logger.add(
        "logs/trading_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
        level="DEBUG",
        rotation="00:00",      # Rotate setiap tengah malam
        retention="30 days",   # Simpan 30 hari
        compression="zip",
        enqueue=True,          # Thread-safe
    )


# Export logger langsung agar bisa `from src.utils.logger import logger`
__all__ = ["logger", "setup_logger"]
