# Core Rules

Always run `source venv/bin/activate` before any `python`, `pytest`, `pip`, or `ruff` command.

## Non-Obvious Dependencies

```
analyst_agent    → llm_rate_limiter.get_provider_limiter()
risk_agent       → luxalgo_smc.OrderBlock
position_manager → exchange.cancel_algo_order(), exchange.place_algo_order()
```

## PEP 8 & Style Standard

Line length is 100. Use Ruff — not black, not flake8.

Naming:
```python
# Classes → PascalCase
class TrendAgent:
class RiskResult:

# Functions & methods → snake_case
def run_trading_cycle():
def get_session():

# Constants → SCREAMING_SNAKE_CASE
MAX_RETRIES = 3

# Private methods → leading underscore
def _log(self, message: str):
def _check_single_pending(self, trade: dict):
```

Type hints — always use Python 3.12 style:
```python
# Correct
def run(self, df: pd.DataFrame) -> TrendResult:
def get_session() -> Generator[Session, None, None]:
value: int | None = None
items: list[str] = []

# Wrong
def run(self, df: pd.DataFrame) -> Optional[TrendResult]:
value: Optional[int] = None
items: List[str] = []
```

Imports — grouped and sorted by Ruff isort (I rule):
```python
# 1. stdlib
import threading
from datetime import UTC, datetime

# 2. third-party
import ccxt
import pandas as pd
from pydantic import BaseModel

# 3. internal
from src.config.settings import settings
from src.utils.logger import logger
```

Never use `print()` — always `logger` from `src.utils.logger`.
Never use stdlib `logging` — always `loguru` via `src.utils.logger`.

