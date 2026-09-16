"""
软件搬家记录数据类。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MoveRecord:
    id: str                                  # UUID
    app_name: str
    app_id: str                              # InstalledApp.id
    source_path: str                         # 原位置
    target_path: str                         # 新位置
    link_type: str                           # junction / symlink
    moved_size: int = 0                      # 字节数
    moved_at: str = ""                       # ISO 时间
    backup_path: str = ""                    # 备份目录（搬家时保留 7 天）
    app_type: str = "exe"
    status: str = "active"                   # active / rolled_back
    notes: str = ""


@dataclass
class PrecheckResult:
    ok: bool = True
    errors: list = field(default_factory=list)        # 错误信息
    warnings: list = field(default_factory=list)      # 警告信息
    target_free_bytes: int = 0
    source_size_bytes: int = 0
    blocking_processes: list = field(default_factory=list)


@dataclass
class MoveResult:
    success: bool = False
    record_id: str = ""
    message: str = ""
    error: str = ""
    bytes_moved: int = 0
    elapsed_seconds: float = 0.0


@dataclass
class RollbackResult:
    success: bool = False
    message: str = ""
    error: str = ""