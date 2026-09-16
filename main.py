"""
应用入口。

启动流程：
  1. 初始化日志
  2. 检查管理员权限（非管理员则重启）
  3. 创建 QApplication
  4. 设置高 DPI
  5. 显示主窗口
"""
from __future__ import annotations

import sys
import os

# 让 PyInstaller 打包后也能正确 import
if getattr(sys, "frozen", False):
    sys.path.insert(0, sys._MEIPASS)

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.common.admin import is_admin, relaunch_as_admin
from app.common.logger import get_logger, setup_logging
from app.config import APP_NAME, APP_VERSION
from app.ui.main_window import MainWindow


def main():
    # 1. 初始化日志
    logger = setup_logging()
    logger.info(f"===== {APP_NAME} v{APP_VERSION} 启动 =====")

    # 2. 检查管理员权限（非开发模式自动重启）
    if sys.platform == "win32" and not is_admin():
        logger.warning("当前未以管理员身份运行，尝试以管理员重启...")
        relaunch_as_admin()
        return 0  # 已发出重启请求，退出当前进程

    # 3. 高 DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 4. 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("WinOptimizer")

    # 设置默认字体（中文）
    if sys.platform == "win32":
        font = QFont("Microsoft YaHei UI", 10)
    else:
        font = QFont()
        font.setPointSize(10)
    app.setFont(font)

    # 5. 创建主窗口
    window = MainWindow()
    window.show()

    logger.info("主窗口已显示，进入事件循环")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())