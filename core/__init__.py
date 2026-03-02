"""
core/__init__.py
提供最常用的两个入口，让其他模块可以直接 from core import Paths, get_logger
"""

from core.paths import Paths
from core.logging_cfg import get_logger, setup_logging

__all__ = ["Paths", "get_logger", "setup_logging"]
