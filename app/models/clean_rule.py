"""
清理规则数据类。

规则匹配方式：
- 通过 paths 列表（支持环境变量 %TEMP% 等）获取一组候选目录
- 通过 patterns（glob，如 *.log / cache_*）匹配文件名
- min_age_days 限制仅清理 N 天前文件
- 风险等级 safe / moderate / risky
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CleanRule:
    id: str
    category: str               # 系统/用户/浏览器/应用/开发工具
    name: str                   # 显示名
    description: str            # 详细说明
    paths: List[str]            # 候选目录（含环境变量）
    patterns: List[str] = field(default_factory=list)   # 文件 glob 模式
    min_age_days: int = 1       # 跳过 N 天内修改的文件
    risk: str = "safe"          # safe / moderate / risky
    requires_admin: bool = False
    enabled_by_default: bool = True
    icon: Optional[str] = None  # 图标名称（FIF.XXX）


@dataclass
class CleanItem:
    """扫描到的单个可清理项。"""
    rule_id: str
    rule_name: str
    path: str                   # 文件或目录绝对路径
    is_dir: bool
    size_bytes: int
    risk: str
    reason: str = ""            # 匹配原因/规则说明


@dataclass
class ScanResult:
    items: List[CleanItem] = field(default_factory=list)
    total_size: int = 0
    elapsed_seconds: float = 0.0
    cancelled: bool = False


@dataclass
class CleanResult:
    deleted_count: int = 0
    failed_count: int = 0
    deleted_bytes: int = 0
    errors: List[str] = field(default_factory=list)
    cancelled: bool = False