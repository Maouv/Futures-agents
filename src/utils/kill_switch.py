"""
kill_switch.py — File-based emergency stop mechanism.

Jika file `data/kill_switch` ada, bot menolak membuka trade baru.
Ini BUKAN menghentikan proses — hanya mencegah NEW entries.
Posisi yang sudah terbuka tetap di-manage oleh Binance server-side SL/TP.

Usage:
    # Aktifkan kill switch (dari terminal VPS)
    touch data/kill_switch

    # Nonaktifkan
    rm data/kill_switch

    # Dalam kode
    from src.utils.kill_switch import check_kill_switch
    if check_kill_switch():
        return  # Skip entry
"""
import os

from src.utils.logger import logger

KILL_SWITCH_PATH = "data/kill_switch"


def check_kill_switch() -> bool:
    """
    Cek apakah kill switch aktif.
    Return True jika file kill_switch ada.
    """
    return os.path.exists(KILL_SWITCH_PATH)


def create_kill_switch() -> None:
    """
    Aktifkan kill switch. Bot tidak akan membuka trade baru.
    """
    os.makedirs(os.path.dirname(KILL_SWITCH_PATH), exist_ok=True)
    with open(KILL_SWITCH_PATH, "w") as f:
        f.write(f"Kill switch activated.\n")
    logger.critical("KILL SWITCH ACTIVATED — no new trades will be opened.")


def remove_kill_switch() -> None:
    """
    Nonaktifkan kill switch. Bot kembali bisa membuka trade.
    """
    if os.path.exists(KILL_SWITCH_PATH):
        os.remove(KILL_SWITCH_PATH)
        logger.info("Kill switch DEACTIVATED — bot can open new trades again.")
    else:
        logger.debug("Kill switch file not found — already deactivated.")
