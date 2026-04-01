"""
main.py — Entry point dan orchestrator utama.
Siklus 15 menit diimplementasikan di Phase 5.
"""
from src.config.settings import settings
from src.data.storage import init_db
from src.utils.logger import logger, setup_logger


def main() -> None:
    setup_logger()
    logger.info(f"Starting Crypto Multi-Agent Trading System")
    logger.info(f"Mode: {settings.EXECUTION_MODE.upper()} | Testnet: {settings.USE_TESTNET}")

    init_db()

    logger.info("Phase 0 scaffold ready. Main loop will be implemented in Phase 5.")


if __name__ == "__main__":
    main()
