"""
全局配置：版本号、受保护路径、APP 数据目录、风险等级等。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

# ============ 应用信息 ============
APP_NAME = "Windows 系统优化管家"
APP_VERSION = "1.0.0"
APP_AUTHOR = "WinOptimizer"
APP_DESCRIPTION = "一款集成 C 盘清理、软件卸载、软件搬家于一体的 Windows 优化工具。"

# ============ APP 数据目录（用于日志、历史记录、缓存） ============
def _get_appdata_dir() -> Path:
    """获取 APPDATA 下的应用目录，确保存在。"""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    app_dir = Path(base) / "Windows系统优化管家"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


APPDATA_DIR: Path = _get_appdata_dir()
LOG_FILE: Path = APPDATA_DIR / "log.txt"
MOVE_HISTORY_FILE: Path = APPDATA_DIR / "move_history.json"
UNINSTALL_HISTORY_FILE: Path = APPDATA_DIR / "uninstall_history.json"
CLEAN_HISTORY_FILE: Path = APPDATA_DIR / "clean_history.json"
SETTINGS_FILE: Path = APPDATA_DIR / "settings.json"

# ============ 资源目录 ============
RESOURCES_DIR: Path = Path(__file__).resolve().parent / "resources"
RULES_FILE: Path = RESOURCES_DIR / "rules" / "default_rules.json"
ICONS_DIR: Path = RESOURCES_DIR / "icons"

# ============ 受保护路径（绝对禁止清理/扫描删除） ============
# 形如 "C:\Windows\System32" "C:\Users\xxx\Documents" "C:\Program Files"
# 在 cleaner 中通过 Path.resolve() 后比对前缀；命中则直接跳过
PROTECTED_PATH_PATTERNS: List[str] = [
    r"C:\Windows\System32",
    r"C:\Windows\SysWOW64",
    r"C:\Windows\WinSxS",
    r"C:\Windows\Boot",
    r"C:\Windows\SystemApps",
    r"C:\Windows\ImmersiveControlPanel",
    r"C:\Windows\security",
    r"C:\Windows\Servicing",
    r"C:\Windows\Winsxs",
    r"C:\Windows\assembly",
    r"C:\Windows\Microsoft.NET",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData\Microsoft\Windows\Defender",
    r"C:\ProgramData\Microsoft\Windows Defender",
    r"C:\Users\*\Documents",
    r"C:\Users\*\Desktop",
    r"C:\Users\*\Downloads",
    r"C:\Users\*\Pictures",
    r"C:\Users\*\Music",
    r"C:\Users\*\Videos",
    r"C:\Users\*\Favorites",
    r"C:\Users\*\OneDrive",
    r"C:\Users\*\AppData\Local\Packages",  # UWP 应用包
    r"C:\Recovery",
    r"C:\$Recycle.Bin",
    r"C:\System Volume Information",
]

# ============ 系统关键程序白名单（不可卸载/搬家） ============
SYSTEM_PROTECTED_KEYWORDS: List[str] = [
    "Microsoft Visual C++",
    ".NET Runtime",
    "Microsoft .NET",
    "Microsoft Edge",
    "Windows Defender",
    "Cortana",
    "Microsoft Store",
    "Windows Security",
    "Windows Update",
    "Realtek Audio",
    "Intel(R) Processor",
    "NVIDIA Graphics Driver",
    "AMD Software",
    "Microsoft Office",
    "Microsoft OneDrive",
]

# ============ 风险等级 ============
RISK_SAFE = "safe"           # 可安全清理
RISK_MODERATE = "moderate"   # 中等风险，默认勾选但给出提示
RISK_RISKY = "risky"         # 高风险，默认不勾选

# ============ 卸载方式 ============
UNINSTALL_METHOD_STANDARD = "standard"
UNINSTALL_METHOD_QUIET = "quiet"
UNINSTALL_METHOD_FORCE = "force"

# ============ 搬家链接类型 ============
LINK_TYPE_JUNCTION = "junction"
LINK_TYPE_SYMLINK = "symlink"

# ============ 默认设置 ============
DEFAULT_SETTINGS = {
    "use_recycle_bin": True,         # 清理默认走回收站
    "min_file_age_days": 1,          # 跳过 N 天内文件（0=跳过24h内，1=跳过1天内）
    "min_file_age_hours": 24,        # 与上者配合：精确到小时
    "show_risky_items": False,       # 默认不显示高风险项
    "theme": "auto",          # auto / light / dark
    "link_type": LINK_TYPE_JUNCTION,
    "scan_threads": 4,
    "confirm_dangerous": True,
}

# ============ 提示常量 ============
ONE_DAY_SECONDS = 86400
ONE_HOUR_SECONDS = 3600

# 程序执行超时（卸载进程）
UNINSTALL_TIMEOUT_SECONDS = 600  # 10 分钟
COPY_PROGRESS_TICK_BYTES = 32 * 1024 * 1024  # 32 MB 触发一次进度回调

# 校验抽样比例（每 N 个文件抽样 1 个做 SHA-256）
VERIFY_SAMPLE_RATE = 100