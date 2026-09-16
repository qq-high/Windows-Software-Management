"""
软件卸载服务：
  - 枚举已安装程序（注册表 HKLM/HKCU + Windows Store AppX）
  - 标准卸载（解析 UninstallString）
  - 静默卸载（QuietUninstallString）
  - 残留扫描（BHUninstaller 风格：保守匹配 publisher/app name）
  - 强制卸载（按关键字匹配）
"""
from __future__ import annotations

import os
import re
import shutil
import string
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from send2trash import send2trash

from app.common.logger import get_logger, log_operation
from app.common.paths import expand_env_vars, is_protected
from app.config import (
    PROTECTED_PATH_PATTERNS,
    SYSTEM_PROTECTED_KEYWORDS,
    UNINSTALL_TIMEOUT_SECONDS,
)
from app.models.installed_app import (
    InstalledApp,
    LeftoverItem,
    LeftoverScanResult,
    UninstallResult,
)

logger = get_logger("uninstaller")


# ============== 注册表枚举 ==============

_UNINSTALL_KEYS = [
    (r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM"),
    (r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM (32位)"),
    (r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "HKCU"),
]


def _query_registry(key_path: str) -> List[Dict]:
    """通过 cmd reg query 查询注册表项（避免 pywin32 依赖复杂性）。

    返回 [{name, value, ...}, ...] 列表。
    """
    if os.name != "nt":
        return []
    try:
        # 先列出子项
        out = subprocess.run(
            ["reg", "query", key_path, "/s", "/reg:64"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if out.returncode != 0:
            return []

        entries: List[Dict] = []
        current: Optional[Dict] = None
        current_subkey = ""

        for line in out.stdout.splitlines():
            line = line.rstrip()
            if not line:
                continue
            # 子项头：HKEY_...\\Uninstall\\{GUID}
            if line.startswith("HKEY_") or line.startswith("\\"):
                # 新子项开始
                if current:
                    entries.append(current)
                current = {}
                current_subkey = line.strip()
                current["__subkey__"] = line.strip()
            elif current is not None and "    " in line:
                parts = line.strip().split("    ", 1)
                if len(parts) == 2:
                    name, value = parts
                    name = name.strip()
                    value = value.strip()
                    if name == "(默认)":
                        current.setdefault("DisplayName", value)
                    else:
                        current[name] = value
        if current:
            entries.append(current)
        return entries
    except subprocess.TimeoutExpired:
        logger.warning(f"注册表查询超时: {key_path}")
        return []
    except Exception as e:
        logger.debug(f"注册表查询失败 {key_path}: {e}")
        return []


def _enforce_system_app(name: str) -> bool:
    """检查是否包含系统关键关键字。"""
    if not name:
        return False
    lower = name.lower()
    for kw in SYSTEM_PROTECTED_KEYWORDS:
        if kw.lower() in lower:
            return True
    return False


def _parse_install_date(date_str: str) -> str:
    """解析 InstallDate 字段（YYYYMMDD） -> YYYY-MM-DD。"""
    if not date_str or len(date_str) != 8:
        return ""
    try:
        return f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"
    except Exception:
        return ""


def _to_installed_app(entry: Dict, source: str) -> Optional[InstalledApp]:
    """将注册表条目转为 InstalledApp。"""
    name = entry.get("DisplayName") or entry.get("(默认)") or ""
    if not name or name.startswith("$") or "Microsoft Visual Studio" in name:
        # 跳过补丁/语言包等无主入口的项
        pass
    if not name or name.startswith("KB") and len(name) <= 12:
        return None  # 跳过 KB 更新
    uninstall = entry.get("UninstallString") or ""
    if not uninstall:
        return None
    subkey = entry.get("__subkey__", "")
    app_id = subkey if subkey else f"{name}|{source}"

    install_loc = entry.get("InstallLocation") or ""
    publisher = entry.get("Publisher") or ""
    version = entry.get("DisplayVersion") or ""

    # 大小（KB）
    estimated_kb = 0
    for k in ("EstimatedSize", "Size"):
        v = entry.get(k, "")
        try:
            estimated_kb = int(str(v).replace(",", "").strip() or 0)
            break
        except (ValueError, TypeError):
            continue

    install_date = _parse_install_date(entry.get("InstallDate", ""))

    # 判断 MSI
    app_type = "exe"
    if uninstall.lower().find("msiexec") >= 0 or "{" in uninstall:
        # 可能是 MSI GUID 卸载
        app_type = "msi"

    is_system = _enforce_system_app(name) or _enforce_system_app(publisher)

    return InstalledApp(
        id=app_id,
        name=name.strip(),
        publisher=publisher.strip(),
        version=version.strip(),
        install_date=install_date,
        install_location=install_loc.strip(),
        estimated_size=estimated_kb * 1024,
        uninstall_cmd=uninstall.strip(),
        quiet_uninstall_cmd=entry.get("QuietUninstallString", "").strip(),
        uninstall_string_raw=uninstall.strip(),
        app_type=app_type,
        source=source,
        is_system=is_system,
        icon_path=entry.get("DisplayIcon", "").strip(),
    )


# ============== AppX 枚举 ==============

def _enumerate_appx() -> List[InstalledApp]:
    """通过 PowerShell Get-AppxPackage 枚举已安装 AppX/UWP 应用。"""
    if os.name != "nt":
        return []
    try:
        ps_cmd = (
            "Get-AppxPackage -AllUsers | "
            "Select-Object Name, Publisher, Version, InstallLocation, PackageFullName, Architecture | "
            "ConvertTo-Csv -NoTypeInformation"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if out.returncode != 0:
            logger.debug(f"AppX 查询失败: {out.stderr[:200]}")
            return []

        apps: List[InstalledApp] = []
        lines = out.stdout.strip().split("\n")
        if len(lines) < 2:
            return apps
        headers = [h.strip('"') for h in lines[0].split(",")]
        for line in lines[1:]:
            # 简单 CSV 解析（依赖 PowerShell 默认 quoting）
            import csv
            from io import StringIO
            try:
                reader = csv.DictReader(StringIO(line), fieldnames=headers)
                row = next(reader)
            except Exception:
                continue

            name = row.get("Name", "").strip()
            pkg_full = row.get("PackageFullName", "").strip()
            if not name or not pkg_full:
                continue
            publisher = row.get("Publisher", "").strip()
            version = row.get("Version", "").strip()
            install_loc = row.get("InstallLocation", "").strip()
            publisher_name = _parse_publisher_name(publisher)

            apps.append(InstalledApp(
                id=pkg_full,
                name=_friendly_appx_name(name),
                publisher=publisher_name,
                version=version,
                install_location=install_loc,
                uninstall_cmd="",  # 通过 PackageFullName 卸载
                app_type="appx",
                source="AppX",
                is_system=_enforce_system_app(publisher_name) or _is_system_appx(name),
                is_movable=False,  # AppX 不能用 Junction 搬
            ))
        return apps
    except subprocess.TimeoutExpired:
        logger.warning("AppX 枚举超时")
        return []
    except Exception as e:
        logger.warning(f"AppX 枚举失败: {e}")
        return []


def _parse_publisher_name(publisher: str) -> str:
    """解析 Publisher 字段：CN=... -> Microsoft Corporation。"""
    if not publisher:
        return ""
    # 类似 "CN=Microsoft Corporation, O=Microsoft Corporation, ..."
    match = re.search(r"CN=([^,]+)", publisher)
    if match:
        return match.group(1).strip()
    return publisher


def _friendly_appx_name(name: str) -> str:
    """AppX 名字美化：Microsoft.ScreenSketch -> ScreenSketch。"""
    if not name:
        return name
    parts = name.split(".")
    if len(parts) > 1:
        # 取最后非数字部分
        for p in reversed(parts):
            if p and not p[0].isdigit():
                return p
    return name


def _is_system_appx(name: str) -> bool:
    """检查 AppX 是否为系统关键应用。"""
    system_appx = [
        "Microsoft.Windows", "Microsoft.UI", "Microsoft.Services",
        "Microsoft.NET", "Microsoft.VCLibs", "Microsoft.NET.Native",
        "Microsoft.WindowsStore", "Windows.Print", "Windows.CBSPush",
        "Microsoft.ScreenSketch", "Microsoft.MicrosoftEdge",
        "Microsoft.WindowsSoundRecorder", "Microsoft.GetHelp",
        "Microsoft.MicrosoftOfficeHub", "Microsoft.People",
        "Microsoft.WindowsCamera", "Microsoft.WindowsMaps",
        "Microsoft.YourPhone", "Microsoft.Xbox", "Microsoft.Zune",
    ]
    for kw in system_appx:
        if name.lower().startswith(kw.lower()):
            return True
    return False


# ============== 实际占用扫描 ==============

def _calc_actual_size(install_loc: str) -> int:
    """扫描 install_location 下的实际占用。"""
    if not install_loc:
        return 0
    p = Path(install_loc)
    if not p.exists():
        return 0
    total = 0
    try:
        # 仅统计顶层（避免对大程序递归过久）
        for entry in p.iterdir():
            try:
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    # 深度限制
                    depth = 0
                    for root, dirs, files in os.walk(str(entry)):
                        rel = Path(root).relative_to(entry)
                        depth = len(rel.parts)
                        if depth > 4:
                            dirs.clear()
                            continue
                        for f in files:
                            try:
                                total += (Path(root) / f).stat().st_size
                            except OSError:
                                continue
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        pass
    return total


# ============== 主类 ==============

class UninstallerService:
    """软件卸载服务。"""

    def __init__(self):
        self._cache: Optional[List[InstalledApp]] = None

    def list_installed(self, include_appx: bool = True) -> List[InstalledApp]:
        """列出所有已安装程序。

        1. 查询注册表 3 个 Uninstall key
        2. 枚举 AppX（异步）
        3. 计算每个程序的 actual_size
        """
        apps: List[InstalledApp] = []

        # 注册表
        for key_path, source in _UNINSTALL_KEYS:
            entries = _query_registry(key_path)
            for entry in entries:
                try:
                    app = _to_installed_app(entry, source)
                    if app:
                        apps.append(app)
                except Exception as e:
                    logger.debug(f"解析条目失败: {e}")

        # AppX
        if include_appx:
            appx = _enumerate_appx()
            apps.extend(appx)

        # 实际占用（异步计算，这里同步以简化）
        for app in apps:
            if app.install_location:
                app.actual_size = _calc_actual_size(app.install_location)

        # 去重（按 name）
        seen = set()
        unique: List[InstalledApp] = []
        for app in apps:
            key = app.name.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(app)

        unique.sort(key=lambda a: (a.is_system, a.actual_size <= 0, -a.actual_size, a.name.lower()))
        self._cache = unique
        return unique

    def uninstall(self, app: InstalledApp, progress_cb=None) -> UninstallResult:
        """执行卸载。"""
        log_operation("卸载", f"开始卸载 {app.name} ({app.app_type})")

        if app.is_system:
            return UninstallResult(success=False, message=f"系统关键程序，禁止卸载")

        if app.app_type == "appx":
            return self._uninstall_appx(app)
        elif app.app_type == "msi":
            return self._uninstall_msi(app)
        else:
            return self._uninstall_exe(app)

    def _uninstall_exe(self, app: InstalledApp) -> UninstallResult:
        """通过 UninstallString 卸载。"""
        cmd = app.uninstall_cmd
        if not cmd:
            return UninstallResult(success=False, message="无卸载命令")

        try:
            # 注册表 UninstallString 通常带引号或 /x {GUID}，需解析
            if cmd.startswith('"') and cmd.count('"') >= 2:
                # "C:\path\uninst.exe" /arg
                end = cmd.index('"', 1)
                exe = cmd[1:end]
                args = cmd[end + 1:].strip()
            else:
                # 无引号：空格分隔
                parts = cmd.split(" ", 1)
                exe = parts[0]
                args = parts[1] if len(parts) > 1 else ""

            # 替换环境变量
            exe = expand_env_vars(exe)
            args = expand_env_vars(args)

            if not Path(exe).exists():
                # 试一下 raw 路径
                if Path(cmd.split()[0]).exists():
                    exe = cmd.split()[0]
                else:
                    return UninstallResult(
                        success=False,
                        message=f"卸载器不存在: {exe}\n请尝试手动卸载或使用强制卸载",
                    )

            cmdline = f'"{exe}" {args}'.strip()
            logger.info(f"启动卸载: {cmdline}")
            proc = subprocess.Popen(
                cmdline,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                stdout, stderr = proc.communicate(timeout=UNINSTALL_TIMEOUT_SECONDS)
                return UninstallResult(
                    success=proc.returncode == 0,
                    exit_code=proc.returncode,
                    stdout=stdout.decode("utf-8", errors="ignore")[:2000],
                    stderr=stderr.decode("utf-8", errors="ignore")[:2000],
                    message="卸载完成" if proc.returncode == 0 else f"退出码 {proc.returncode}",
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                return UninstallResult(
                    success=False,
                    message=f"卸载超时（{UNINSTALL_TIMEOUT_SECONDS // 60} 分钟）",
                    cancelled=True,
                )
        except Exception as e:
            return UninstallResult(success=False, message=f"启动卸载失败: {e}")

    def _uninstall_msi(self, app: InstalledApp) -> UninstallResult:
        """通过 msiexec 卸载。"""
        # 提取 GUID
        guid_match = re.search(r"\{[0-9A-Fa-f-]{36}\}", app.uninstall_cmd + " " + app.install_location)
        if not guid_match:
            return self._uninstall_exe(app)

        guid = guid_match.group(0)
        try:
            proc = subprocess.run(
                ["msiexec", "/x", guid, "/qn", "/norestart"],
                capture_output=True, text=True,
                timeout=UNINSTALL_TIMEOUT_SECONDS,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return UninstallResult(
                success=proc.returncode == 0,
                exit_code=proc.returncode,
                stdout=proc.stdout[:2000],
                stderr=proc.stderr[:2000],
                message="MSI 卸载完成" if proc.returncode == 0 else f"退出码 {proc.returncode}",
            )
        except subprocess.TimeoutExpired:
            return UninstallResult(success=False, message="MSI 卸载超时", cancelled=True)
        except Exception as e:
            return UninstallResult(success=False, message=f"MSI 卸载失败: {e}")

    def _uninstall_appx(self, app: InstalledApp) -> UninstallResult:
        """通过 PowerShell 卸载 AppX。"""
        if not app.id:
            return UninstallResult(success=False, message="AppX 无 PackageFullName")
        try:
            ps_cmd = f"Remove-AppxPackage -Package '{app.id}'"
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=300,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return UninstallResult(
                success=proc.returncode == 0,
                exit_code=proc.returncode,
                stdout=proc.stdout[:1000],
                stderr=proc.stderr[:1000],
                message="AppX 卸载完成" if proc.returncode == 0 else f"退出码 {proc.returncode}",
            )
        except subprocess.TimeoutExpired:
            return UninstallResult(success=False, message="AppX 卸载超时", cancelled=True)
        except Exception as e:
            return UninstallResult(success=False, message=f"AppX 卸载失败: {e}")

    def force_uninstall(self, keyword: str) -> List[InstalledApp]:
        """按关键字反查匹配项（用于用户手动输入应用名找不到时）。

        在已加载缓存中模糊匹配 name / publisher / install_location。
        """
        if not self._cache:
            self.list_installed()
        if not keyword or not self._cache:
            return []
        kw = keyword.lower()
        result: List[InstalledApp] = []
        for app in self._cache:
            if (kw in app.name.lower() or
                    kw in app.publisher.lower() or
                    (app.install_location and kw in app.install_location.lower())):
                result.append(app)
        return result

    def scan_leftovers(self, app: InstalledApp) -> LeftoverScanResult:
        """扫描残留：基于 publisher + 应用名的目录、注册表项、快捷方式。"""
        result = LeftoverScanResult()

        if not app.name:
            return result

        # 构建关键字（精确与模糊）
        keywords = self._build_leftover_keywords(app)

        # 1. AppData / LocalAppData / ProgramData 中可能的残留目录
        appdata_roots = []
        for env_var in ("APPDATA", "LOCALAPPDATA", "PROGRAMDATA"):
            v = os.environ.get(env_var)
            if v:
                appdata_roots.append(Path(v))
        # 用户主目录
        appdata_roots.append(Path.home())

        for root in appdata_roots:
            if not root.exists():
                continue
            try:
                for entry in root.iterdir():
                    if not entry.is_dir():
                        continue
                    name_lower = entry.name.lower()
                    for kw in keywords:
                        if kw.lower() in name_lower:
                            try:
                                size = sum(
                                    f.stat().st_size
                                    for f in entry.rglob("*")
                                    if f.is_file() and not f.is_junction()
                                ) if entry.is_dir() else 0
                            except (OSError, PermissionError):
                                size = 0
                            result.items.append(LeftoverItem(
                                app_id=app.id,
                                path=str(entry),
                                item_type="directory",
                                size_bytes=size,
                                description=f"残留目录: {entry.name}",
                                risk="moderate",
                            ))
                            break
            except (PermissionError, OSError):
                continue

        # 2. 开始菜单孤立快捷方式
        start_menu_dirs = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        for sm in start_menu_dirs:
            if not sm.exists():
                continue
            try:
                for lnk in sm.rglob("*.lnk"):
                    name_lower = lnk.stem.lower()
                    for kw in keywords:
                        if kw.lower() in name_lower:
                            result.items.append(LeftoverItem(
                                app_id=app.id,
                                path=str(lnk),
                                item_type="shortcut",
                                size_bytes=lnk.stat().st_size if lnk.exists() else 0,
                                description=f"开始菜单快捷方式: {lnk.name}",
                                risk="safe",
                            ))
                            break
            except (PermissionError, OSError):
                continue

        # 3. 注册表残留（HKCU + HKLM 下以 publisher / app name 命名的项）
        for key_path, hive in [
            (r"HKCU\SOFTWARE", "HKCU"),
            (r"HKLM\SOFTWARE", "HKLM"),
        ]:
            entries = _query_registry(key_path)
            for entry in entries:
                subkey = entry.get("__subkey__", "")
                if not subkey:
                    continue
                subkey_lower = subkey.lower()
                for kw in keywords:
                    if kw.lower() in subkey_lower:
                        # 必须包含 publisher 或 app name（精确匹配）
                        if kw.lower() not in app.name.lower() and kw.lower() not in app.publisher.lower():
                            continue
                        result.items.append(LeftoverItem(
                            app_id=app.id,
                            path=subkey,
                            item_type="registry_key",
                            size_bytes=0,
                            description=f"注册表项: {subkey.split('\\')[-1]}",
                            risk="moderate",
                        ))
                        break

        result.total_size = sum(item.size_bytes for item in result.items)
        logger.info(f"残留扫描 [{app.name}]: {len(result.items)} 项, {result.total_size / (1024*1024):.1f} MB")
        return result

    def _build_leftover_keywords(self, app: InstalledApp) -> List[str]:
        """构造残留扫描的关键字列表。"""
        kws: List[str] = []
        # 完整 name
        if app.name:
            kws.append(app.name.strip())
            # 拆词
            for word in re.split(r"[\s\-_]+", app.name):
                if len(word) >= 3:
                    kws.append(word)
        # publisher 短名
        if app.publisher:
            kws.append(app.publisher.strip())
            for word in re.split(r"[\s\-_]+", app.publisher):
                if len(word) >= 4:
                    kws.append(word)
        # 从 install_location 提取目录名
        if app.install_location:
            try:
                p = Path(app.install_location)
                if p.name:
                    kws.append(p.name)
            except Exception:
                pass
        return list(set(kws))

    def remove_leftovers(
        self,
        items: List[LeftoverItem],
        use_recycle_bin: bool = True,
        progress_cb=None,
    ) -> UninstallResult:
        """删除残留项。"""
        deleted = 0
        failed = 0
        errors = []
        total = len(items)
        for i, item in enumerate(items):
            if progress_cb:
                progress_cb(int(i / max(total, 1) * 100), Path(item.path).name)
            try:
                if is_protected(item.path, PROTECTED_PATH_PATTERNS):
                    failed += 1
                    errors.append(f"受保护: {item.path}")
                    continue
                p = Path(item.path)
                if not p.exists() and item.item_type != "registry_key":
                    continue
                if item.item_type == "registry_key":
                    # 删除注册表项
                    try:
                        out = subprocess.run(
                            ["reg", "delete", item.path, "/f"],
                            capture_output=True, text=True, timeout=10,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        if out.returncode == 0:
                            deleted += 1
                        else:
                            failed += 1
                            errors.append(f"注册表: {item.path}")
                    except Exception as e:
                        failed += 1
                        errors.append(f"{item.path}: {e}")
                else:
                    if use_recycle_bin:
                        try:
                            send2trash(item.path)
                            deleted += 1
                        except Exception:
                            # 回退永久删除
                            try:
                                if p.is_dir():
                                    shutil.rmtree(str(p), ignore_errors=True)
                                else:
                                    os.remove(str(p))
                                deleted += 1
                            except Exception as e:
                                failed += 1
                                errors.append(f"{item.path}: {e}")
                    else:
                        try:
                            if p.is_dir():
                                shutil.rmtree(str(p), ignore_errors=True)
                            else:
                                os.remove(str(p))
                            deleted += 1
                        except Exception as e:
                            failed += 1
                            errors.append(f"{item.path}: {e}")
            except Exception as e:
                failed += 1
                errors.append(f"{item.path}: {e}")

        log_operation("残留清理", f"应用 {items[0].app_id if items else '?'}: 成功 {deleted}, 失败 {failed}")
        return UninstallResult(
            success=failed == 0,
            message=f"删除 {deleted} 项, 失败 {failed}",
            errors=errors,
        )