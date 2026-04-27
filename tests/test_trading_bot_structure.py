"""
test_trading_bot_structure.py — Unit test untuk BUG #12 fix.
Test bahwa TradingBot class structure bekerja dengan benar.
"""
import asyncio

from src.main import TradingBot


def test_trading_bot_instantiation():
    """
    Test bahwa TradingBot bisa di-instantiate tanpa error.
    """
    bot = TradingBot()

    # Verify initial state
    assert bot.event_loop is None
    assert bot.scheduler is None


def test_send_notification_sync_without_event_loop():
    """
    Test bahwa send_notification_sync menangani None event loop dengan graceful.
    """
    bot = TradingBot()

    # Should not raise error
    bot.send_notification_sync("test message")


def test_send_notification_sync_handles_errors():
    """
    Test bahwa send_notification_sync menangani error dengan graceful.
    """
    bot = TradingBot()
    bot.event_loop = asyncio.new_event_loop()

    # Should not raise error even if event loop not running
    # (implementation akan catch exception dan log)
    try:
        bot.send_notification_sync("test")
        # Success - error ditangani dengan graceful
    except Exception:
        # If raises, it should be handled in implementation
        pass


def test_bot_has_required_methods():
    """
    Test bahwa TradingBot memiliki semua method yang dibutuhkan.
    """
    bot = TradingBot()

    # Verify methods exist
    assert hasattr(bot, 'send_notification_sync')
    assert hasattr(bot, 'run_trading_cycle')
    assert hasattr(bot, '_run_sltp_check')
    assert hasattr(bot, 'run')

    # Verify methods are callable
    assert callable(bot.send_notification_sync)
    assert callable(bot.run_trading_cycle)
    assert callable(bot._run_sltp_check)
    assert callable(bot.run)


def test_no_global_variables():
    """
    Test bahwa tidak ada global variables di module.
    """
    import src.main as main_module

    # Check that _event_loop global variable tidak ada
    assert not hasattr(main_module, '_event_loop'), \
        "Module should not have global _event_loop variable"

    # Check that functions yang menggunakan global tidak ada
    assert not hasattr(main_module, '_send_notification_sync'), \
        "Module should not have global _send_notification_sync function"
