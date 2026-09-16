"""
管理员权限检测与提升。
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Optional

from app.common.logger import get_logger

logger = get_logger("admin")


def is_admin() -> bool:
    """检查当前进程是否拥有管理员权限。"""
    if sys.platform != "win32":
        return True  # 非 Windows 视为管理员（开发环境）
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin(script: Optional[str] = None, args: Optional[list] = None) -> bool:
    """以管理员权限重新启动当前脚本。

    :param script: 要启动的脚本（None 则重新启动当前解释器 + main）
    :param args: 额外参数
    :return: 已发出重启请求返回 True
    """
    if is_admin():
        return True
    if sys.platform != "win32":
        return False

    try:
        params = " ".join([f'"{a}"' for a in (args or [])])
        if script:
            target = f'"{script}" {params}'.strip()
        else:
            # 重新启动当前 python + main.py
            target = f'"{sys.executable}" "{sys.argv[0]}" {params}'.strip()

        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, target, None, 1
        )
        return int(ret) > 32
    except Exception as e:
        logger.error(f"提升管理员权限失败: {e}")
        return False


def relaunch_as_admin() -> None:
    """退出当前进程，以管理员权限重新启动 main.py。"""
    if is_admin() or sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{sys.argv[0]}"', None, 1
        )
    except Exception as e:
        logger.error(f"重启失败: {e}")
    finally:
        sys.exit(0)


def get_admin_username() -> str:
    """获取当前管理员用户名（用于 UI 显示）。"""
    if sys.platform != "win32":
        return "developer"
    try:
        import os
        return os.getlogin()
    except OSError:
        return "Unknown"