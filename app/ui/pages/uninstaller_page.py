"""
软件卸载页面：
  - 顶部：搜索框 + 筛选（全部/传统程序/UWP）
  - 中部：已安装程序表格（图标/名称/发布者/版本/大小/安装日期/类型）
  - 右侧详情 + 操作按钮（标准卸载/静默卸载/扫描残留/强制卸载）
  - 卸载/扫描在后台 Worker 中执行
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QHeaderView, QTableWidgetItem,
    QAbstractItemView,
)

from qfluentwidgets import (
    TitleLabel, SubtitleLabel, BodyLabel, StrongBodyLabel,
    PrimaryPushButton, PushButton, FluentIcon as FIF,
    LineEdit, SearchLineEdit, ComboBox,
    TableWidget, MessageBox, InfoBar, InfoBarPosition,
    ProgressRing, ScrollArea, CardWidget,
)

from app.common.logger import get_logger
from app.common.size_fmt import format_size_chinese
from app.models.installed_app import InstalledApp, LeftoverItem, LeftoverScanResult, UninstallResult
from app.services.uninstaller import UninstallerService

logger = get_logger("uninstaller_page")


class _LoadWorker(QThread):
    """后台加载已安装程序列表。"""
    progress = Signal(int, str)
    finished_signal = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._svc = UninstallerService()

    def run(self):
        self.progress.emit(10, "正在枚举已安装程序...")
        apps = self._svc.list_installed(include_appx=True)
        self.progress.emit(100, "加载完成")
        self.finished_signal.emit(apps)


class _UninstallWorker(QThread):
    """后台执行卸载。"""
    progress = Signal(int, str)
    finished_signal = Signal(object)

    def __init__(self, app: InstalledApp, parent=None):
        super().__init__(parent)
        self._app = app
        self._svc = UninstallerService()

    def run(self):
        self.progress.emit(20, f"正在卸载 {self._app.name}...")
        result = self._svc.uninstall(self._app, progress_cb=None)
        self.progress.emit(100, "卸载流程结束")
        self.finished_signal.emit(result)


class _LeftoverWorker(QThread):
    """后台扫描残留。"""
    progress = Signal(int, str)
    finished_signal = Signal(object)

    def __init__(self, app: InstalledApp, parent=None):
        super().__init__(parent)
        self._app = app
        self._svc = UninstallerService()

    def run(self):
        self.progress.emit(30, f"扫描 {self._app.name} 的残留...")
        result = self._svc.scan_leftovers(self._app)
        self.progress.emit(100, "扫描完成")
        self.finished_signal.emit(result)


class _RemoveLeftoverWorker(QThread):
    """清理残留。"""
    progress = Signal(int, str)
    finished_signal = Signal(object)

    def __init__(self, items: List[LeftoverItem], use_recycle_bin: bool, parent=None):
        super().__init__(parent)
        self._items = items
        self._use_recycle_bin = use_recycle_bin
        self._svc = UninstallerService()

    def run(self):
        result = self._svc.remove_leftovers(
            self._items,
            use_recycle_bin=self._use_recycle_bin,
            progress_cb=lambda p, m: self.progress.emit(p, m),
        )
        self.finished_signal.emit(result)


class UninstallerPage(QWidget):
    """软件卸载页面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("uninstallerPage")

        self._all_apps: List[InstalledApp] = []
        self._filtered_apps: List[InstalledApp] = []
        self._selected_app: Optional[InstalledApp] = None
        self._load_worker: Optional[_LoadWorker] = None
        self._uninstall_worker: Optional[_UninstallWorker] = None
        self._leftover_worker: Optional[_LeftoverWorker] = None
        self._remove_worker: Optional[_RemoveLeftoverWorker] = None

        self._build_ui()
        # 默认延迟加载
        self._start_load()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ============== 主区域 ==============
        main_panel = QWidget()
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(12)

        # 头部
        header = QHBoxLayout()
        title = TitleLabel("软件卸载")
        header.addWidget(title)
        header.addStretch()
        self.btn_refresh = PushButton(FIF.SYNC, "刷新列表")
        self.btn_refresh.clicked.connect(self._start_load)
        header.addWidget(self.btn_refresh)
        main_layout.addLayout(header)

        # 进度条 + 状态
        status_row = QHBoxLayout()
        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(24, 24)
        self.progress_ring.setVisible(False)
        self.status_label = BodyLabel("准备就绪")
        self.status_label.setStyleSheet("color: #888;")
        status_row.addWidget(self.progress_ring)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        main_layout.addLayout(status_row)

        # 搜索 + 筛选
        search_row = QHBoxLayout()
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索程序名 / 发布者...")
        self.search_edit.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search_edit, 1)

        self.filter_combo = ComboBox()
        self.filter_combo.addItems(["全部", "传统程序", "UWP 应用", "MSI 程序"])
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        search_row.addWidget(self.filter_combo)
        main_layout.addLayout(search_row)

        # 表格
        self.table = TableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["名称", "发布者", "版本", "大小", "安装日期", "类型"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        # 自适应列宽
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 6):
            header_view.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        self.table.itemSelectionChanged.connect(self._on_app_selected)
        main_layout.addWidget(self.table, 1)

        # ============== 右侧详情面板 ==============
        detail_panel = QWidget()
        detail_panel.setFixedWidth(320)
        detail_panel.setStyleSheet("background-color: rgba(0,0,0,8);")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(16, 24, 16, 16)
        detail_layout.setSpacing(12)

        detail_layout.addWidget(StrongBodyLabel("详情"))

        self.detail_card = CardWidget()
        self.detail_layout_inner = QVBoxLayout(self.detail_card)
        self.detail_layout_inner.setContentsMargins(16, 16, 16, 16)
        self.detail_layout_inner.setSpacing(8)

        self.detail_name = StrongBodyLabel("请选择程序")
        self.detail_name.setWordWrap(True)
        self.detail_layout_inner.addWidget(self.detail_name)

        self.detail_info = BodyLabel("")
        self.detail_info.setWordWrap(True)
        self.detail_info.setStyleSheet("color: #666; font-size: 12px;")
        self.detail_layout_inner.addWidget(self.detail_info)

        detail_layout.addWidget(self.detail_card)

        # 操作按钮
        detail_layout.addSpacing(8)
        detail_layout.addWidget(StrongBodyLabel("操作"))

        self.btn_uninstall = PrimaryPushButton(FIF.REMOVE, "标准卸载")
        self.btn_uninstall.setEnabled(False)
        self.btn_uninstall.clicked.connect(self._on_uninstall_clicked)
        detail_layout.addWidget(self.btn_uninstall)

        self.btn_uninstall_quiet = PushButton("静默卸载")
        self.btn_uninstall_quiet.setEnabled(False)
        self.btn_uninstall_quiet.clicked.connect(self._on_uninstall_quiet_clicked)
        detail_layout.addWidget(self.btn_uninstall_quiet)

        self.btn_scan_leftover = PushButton(FIF.SEARCH, "扫描残留")
        self.btn_scan_leftover.setEnabled(False)
        self.btn_scan_leftover.clicked.connect(self._on_scan_leftover_clicked)
        detail_layout.addWidget(self.btn_scan_leftover)

        self.btn_force_uninstall = PushButton("强制卸载...")
        self.btn_force_uninstall.setEnabled(False)
        self.btn_force_uninstall.clicked.connect(self._on_force_uninstall_clicked)
        detail_layout.addWidget(self.btn_force_uninstall)

        detail_layout.addStretch()

        # 装配
        root.addWidget(main_panel, 1)
        root.addWidget(detail_panel)

    def _start_load(self):
        """启动后台加载。"""
        if self._load_worker and self._load_worker.isRunning():
            return
        self.btn_refresh.setEnabled(False)
        self.progress_ring.setVisible(True)
        self.progress_ring.setValue(0)
        self.status_label.setText("正在枚举已安装程序（首次约需 10-30 秒）...")

        self._load_worker = _LoadWorker(parent=self)
        self._load_worker.progress.connect(self._on_load_progress)
        self._load_worker.finished_signal.connect(self._on_load_finished)
        self._load_worker.start()

    def _on_load_progress(self, percent: int, message: str):
        self.progress_ring.setValue(percent)
        self.status_label.setText(message)

    def _on_load_finished(self, apps: List[InstalledApp]):
        self._all_apps = apps
        self.progress_ring.setVisible(False)
        self.btn_refresh.setEnabled(True)
        self.status_label.setText(f"已加载 {len(apps)} 个程序")
        self._apply_filter()

    def _apply_filter(self):
        """应用搜索 + 筛选。"""
        search = self.search_edit.text().strip().lower()
        type_idx = self.filter_combo.currentIndex()
        type_map = {0: None, 1: ["exe", "msi"], 2: ["appx", "msix"], 3: ["msi"]}

        result = []
        for app in self._all_apps:
            if search and (search not in app.name.lower() and search not in app.publisher.lower()):
                continue
            allowed = type_map.get(type_idx)
            if allowed and app.app_type not in allowed:
                continue
            result.append(app)

        self._filtered_apps = result
        self._render_table()

    def _render_table(self):
        self.table.setRowCount(len(self._filtered_apps))
        for row, app in enumerate(self._filtered_apps):
            # 名称
            name_text = app.name
            if app.is_system:
                name_text = f"🔒 {name_text}"
            self.table.setItem(row, 0, QTableWidgetItem(name_text))
            self.table.setItem(row, 1, QTableWidgetItem(app.publisher or "—"))
            self.table.setItem(row, 2, QTableWidgetItem(app.version or "—"))
            self.table.setItem(row, 3, QTableWidgetItem(app.display_size))
            self.table.setItem(row, 4, QTableWidgetItem(app.install_date or "—"))
            self.table.setItem(row, 5, QTableWidgetItem(app.display_type))
            # 行高
            self.table.setRowHeight(row, 32)
        self.status_label.setText(f"显示 {len(self._filtered_apps)} 个程序（总 {len(self._all_apps)}）")

    def _on_app_selected(self):
        """选中程序时更新详情。"""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._selected_app = None
            self.detail_name.setText("请选择程序")
            self.detail_info.setText("")
            self.btn_uninstall.setEnabled(False)
            self.btn_uninstall_quiet.setEnabled(False)
            self.btn_scan_leftover.setEnabled(False)
            self.btn_force_uninstall.setEnabled(False)
            return
        idx = rows[0].row()
        if idx >= len(self._filtered_apps):
            return
        app = self._filtered_apps[idx]
        self._selected_app = app

        info_lines = [
            f"名称：{app.name}",
            f"发布者：{app.publisher or '—'}",
            f"版本：{app.version or '—'}",
            f"类型：{app.display_type}",
            f"占用：{app.display_size}",
            f"安装日期：{app.install_date or '—'}",
        ]
        if app.install_location:
            info_lines.append(f"安装位置：\n{app.install_location}")
        if app.is_system:
            info_lines.append("\n⚠ 系统关键程序")

        self.detail_name.setText(app.name)
        self.detail_info.setText("\n".join(info_lines))

        # 系统程序不可卸载
        enabled = not app.is_system and bool(app.uninstall_cmd or app.app_type == "appx")
        self.btn_uninstall.setEnabled(enabled)
        self.btn_uninstall_quiet.setEnabled(enabled and bool(app.quiet_uninstall_cmd))
        self.btn_scan_leftover.setEnabled(True)
        self.btn_force_uninstall.setEnabled(bool(app.uninstall_cmd))

    def _on_uninstall_clicked(self):
        """标准卸载。"""
        if not self._selected_app:
            return
        if self._selected_app.is_system:
            InfoBar.error(
                title="无法卸载",
                content="该程序为系统关键组件，强制卸载可能导致系统异常",
                parent=self, duration=3000, position=InfoBarPosition.TOP,
            )
            return
        self._confirm_and_uninstall(self._selected_app, quiet=False)

    def _on_uninstall_quiet_clicked(self):
        """静默卸载。"""
        if not self._selected_app or not self._selected_app.quiet_uninstall_cmd:
            return
        self._confirm_and_uninstall(self._selected_app, quiet=True)

    def _confirm_and_uninstall(self, app: InstalledApp, quiet: bool):
        msg_box = MessageBox(
            f"卸载 {app.name}",
            f"即将卸载：\n{app.name} {app.version}\n\n"
            f"来源：{app.source}\n"
            f"占用：{app.display_size}\n\n"
            "卸载过程中可能弹出该程序自带的卸载窗口。\n"
            "完成后建议扫描残留以彻底清理。\n\n"
            "是否继续？",
            self.window(),
        )
        msg_box.yesButton.setText("开始卸载")
        msg_box.cancelButton.setText("取消")
        if not msg_box.exec():
            return

        # 启动 worker
        if quiet and app.quiet_uninstall_cmd:
            # 用静默命令直接卸载
            self._run_quiet_uninstall(app)
        else:
            self.progress_ring.setVisible(True)
            self.progress_ring.setValue(0)
            self.status_label.setText(f"正在卸载 {app.name}...")
            self._uninstall_worker = _UninstallWorker(app, parent=self)
            self._uninstall_worker.progress.connect(self._on_progress)
            self._uninstall_worker.finished_signal.connect(self._on_uninstall_finished)
            self._uninstall_worker.start()

    def _run_quiet_uninstall(self, app: InstalledApp):
        """用静默命令直接卸载（不通过 worker 的 uninstall 方法）。"""
        import subprocess
        try:
            cmd = app.quiet_uninstall_cmd
            if cmd.startswith('"') and cmd.count('"') >= 2:
                end = cmd.index('"', 1)
                exe = cmd[1:end]
                args = cmd[end + 1:].strip()
            else:
                parts = cmd.split(" ", 1)
                exe = parts[0]
                args = parts[1] if len(parts) > 1 else ""

            from app.common.paths import expand_env_vars
            exe = expand_env_vars(exe)
            cmdline = f'"{exe}" {args}'.strip()
            proc = subprocess.Popen(cmdline, shell=True)
            proc.wait(timeout=300)
            self._on_uninstall_finished(UninstallResult(
                success=proc.returncode == 0,
                exit_code=proc.returncode,
                message="静默卸载完成" if proc.returncode == 0 else f"退出码 {proc.returncode}",
            ))
        except Exception as e:
            self._on_uninstall_finished(UninstallResult(success=False, message=str(e)))

    def _on_uninstall_finished(self, result: UninstallResult):
        self.progress_ring.setVisible(False)
        msg = f"{result.message}\n"
        if result.exit_code is not None and result.exit_code >= 0:
            msg += f"\n退出码：{result.exit_code}"
        if result.cancelled:
            msg += "\n\n提示：可尝试强制卸载（扫描注册表与目录）"

        box = MessageBox("卸载结果", msg, self.window())
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()

        # 询问是否扫描残留
        if self._selected_app and not result.cancelled:
            ask = MessageBox(
                "扫描残留？",
                f"是否扫描「{self._selected_app.name}」的卸载残留？",
                self.window(),
            )
            ask.yesButton.setText("立即扫描")
            ask.cancelButton.setText("暂不")
            if ask.exec():
                self._on_scan_leftover_clicked()

        # 刷新列表
        self._start_load()

    def _on_scan_leftover_clicked(self):
        """扫描残留。"""
        if not self._selected_app:
            return
        self.progress_ring.setVisible(True)
        self.progress_ring.setValue(0)
        self.status_label.setText(f"扫描 {self._selected_app.name} 的残留...")

        self._leftover_worker = _LeftoverWorker(self._selected_app, parent=self)
        self._leftover_worker.progress.connect(self._on_progress)
        self._leftover_worker.finished_signal.connect(self._on_leftover_finished)
        self._leftover_worker.start()

    def _on_leftover_finished(self, result: LeftoverScanResult):
        self.progress_ring.setVisible(False)
        if not result.items:
            InfoBar.success(
                title="扫描完成",
                content=f"未发现 {self._selected_app.name} 的残留文件",
                parent=self, duration=3000, position=InfoBarPosition.TOP,
            )
            return

        # 弹窗：列出残留项并询问是否清理
        msg_lines = [
            f"发现 {len(result.items)} 项残留，共 {format_size_chinese(result.total_size)}：",
            "",
        ]
        # 按类型分组显示
        from collections import defaultdict
        by_type: dict = defaultdict(list)
        for item in result.items:
            by_type[item.item_type].append(item)

        type_label = {
            "directory": "📁 目录",
            "file": "📄 文件",
            "registry_key": "🔑 注册表",
            "shortcut": "🔗 快捷方式",
        }
        for t, items in by_type.items():
            msg_lines.append(f"{type_label.get(t, t)} ({len(items)}):")
            for it in items[:8]:  # 每类最多展示 8 个
                size_str = f" ({format_size_chinese(it.size_bytes)})" if it.size_bytes > 0 else ""
                msg_lines.append(f"  • {it.path}{size_str}")
            if len(items) > 8:
                msg_lines.append(f"  ... 还有 {len(items) - 8} 项")
            msg_lines.append("")

        msg_lines.append("\n是否将这些项进入回收站？")

        msg_box = MessageBox(
            f"残留扫描 - {self._selected_app.name}",
            "\n".join(msg_lines),
            self.window(),
        )
        msg_box.yesButton.setText("清理残留")
        msg_box.cancelButton.setText("取消")
        if not msg_box.exec():
            return

        # 执行清理
        self.progress_ring.setVisible(True)
        self.progress_ring.setValue(0)
        self.status_label.setText("正在清理残留...")
        self._remove_worker = _RemoveLeftoverWorker(
            result.items, use_recycle_bin=True, parent=self,
        )
        self._remove_worker.progress.connect(self._on_progress)
        self._remove_worker.finished_signal.connect(self._on_remove_leftover_finished)
        self._remove_worker.start()

    def _on_remove_leftover_finished(self, result: UninstallResult):
        self.progress_ring.setVisible(False)
        msg = result.message
        if result.errors:
            msg += f"\n\n失败 {len(result.errors)} 项（前 5 条）：\n"
            msg += "\n".join(f"  {e}" for e in result.errors[:5])

        box = MessageBox("清理完成", msg, self.window())
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()

    def _on_force_uninstall_clicked(self):
        """强制卸载（基于强制扫描匹配）。"""
        if not self._selected_app:
            return

        # 二次确认
        box = MessageBox(
            "强制卸载",
            f"强制卸载「{self._selected_app.name}」将尝试：\n"
            "1. 调用程序自身的卸载命令\n"
            "2. 如失败，扫描并清理应用残留\n"
            "3. 删除注册表与 AppData 下的相关项\n\n"
            "⚠ 强制卸载可能误删与此应用关联但仍需使用的配置。\n"
            "建议先备份重要数据。\n\n"
            "是否继续？",
            self.window(),
        )
        box.yesButton.setText("强制卸载")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        # 卸载 + 扫残留
        self.progress_ring.setVisible(True)
        self.progress_ring.setValue(0)
        self.status_label.setText(f"正在强制卸载 {self._selected_app.name}...")
        self._uninstall_worker = _UninstallWorker(self._selected_app, parent=self)
        self._uninstall_worker.progress.connect(self._on_progress)
        # 用 lambda 包装：卸载完成后自动扫描残留
        def on_finished(r):
            self._on_uninstall_finished(r)
        self._uninstall_worker.finished_signal.connect(on_finished)
        self._uninstall_worker.start()

    def _on_progress(self, percent: int, message: str):
        self.progress_ring.setValue(percent)
        self.status_label.setText(message)

    def cancel_running(self):
        for w in (self._load_worker, self._uninstall_worker, self._leftover_worker, self._remove_worker):
            if w and w.isRunning():
                w.quit()
                w.wait(2000)