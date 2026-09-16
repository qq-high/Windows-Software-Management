"""
磁盘使用情况查询服务。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from app.common.paths import list_drives


def get_drive_info() -> List[Dict]:
    """获取所有盘器的信息列表。"""
    return list_drives()


def get_c_drive_info() -> Dict:
    """获取 C 盘的信息（如不存在返回空字典）。"""
    for d in list_drives():
        if d["drive"].upper().startswith("C"):
            return d
    return {}


def get_directory_size(path: Path) -> int:
    """递归计算目录大小（字节）。"""
    total = 0
    try:
        for entry in path.rglob("*"):
            try:
                if entry.is_file() and not entry.is_junction():
                    total += entry.stat().st_size
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        pass
    return total


def quick_directory_size(path: Path, max_depth: int = 3) -> int:
    """快速估算目录大小（限制深度），仅扫描前 max_depth 层。"""
    if not path.exists():
        return 0
    total = 0
    try:
        for root, dirs, files in __import__("os").walk(str(path)):
            rel_depth = Path(root).relative_to(path).parts
            if len(rel_depth) > max_depth:
                dirs.clear()
                continue
            for f in files:
                try:
                    fp = Path(root) / f
                    if not fp.is_junction():
                        total += fp.stat().st_size
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        pass
    return total