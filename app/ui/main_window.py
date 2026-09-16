"""
主窗口：Fluent Window + NavigationInterface + 5 个子页面。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

from qfluentwidgets import (
    FluentWindow,
    FluentIcon as FIF,
    NavigationItemPosition,
)

from app.common.logger import get_logger
from app.config import APP_NAME, APP_VERSION
from app.ui.pages.about_page import AboutPage
from app.ui.pages.cleaner_page import CleanerPage
from app.ui.pages.home_page import HomePage
from app.ui.pages.mover_page import MoverPage
from app.ui.pages.uninstaller_page import UninstallerPage

logger = get_logger("main_window")


class MainWindow(FluentWindow):
    """主窗口：Fluent 风格的侧边栏导航。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1280, 820)

        # 创建子页面
        self.home_page = HomePage(self)
        self.cleaner_page = CleanerPage(self)
        self.uninstaller_page = UninstallerPage(self)
        self.mover_page = MoverPage(self)
        self.about_page = AboutPage(self)

        # 添加到导航
        self.addSubInterface(self.home_page, FIF.HOME, "主页")

        self.navigationInterface.addSeparator()
        self.addSubInterface(
            self.cleaner_page, FIF.BROOM,
            "C 盘清理",
            position=NavigationItemPosition.SCROLL,
        )
        self.addSubInterface(
            self.uninstaller_page, FIF.REMOVE,
            "软件卸载",
            position=NavigationItemPosition.SCROLL,
        )
        self.addSubInterface(
            self.mover_page, FIF.MOVE,
            "软件搬家",
            position=NavigationItemPosition.SCROLL,
        )

        self.navigationInterface.addSeparator()
        self.addSubInterface(
            self.about_page, FIF.INFO,
            "关于",
            position=NavigationItemPosition.BOTTOM,
        )

        # 默认导航到主页
        self.stackedWidget.setCurrentWidget(self.home_page)
        self.navigationInterface.setCurrentItem(self.home_page.objectName())

    def closeEvent(self, event):
        """关闭时清理资源。"""
        # 取消所有正在运行的 Worker
        try:
            self.cleaner_page.cancel_running()
        except Exception:
            pass
        try:
            self.uninstaller_page.cancel_running()
        except Exception:
            pass
        try:
            self.mover_page.cancel_running()
        except Exception:
            pass
        super().closeEvent(event)