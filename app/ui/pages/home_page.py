"""
主页：仪表盘 - 磁盘使用、推荐操作、最近日志。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QProgressBar, QPushButton, QSizePolicy, QSpacerItem,
)

from qfluentwidgets import (
    ScrollArea, TitleLabel, SubtitleLabel, BodyLabel,
    FluentIcon as FIF, PrimaryPushButton, PushButton, CardWidget,
    IconWidget, StrongBodyLabel,
)

from app.common.admin import get_admin_username, is_admin
from app.common.logger import get_logger
from app.common.size_fmt import format_size_chinese
from app.config import APP_NAME, APP_VERSION, LOG_FILE
from app.services.disk_usage import get_c_drive_info, list_drives
from app.services.uninstaller import UninstallerService

logger = get_logger("home_page")


class _DriveStatWorker(QThread):
    """后台获取 C 盘容量与已安装程序数。"""
    finished_signal = Signal(dict)

    def run(self):
        info = get_c_drive_info()
        # 已安装程序数量（仅注册表部分，快速）
        try:
            svc = UninstallerService()
            apps = svc.list_installed(include_appx=False)
            app_count = len(apps)
        except Exception:
            app_count = 0

        # 估算可清理空间：扫描临时目录
        import os
        temp = os.environ.get("TEMP", "")
        cleanable = 0
        if temp and Path(temp).exists():
            try:
                for f in Path(temp).rglob("*"):
                    try:
                        if f.is_file() and not f.is_junction():
                            cleanable += f.stat().st_size
                    except (OSError, PermissionError):
                        continue
            except (OSError, PermissionError):
                pass

        self.finished_signal.emit({
            "drive_info": info,
            "app_count": app_count,
            "cleanable_estimate": cleanable,
        })


class _StatCard(CardWidget):
    """统计卡片：图标 + 数字 + 标签。"""

    def __init__(self, icon, title: str, value: str = "—", suffix: str = "", parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        # 图标 + 标题
        top = QHBoxLayout()
        top.setSpacing(10)
        self.icon_widget = IconWidget(icon)
        self.icon_widget.setFixedSize(28, 28)
        top.addWidget(self.icon_widget)
        title_label = SubtitleLabel(title)
        title_label.setStyleSheet("color: #888;")
        top.addWidget(title_label)
        top.addStretch()
        layout.addLayout(top)

        # 数值
        self.value_label = TitleLabel(value)
        self.value_label.setStyleSheet("font-size: 32px; font-weight: 600;")
        layout.addWidget(self.value_label)

        if suffix:
            self.suffix_label = BodyLabel(suffix)
            self.suffix_label.setStyleSheet("color: #888;")
            layout.addWidget(self.suffix_label)

        layout.addStretch()

    def set_value(self, value: str, suffix: str = ""):
        self.value_label.setText(value)
        if suffix and hasattr(self, "suffix_label"):
            self.suffix_label.setText(suffix)


class HomePage(QWidget):
    """主页 - 仪表盘。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")
        self._worker = None

        # 滚动容器
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(30, 30, 30, 30)
        self._layout.setSpacing(20)

        # 标题
        title = TitleLabel(f"欢迎使用 {APP_NAME}")
        self._layout.addWidget(title)
        subtitle = BodyLabel(
            f"v{APP_VERSION} · 当前用户: {get_admin_username()} · "
            f"{'✓ 管理员模式' if is_admin() else '⚠ 普通模式'}"
        )
        subtitle.setStyleSheet("color: #888;")
        self._layout.addWidget(subtitle)

        # 状态卡片
        self._layout.addSpacing(10)
        cards_row = QHBoxLayout()
        cards_row.setSpacing(15)
        self.drive_card = _StatCard(FIF.FOLDER, "C 盘容量", "加载中...", "")
        self.cleanable_card = _StatCard(FIF.BROOM, "临时文件估算", "加载中...", "")
        self.app_card = _StatCard(FIF.APPLICATION, "已安装程序", "加载中...", "仅扫描注册表")
        cards_row.addWidget(self.drive_card, 1)
        cards_row.addWidget(self.cleanable_card, 1)
        cards_row.addWidget(self.app_card, 1)
        self._layout.addLayout(cards_row)

        # 快速操作
        self._layout.addSpacing(10)
        self._layout.addWidget(StrongBodyLabel("快速操作"))
        actions_row = QHBoxLayout()
        actions_row.setSpacing(15)

        self.btn_clean = PrimaryPushButton(FIF.BROOM, "扫描 C 盘")
        self.btn_clean.setFixedHeight(60)
        self.btn_clean.clicked.connect(self._on_clean_clicked)
        actions_row.addWidget(self.btn_clean)

        self.btn_uninstall = PrimaryPushButton(FIF.REMOVE, "查看已安装程序")
        self.btn_uninstall.setFixedHeight(60)
        self.btn_uninstall.clicked.connect(self._on_uninstall_clicked)
        actions_row.addWidget(self.btn_uninstall)

        self.btn_move = PrimaryPushButton(FIF.MOVE, "软件搬家")
        self.btn_move.setFixedHeight(60)
        self.btn_move.clicked.connect(self._on_move_clicked)
        actions_row.addWidget(self.btn_move)

        self._layout.addLayout(actions_row)

        # 使用提示
        self._layout.addSpacing(10)
        self._layout.addWidget(StrongBodyLabel("安全提示"))
        tip_card = CardWidget()
        tip_layout = QVBoxLayout(tip_card)
        tip_layout.setContentsMargins(20, 16, 20, 16)
        tip_layout.setSpacing(6)
        tips = [
            "• 清理默认走回收站，可随时还原",
            "• 卸载前请关闭正在运行的程序，避免卸载失败",
            "• 搬家使用 NTFS 符号链接，对应用完全透明",
            "• 所有操作均记录在日志文件中",
        ]
        for t in tips:
            label = BodyLabel(t)
            label.setStyleSheet("color: #666;")
            tip_layout.addWidget(label)
        self._layout.addWidget(tip_card)

        self._layout.addStretch()

        # 触发加载数据
        self._load_stats()

    def _load_stats(self):
        """触发后台加载统计数据。"""
        if self._worker and self._worker.isRunning():
            return
        self._worker = _DriveStatWorker(self)
        self._worker.finished_signal.connect(self._on_stats_loaded)
        self._worker.start()

    def _on_stats_loaded(self, data: dict):
        info = data["drive_info"]
        if info:
            used = info.get("total", 0) - info.get("free", 0)
            total = info.get("total", 0)
            self.drive_card.set_value(
                format_size_chinese(used),
                f"已用 / {format_size_chinese(total)} 总容量"
            )
        else:
            self.drive_card.set_value("—", "")

        self.cleanable_card.set_value(
            format_size_chinese(data["cleanable_estimate"]),
            "用户 Temp 目录（实际清理会扫描更多位置）"
        )
        self.app_card.set_value(str(data["app_count"]), "仅扫描注册表")

    def _on_clean_clicked(self):
        """跳转到 C 盘清理页。"""
        main = self.window()
        if hasattr(main, "stackedWidget") and hasattr(main, "cleaner_page"):
            main.stackedWidget.setCurrentWidget(main.cleaner_page)
            main.navigationInterface.setCurrentItem(main.cleaner_page.objectName())

    def _on_uninstall_clicked(self):
        main = self.window()
        if hasattr(main, "stackedWidget") and hasattr(main, "uninstaller_page"):
            main.stackedWidget.setCurrentWidget(main.uninstaller_page)
            main.navigationInterface.setCurrentItem(main.uninstaller_page.objectName())

    def _on_move_clicked(self):
        main = self.window()
        if hasattr(main, "stackedWidget") and hasattr(main, "mover_page"):
            main.stackedWidget.setCurrentWidget(main.mover_page)
            main.navigationInterface.setCurrentItem(main.mover_page.objectName())