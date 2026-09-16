"""
路径相关工具：环境变量展开、Windows 已知目录、Junction 检测等。
"""
from __future__ import annotations

import os
import re
import string
from pathlib import Path
from typing import Iterable, List, Optional

# 已知 GUID -> 环境变量
_KNOWN_FOLDERS = {
    "Desktop":            "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Programs":           "{A77F5F77-2E7F-4B0C-A189-6E1AC4E8E4A9}",
    "MyDocuments":        "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "Favorites":          "{1777F761-276AD-411C-B6F1-EB5D5E88C2B9}",
    "StartMenu":          "{A4115719-62B4-4797-B7B7-5BA81D9D9D78}",
    "ProgramsCommon":     "{0139D44E-6AFE-49F2-8690-3DAFCA6FF8A4}",
    "StartMenuCommon":    "{A4115719-62B4-4797-B7B7-5BA81D9D9D78}",
    "AppData":            "{3D644C9B-1FB8-4F30-9B45-F670235F79B0}",
    "LocalAppData":       "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}",
    "Downloads":          "{374DE290-123F-4565-9164-39C4925E467B}",
    "UserProfile":        "{5E6C858F-0E22-4760-9AFE-EA3317B67E3D}",
    "Windows":            "{F38BF404-1D43-42F2-9305-67DE0B66FCFB}",
    "System":             "{1AC14E77-02E7-4E5D-B744-2EB9AE1AA8B1}",
    "ProgramFiles":       "{6D809377-6AF0-444B-8957-A3773F02200E}",
    "ProgramFilesX86":    "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}",
    "ProgramData":        "{62AB5D82-FDC1-4DC3-A9DD-070D1D495D97}",
}


def expand_env_vars(path: str) -> str:
    """展开 Windows 风格的环境变量（如 %TEMP%, %LOCALAPPDATA%）。"""
    if not path:
        return path
    return os.path.expandvars(path)


def expand_path(path: str | Path) -> Optional[Path]:
    """展开环境变量并解析为绝对 Path；不存在则返回 None。"""
    if path is None:
        return None
    try:
        expanded = expand_env_vars(str(path))
        p = Path(expanded).expanduser()
        return p.resolve(strict=False)
    except (OSError, ValueError):
        return None


def get_known_folder(name: str) -> Optional[Path]:
    """通过 SHGetKnownFolderPath 获取 Windows 已知文件夹。

    跨平台退化：如果不是 Windows 或调用失败，返回基于环境变量的估算值。
    """
    if os.name != "nt":
        # 非 Windows：使用环境变量退化
        env_map = {
            "Desktop": "USERPROFILE",
            "UserProfile": "USERPROFILE",
            "AppData": "APPDATA",
            "LocalAppData": "LOCALAPPDATA",
            "Downloads": "USERPROFILE",
            "Windows": "WINDIR",
            "System": "WINDIR",
            "ProgramFiles": "PROGRAMFILES",
            "ProgramFilesX86": "PROGRAMFILES(X86)",
            "ProgramData": "PROGRAMDATA",
            "StartMenu": "APPDATA",
            "ProgramsCommon": "PROGRAMDATA",
            "StartMenuCommon": "PROGRAMDATA",
            "MyDocuments": "USERPROFILE",
        }
        env_name = env_map.get(name)
        if env_name:
            v = os.environ.get(env_name)
            if v:
                return Path(v)
        return None

    guid = _KNOWN_FOLDERS.get(name)
    if not guid:
        return None

    try:
        import ctypes
        from ctypes import wintypes

        FOLDERID = guid
        KF_FLAG_CREATE = 0x00008000  # 不创建
        SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
        SHGetKnownFolderPath.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        SHGetKnownFolderPath.restype = ctypes.HRESULT

        path_ptr = ctypes.c_wchar_p()
        hr = SHGetKnownFolderPath(ctypes.c_wchar_p(FOLDERID), 0, None,
                                  ctypes.byref(path_ptr))
        if hr == 0 and path_ptr.value:
            return Path(path_ptr.value)
        return None
    except Exception:
        # 退化：用环境变量
        env_map = {
            "Desktop": ("USERPROFILE", "Desktop"),
            "MyDocuments": ("USERPROFILE", "Documents"),
            "UserProfile": ("USERPROFILE",),
            "AppData": ("APPDATA",),
            "LocalAppData": ("LOCALAPPDATA",),
            "Downloads": ("USERPROFILE", "Downloads"),
            "Windows": ("WINDIR",),
            "System": ("WINDIR", "System32"),
            "ProgramFiles": ("PROGRAMFILES",),
            "ProgramFilesX86": ("PROGRAMFILES(X86)",),
            "ProgramData": ("PROGRAMDATA",),
            "ProgramsCommon": ("PROGRAMDATA", "Microsoft", "Windows", "Start Menu", "Programs"),
            "StartMenuCommon": ("PROGRAMDATA", "Microsoft", "Windows", "Start Menu"),
            "StartMenu": ("APPDATA", "Microsoft", "Windows", "Start Menu"),
            "Programs": ("APPDATA", "Microsoft", "Windows", "Start Menu", "Programs"),
        }
        parts = env_map.get(name)
        if parts:
            base = os.environ.get(parts[0])
            if base:
                return Path(base).joinpath(*parts[1:]) if len(parts) > 1 else Path(base)
        return None


