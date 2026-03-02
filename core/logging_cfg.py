"""
core/logging_cfg.py — 统一 logging 配置

使用方式：
    from core.logging_cfg import get_logger
    logger = get_logger(__name__)

    # 入口脚本（main.py）初始化时可指定 log 文件：
    from core.logging_cfg import setup_logging
    setup_logging(project="emotion-cycle")
"""

import logging
import sys
from pathlib import Path


def setup_logging(
    project: str = None,
    level: int = logging.INFO,
    fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    to_file: bool = False,
) -> None:
    """
    初始化全局 logging。
    - 总是输出到 stdout
    - to_file=True 时同时写入 data/{project}/logs/app.log
    """
    handlers = [logging.StreamHandler(sys.stdout)]

    if to_file and project:
        from core.paths import Paths
        log_path = Paths.logs(project) / "app.log"
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=handlers,
        force=True,   # 允许重复调用覆盖已有配置
    )


def get_logger(name: str) -> logging.Logger:
    """各模块统一用此函数获取 logger，无需重复配置 basicConfig。"""
    return logging.getLogger(name)
