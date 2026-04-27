Baris 328 — ganti jadi inline tapi pertahankan DB update logic:

except ccxt.InsufficientFunds:
    self._log_error(f"Insufficient funds for trade {trade_id}")
    with get_session() as db:
        db_trade = db.query(PaperTrade).get(trade_id)
        if db_trade:
            db_trade.status = 'FAILED'
            db_trade.close_reason = 'EXCHANGE_ERROR'
            db_trade.close_timestamp = datetime.now(timezone.utc)
    return ExecutionResult(action="SKIP", reason="Insufficient funds")
except ccxt.InvalidOrder as e:
    self._log_error(f"Invalid order for trade {trade_id}: {e}")
    with get_session() as db:
        db_trade = db.query(PaperTrade).get(trade_id)
        if db_trade:
            db_trade.status = 'FAILED'
            db_trade.close_reason = 'EXCHANGE_ERROR'
            db_trade.close_timestamp = datetime.now(timezone.utc)
    return ExecutionResult(action="SKIP", reason=f"Invalid order: {str(e)}")
except ccxt.NetworkError:
    self._log_error(f"Network error for trade {trade_id} — resetting exchange")
    with get_session() as db:
        db_trade = db.query(PaperTrade).get(trade_id)
        if db_trade:
            db_trade.status = 'FAILED'
            db_trade.close_reason = 'EXCHANGE_ERROR'
            db_trade.close_timestamp = datetime.now(timezone.utc)
    reset_exchange()
    return ExecutionResult(action="SKIP", reason="Network error, exchange reset")
except ccxt.ExchangeError as e:
    self._log_error(f"Exchange error for trade {trade_id}: {e}")
    with get_session() as db:
        db_trade = db.query(PaperTrade).get(trade_id)
        if db_trade:
            db_trade.status = 'FAILED'
            db_trade.close_reason = 'EXCHANGE_ERROR'
            db_trade.close_timestamp = datetime.now(timezone.utc)
    return ExecutionResult(action="SKIP", reason=f"Exchange error: {str(e)}")
except Exception as e:
    self._log_error(f"Unexpected error for trade {trade_id}: {e}")
    with get_session() as db:
        db_trade = db.query(PaperTrade).get(trade_id)
        if db_trade:
            db_trade.status = 'FAILED'
            db_trade.close_reason = 'EXCHANGE_ERROR'
            db_trade.close_timestamp = datetime.now(timezone.utc)
    return self._handle_ccxt_error(e, "live limit execution")

baris 495

except ccxt.InsufficientFunds:
    self._log_error("Insufficient funds during live market execution")
    return ExecutionResult(action="SKIP", reason="Insufficient funds")
except ccxt.InvalidOrder as e:
    self._log_error(f"Invalid order during live market execution: {e}")
    return ExecutionResult(action="SKIP", reason=f"Invalid order: {str(e)}")
except ccxt.NetworkError:
    self._log_error("Network error during live market execution — resetting exchange")
    reset_exchange()
    return ExecutionResult(action="SKIP", reason="Network error, exchange reset")
except ccxt.ExchangeError as e:
    self._log_error(f"Exchange error during live market execution: {e}")
    return ExecutionResult(action="SKIP", reason=f"Exchange error: {str(e)}")
except Exception as e:
    return self._handle_ccxt_error(e, "live market execution")
