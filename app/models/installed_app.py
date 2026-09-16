"""
已安装程序数据类。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InstalledApp:
    id: str                              # 唯一标识（注册表 key 路径 / AppX PackageFullName）
    name: str
    publisher: str = ""
    version: str = ""
    install_date: str = ""               # YYYY-MM-DD
    install_location: str = ""           # 主程序路径
    estimated_size: int = 0              # 注册表估值（KB）
    actual_size: int = 0                 # 扫描 install_location 算出的字节
    uninstall_cmd: str = ""              # 主卸载命令（UninstallString）
    quiet_uninstall_cmd: str = ""        # 静默卸载命令
    uninstall_string_raw: str = ""       # 原始 UninstallString（用于调试）
    app_type: str = "exe"                # exe / msi / appx / msix
    icon_path: str = ""
    source: str = ""                     # 注册表来源：HKLM/HKCU/AppX/...
    is_system: bool = False              # 是否为系统关键程序
    is_movable: bool = True              # 是否可搬家（UWP/AppX 通常 False）

    @property
    def display_size(self) -> str:
        if self.actual_size > 0:
            from app.common.size_fmt import format_size
            return format_size(self.actual_size)
        if self.estimated_size > 0:
            return f"~{self.estimated_size // 1024} MB"
        return "未知"

    @property
    def display_type(self) -> str:
        return {
            "exe": "传统程序",
            "msi": "MSI 程序",
            "appx": "Store 应用",
            "msix": "MSIX 应用",
        }.get(self.app_type, "其他")


@dataclass
class LeftoverItem:
    """卸载残留项。"""
    app_id: str
    path: str
    item_type: str                 # directory / file / registry_key / shortcut
    size_bytes: int = 0
    description: str = ""
    risk: str = "safe"             # safe / moderate
    selected: bool = True


@dataclass
class UninstallResult:
    success: bool = False
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    message: str = ""
    cancelled: bool = False


@dataclass
class LeftoverScanResult:
    items: List[LeftoverItem] = field(default_factory=list)
    total_size: int = 0