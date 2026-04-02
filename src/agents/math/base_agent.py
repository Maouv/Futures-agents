"""
base_agent.py — Abstract base class untuk semua Math Agents.
"""
from abc import ABC, abstractmethod
from typing import Any
import pandas as pd
from pydantic import BaseModel
from src.utils.logger import logger


class BaseAgent(ABC):
    """Base class untuk semua Math Agents."""

    @abstractmethod
    def run(self, *args, **kwargs) -> BaseModel:
        """Jalankan agent dan return Pydantic Model."""
        pass

    def _log(self, message: str) -> None:
        logger.info(f"[{self.__class__.__name__}] {message}")

    def _log_error(self, message: str) -> None:
        logger.error(f"[{self.__class__.__name__}] {message}")