def is_protected(path: Path | str, patterns: Iterable[str]) -> bool:
    """判断路径是否命中受保护模式。

    命中规则：
    - 路径 resolve 后字符串前缀匹配（忽略大小写）
    - 通配符 * 支持（C:\\Users\\*\\Documents）
    """
    if path is None:
        return False
    try:
        p = Path(path).resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    p_str = str(p).rstrip("\\/")
    if not p_str:
        return False

    p_lower = p_str.lower()
    for pat in patterns:
        pat_lower = pat.lower()
        # 将通配符转为正则
        regex = "^" + re.escape(pat_lower).replace(r"\*", ".*") + "$"
        if re.match(regex, p_lower):
            return True
        # 也兼容前缀匹配（C:\Windows 含 C:\Windows\Temp）
        if "*" not in pat and p_lower.startswith(pat_lower.rstrip("\\/") + "\\"):
            return True
    return False


def safe_join(base: Path, *parts: str) -> Path:
    """安全的路径拼接：防止越出 base。"""
    base_resolved = base.resolve(strict=False)
    target = base_resolved.joinpath(*parts).resolve(strict=False)
    # 检查越界
    try:
        target.relative_to(base_resolved)
    except ValueError:
        raise ValueError(f"路径越界：{target} 不在 {base_resolved} 内") from None
    return target


def is_junction(path: Path) -> bool:
    """判断是否为 NTFS Junction（仅在 Windows 上有效）。"""
    if os.name != "nt":
        return False
    try:
        return bool(path.is_junction()) if hasattr(path, "is_junction") else False
    except (OSError, AttributeError):
        return False


def get_volume_info(drive: str) -> dict:
    """获取指定盘符的文件系统类型与空间信息。"""
    if os.name != "nt":
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        free_bytes = ctypes.c_ulonglong(0)
        total_bytes = ctypes.c_ulonglong(0)
        total_free = ctypes.c_ulonglong(0)

        kernel32 = ctypes.windll.kernel32
        GetDiskFreeSpaceExW = kernel32.GetDiskFreeSpaceExW
        GetDiskFreeSpaceExW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulonglong),
            ctypes.POINTER(ctypes.c_ulonglong),
            ctypes.POINTER(ctypes.c_ulonglong),
        ]
        GetDiskFreeSpaceExW.restype = ctypes.c_bool

        ok = GetDiskFreeSpaceExW(
            str(drive),
            ctypes.byref(free_bytes),
            ctypes.byref(total_bytes),
            ctypes.byref(total_free),
        )
        result = {}
        if ok:
            result["total"] = total_bytes.value
            result["free"] = free_bytes.value

        # 文件系统类型：NTFS / FAT32 / exFAT / ReFS
        try:
            volume_name = ctypes.create_unicode_buffer(261)
            fs_name = ctypes.create_unicode_buffer(261)
            serial = ctypes.c_ulong(0)
            max_comp = ctypes.c_ulong(0)
            fs_flags = ctypes.c_ulong(0)
            GetVolumeInformationW = kernel32.GetVolumeInformationW
            GetVolumeInformationW.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_uint,
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.c_wchar_p,
                ctypes.c_uint,
            ]
            GetVolumeInformationW.restype = ctypes.c_bool
            ok2 = GetVolumeInformationW(
                str(drive), volume_name, 261,
                ctypes.byref(serial),
                ctypes.byref(max_comp),
                ctypes.byref(fs_flags),
                fs_name, 261,
            )
            if ok2:
                result["fs"] = fs_name.value
                result["label"] = volume_name.value
        except Exception:
            pass
        return result
    except Exception:
        return {}


def list_drives() -> List[dict]:
    """列出所有可用盘符及其信息。"""
    drives: List[dict] = []
    if os.name != "nt":
        # 非 Windows：仅返回当前根
        try:
            usage = os.statvfs("/")
            drives.append({
                "drive": "/",
                "label": "Root",
                "fs": "unknown",
                "total": usage.f_blocks * usage.f_frsize,
                "free": usage.f_bavail * usage.f_frsize,
            })
        except OSError:
            pass
        return drives

    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive = f"{letter}:\\"
                try:
                    if os.path.exists(drive):
                        info = get_volume_info(drive)
                        drives.append({
                            "drive": drive,
                            "label": info.get("label", ""),
                            "fs": info.get("fs", "unknown"),
                            "total": info.get("total", 0),
                            "free": info.get("free", 0),
                        })
                except OSError:
                    pass
            bitmask >>= 1
    except Exception:
        pass
    return drives


def windows_to_powershell_path(p: Path) -> str:
    """将 Path 转为 PowerShell 中可用的单引号转义字符串。"""
    s = str(p)
    return s.replace("'", "''")