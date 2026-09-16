"""字节单位格式化。"""
from __future__ import annotations

from typing import Tuple

_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


def format_size(size_bytes: int | float, decimal: int = 2) -> str:
    """将字节数格式化为人类可读字符串，如 '1.23 GB'。

    size_bytes < 0 返回 '0 B'。
    """
    if size_bytes is None or size_bytes < 0:
        return "0 B"
    size = float(size_bytes)
    for unit in _UNITS:
        if size < 1024.0 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.{decimal}f} {unit}"
        size /= 1024.0
    return f"{size:.{decimal}f} {_UNITS[-1]}"


def format_size_chinese(size_bytes: int | float) -> str:
    """中文单位：字节/KB/MB/GB/TB。"""
    if size_bytes is None or size_bytes < 0:
        return "0 字节"
    size = float(size_bytes)
    units_zh = ["字节", "KB", "MB", "GB", "TB", "PB"]
    for unit in units_zh:
        if size < 1024.0 or unit == units_zh[-1]:
            if unit == "字节":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} {units_zh[-1]}"


def parse_size(text: str) -> int:
    """反向解析 '1.5 GB' -> 字节数。无法解析则返回 0。"""
    if not text:
        return 0
    text = text.strip().upper()
    try:
        for unit in sorted(_UNITS, key=len, reverse=True):
            if text.endswith(unit.upper()):
                num = float(text[: -len(unit)].strip())
                factor = 1024 ** _UNITS.index(unit)
                return int(num * factor)
        return int(float(text))
    except (ValueError, AttributeError):
        return 0


def format_duration(seconds: int | float) -> str:
    """秒 -> 可读字符串（'2 分钟 30 秒'）。"""
    if seconds is None or seconds < 0:
        return "0 秒"
    s = int(seconds)
    if s < 60:
        return f"{s} 秒"
    if s < 3600:
        m = s // 60
        sec = s % 60
        return f"{m} 分 {sec} 秒"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h} 时 {m} 分"