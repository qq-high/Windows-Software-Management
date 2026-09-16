"""
简单日志：写入文件 + stderr，便于调试与操作审计。
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import LOG_FILE, APP_NAME

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化全局日志（应用启动调用一次即可）。"""
    global _initialized
    root = logging.getLogger(APP_NAME)
    if _initialized:
        return root

    root.setLevel(level)
    root.propagate = False

    # 控制台 handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
    root.addHandler(console)

    # 文件 handler（10MB 滚动）
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
        root.addHandler(file_handler)
    except Exception:
        # 写入失败也不致命（如权限问题）
        pass

    _initialized = True
    return root


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger（懒加载，setup_logging 由 main 调用）。"""
    return logging.getLogger(f"{APP_NAME}.{name}")


def log_operation(operation: str, detail: str = "") -> None:
    """记录一次用户操作（写入专用 'OPERATION' logger，便于审计）。"""
    logger = get_logger("operation")
    logger.info(f"[{operation}] {detail}")