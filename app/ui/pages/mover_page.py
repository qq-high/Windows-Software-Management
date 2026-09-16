"""
软件搬家页面：
  - 顶部：目标盘选择
  - 主表格：可搬家应用列表（与卸载页面类似）
  - 详情 + 预检 + 搬家按钮
  - 底部：搬家历史表格 + 一键回滚
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QHeaderView, QTableWidgetItem,
    QAbstractItemView, QSizePolicy,
)

from qfluentwidgets import (
    TitleLabel, SubtitleLabel, BodyLabel, StrongBodyLabel,
    PrimaryPushButton, PushButton, FluentIcon as FIF,
    ComboBox, TableWidget, MessageBox, InfoBar, InfoBarPosition,
    ProgressRing, ScrollArea, CardWidget,
)

from app.common.logger import get_logger
from app.common.paths import list_drives
from app.common.size_fmt import format_size_chinese
from app.config import LINK_TYPE_JUNCTION, LINK_TYPE_SYMLINK
from app.models.installed_app import InstalledApp
from app.models.move_record import MoveRecord, MoveResult, PrecheckResult, RollbackResult
from app.services.mover import MoverService
from app.services.uninstaller import UninstallerService

logger = get_logger("mover_page")


class _LoadMovableWorker(QThread):
    """后台获取可搬家应用列表。"""
    progress = Signal(int, str)
    finished_signal = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._uninst = UninstallerService()
        self._mover = MoverService()

    def run(self):
        self.progress.emit(20, "加载已安装程序...")
        apps = self._uninst.list_installed(include_appx=False)
        self.progress.emit(70, "过滤可搬家应用...")
        movable = self._mover.get_movable_apps(apps)
        self.progress.emit(100, "完成")
        self.finished_signal.emit(movable)


class _MoveWorker(QThread):
    """后台执行搬家。"""
    progress_signal = Signal(str, int, int)  # stage, percent, total
    finished_signal = Signal(object)

    def __init__(self, app: InstalledApp, target_drive: str, link_type: str, parent=None):
        super().__init__(parent)
        self._app = app
        self._target = target_drive
        self._link_type = link_type
        self._service = MoverService()

    def run(self):
        # progress_cb: (stage, percent, message) -> None
        # 但 MoverService.move 的回调是 (stage, percent, message) 元组
        # 这里我们用 lambda 把 (s, p, m) 转发为 signal
        result = self._service.move(
            self._app,
            self._target,
            link_type=self._link_type,
            progress_cb=lambda s, p, m: self.progress_signal.emit(s, p, m if isinstance(m, str) else ""),
        )
        self.finished_signal.emit(result)


class MoverPage(QWidget):
    """软件搬家页面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("moverPage")

        self._movable_apps: List[InstalledApp] = []
        self._history: List[MoveRecord] = []
        self._selected_app: Optional[InstalledApp] = None
        self._drives: List[dict] = []
        self._load_worker: Optional[_LoadMovableWorker] = None
        self._move_worker: Optional[_MoveWorker] = None

        self._build_ui()
        self._load_drives()
        self._start_load_apps()
        self._load_history()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        # 标题
        header = QHBoxLayout()
        title = TitleLabel("软件搬家")
        header.addWidget(title)
        header.addStretch()
        self.btn_refresh = PushButton(FIF.SYNC, "刷新")
        self.btn_refresh.clicked.connect(self._start_load_apps)
        header.addWidget(self.btn_refresh)
        root.addLayout(header)

        # 目标盘选择
        target_row = QHBoxLayout()
        target_row.addWidget(StrongBodyLabel("目标盘："))
        self.drive_combo = ComboBox()
        self.drive_combo.setMinimumWidth(280)
        target_row.addWidget(self.drive_combo)
        target_row.addStretch()

        target_row.addWidget(BodyLabel("链接类型："))
        self.link_type_combo = ComboBox()
        self.link_type_combo.addItems([
            "NTFS Junction（推荐，兼容性好）",
            "Symbolic Link（需管理员/开发者模式）",
        ])
        self.link_type_combo.setMinimumWidth(280)
        target_row.addWidget(self.link_type_combo)

        root.addLayout(target_row)

        # 状态
        status_row = QHBoxLayout()
        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(24, 24)
        self.progress_ring.setVisible(False)
        self.status_label = BodyLabel("准备就绪")
        self.status_label.setStyleSheet("color: #888;")
        status_row.addWidget(self.progress_ring)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        root.addLayout(status_row)

        # 主表格 + 详情
        main_row = QHBoxLayout()
        self.table = TableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["名称", "当前位置", "大小", "类型"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        for i in range(2, 4):
            header_view.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_app_selected)
        main_row.addWidget(self.table, 1)

        # 右侧详情 + 操作
        right_panel = QWidget()
        right_panel.setFixedWidth(300)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        self.detail_card = CardWidget()
        self.detail_layout_inner = QVBoxLayout(self.detail_card)
        self.detail_layout_inner.setContentsMargins(16, 16, 16, 16)
        self.detail_layout_inner.setSpacing(6)
        self.detail_name = StrongBodyLabel("请选择程序")
        self.detail_layout_inner.addWidget(self.detail_name)
        self.detail_info = BodyLabel("")
        self.detail_info.setStyleSheet("color: #666; font-size: 12px;")
        self.detail_info.setWordWrap(True)
        self.detail_layout_inner.addWidget(self.detail_info)
        right_layout.addWidget(self.detail_card)

        self.btn_precheck = PushButton(FIF.SEARCH, "预检")
        self.btn_precheck.setEnabled(False)
        self.btn_precheck.clicked.connect(self._on_precheck_clicked)
        right_layout.addWidget(self.btn_precheck)

        self.btn_move = PrimaryPushButton(FIF.MOVE, "搬家到目标盘")
        self.btn_move.setEnabled(False)
        self.btn_move.clicked.connect(self._on_move_clicked)
        right_layout.addWidget(self.btn_move)

        right_layout.addStretch()

        main_row.addWidget(right_panel)
        root.addLayout(main_row, 1)

        # 搬家历史
        root.addWidget(StrongBodyLabel("搬家历史"))
        self.history_table = TableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(["程序", "源路径", "目标路径", "时间", "状态"])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setShowGrid(False)
        self.history_table.setMaximumHeight(220)
        h_header = self.history_table.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.Stretch)
        h_header.setSectionResizeMode(1, QHeaderView.Stretch)
        h_header.setSectionResizeMode(2, QHeaderView.Stretch)
        h_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        root.addWidget(self.history_table)

        self.btn_rollback = PushButton("回滚选中的搬家记录")
        self.btn_rollback.clicked.connect(self._on_rollback_clicked)
        root.addWidget(self.btn_rollback)

    def _load_drives(self):
        self._drives = list_drives()
        self.drive_combo.clear()
        for d in self._drives:
            drive = d["drive"]
            label = d.get("label", "")
            free_gb = d.get("free", 0) / (1024 ** 3)
            total_gb = d.get("total", 0) / (1024 ** 3)
            fs = d.get("fs", "")
            display = f"{drive} ({label}) {free_gb:.1f}/{total_gb:.1f} GB · {fs}"
            self.drive_combo.addItem(display, drive)

    def _start_load_apps(self):
        if self._load_worker and self._load_worker.isRunning():
            return
        self.btn_refresh.setEnabled(False)
        self.progress_ring.setVisible(True)
        self.progress_ring.setValue(0)
        self.status_label.setText("加载可搬家应用列表...")

        self._load_worker = _LoadMovableWorker(parent=self)
        self._load_worker.progress.connect(self._on_load_progress)
        self._load_worker.finished_signal.connect(self._on_load_finished)
        self._load_worker.start()

    def _on_load_progress(self, percent: int, message: str):
        self.progress_ring.setValue(percent)
        self.status_label.setText(message)

    def _on_load_finished(self, apps: List[InstalledApp]):
        self._movable_apps = apps
        self.progress_ring.setVisible(False)
        self.btn_refresh.setEnabled(True)
        self.status_label.setText(f"已加载 {len(apps)} 个可搬家应用")
        self._render_table()

    def _render_table(self):
        self.table.setRowCount(len(self._movable_apps))
        for row, app in enumerate(self._movable_apps):
            self.table.setItem(row, 0, QTableWidgetItem(app.name))
            self.table.setItem(row, 1, QTableWidgetItem(app.install_location))
            self.table.setItem(row, 2, QTableWidgetItem(app.display_size))
            self.table.setItem(row, 3, QTableWidgetItem(app.display_type))
            self.table.setRowHeight(row, 32)
        if not self._movable_apps:
            self.status_label.setText("没有可搬家的应用（已加载程序可能都是系统组件或 UWP）")

    def _on_app_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._selected_app = None
            self.detail_name.setText("请选择程序")
            self.detail_info.setText("")
            self.btn_move.setEnabled(False)
            self.btn_precheck.setEnabled(False)
            return
        idx = rows[0].row()
        if idx >= len(self._movable_apps):
            return
        app = self._movable_apps[idx]
        self._selected_app = app

        info_lines = [
            f"发布者：{app.publisher or '—'}",
            f"版本：{app.version or '—'}",
            f"占用：{app.display_size}",
            f"位置：\n{app.install_location}",
        ]
        self.detail_name.setText(app.name)
        self.detail_info.setText("\n".join(info_lines))
        self.btn_precheck.setEnabled(True)
        self.btn_move.setEnabled(self.drive_combo.count() > 0)

    def _on_precheck_clicked(self):
        if not self._selected_app:
            return
        idx = self.drive_combo.currentIndex()
        if idx < 0 or idx >= len(self._drives):
            return
        target = self._drives[idx]["drive"]

        svc = MoverService()
        result = svc.precheck(self._selected_app, target)

        msg_lines = []
        if result.ok:
            msg_lines.append("✓ 预检通过，可执行搬家")
        else:
            msg_lines.append("✗ 预检未通过")
        msg_lines.append("")
        msg_lines.append(
            f"源占用：{format_size_chinese(result.source_size_bytes)}"
        )
        msg_lines.append(
            f"目标剩余：{format_size_chinese(result.target_free_bytes)}"
        )
        if result.errors:
            msg_lines.append("\n错误：")
            for e in result.errors:
                msg_lines.append(f"  • {e}")
        if result.warnings:
            msg_lines.append("\n警告：")
            for w in result.warnings:
                msg_lines.append(f"  • {w}")
        if result.blocking_processes:
            msg_lines.append("\n正在占用此应用的进程：")
            for p in result.blocking_processes:
                msg_lines.append(f"  • {p['name']} (PID {p['pid']})")

        box = MessageBox("预检结果", "\n".join(msg_lines), self.window())
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()

    def _on_move_clicked(self):
        if not self._selected_app:
            return
        idx = self.drive_combo.currentIndex()
        if idx < 0 or idx >= len(self._drives):
            return
        target = self._drives[idx]["drive"]
        link_type = LINK_TYPE_SYMLINK if self.link_type_combo.currentIndex() == 1 else LINK_TYPE_JUNCTION

        # 二次确认
        box = MessageBox(
            f"搬家 {self._selected_app.name}",
            f"搬家操作将：\n"
            f"1. 复制 {self._selected_app.name} 到 {target}WinOptimizer\\\n"
            f"2. 校验复制完整性\n"
            f"3. 在原位置创建 {('符号链接' if link_type == LINK_TYPE_SYMLINK else 'Junction')}\n"
            f"4. 记录历史以便一键回滚\n\n"
            f"⚠ 请先关闭此应用，否则复制可能失败\n\n"
            f"是否继续？",
            self.window(),
        )
        box.yesButton.setText("开始搬家")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        # 启动 worker
        self.btn_move.setEnabled(False)
        self.progress_ring.setVisible(True)
        self.progress_ring.setValue(0)
        self.status_label.setText(f"开始搬家 {self._selected_app.name}...")

        self._move_worker = _MoveWorker(self._selected_app, target, link_type, parent=self)
        self._move_worker.progress_signal.connect(self._on_move_progress)
        self._move_worker.finished_signal.connect(self._on_move_finished)
        self._move_worker.start()

    def _on_move_progress(self, stage: str, percent: int, _msg):
        # percent 实际范围 0-100，stage 区分阶段
        self.progress_ring.setValue(percent)
        stage_label = {
            "prepare": "准备",
            "copy": "复制",
            "verify": "校验",
            "switch": "切换链接",
        }.get(stage, stage)
        self.status_label.setText(f"{stage_label} ({percent}%)")

    def _on_move_finished(self, result: MoveResult):
        self.progress_ring.setVisible(False)
        self.btn_move.setEnabled(self._selected_app is not None)

        msg_lines = []
        if result.success:
            msg_lines.append(f"✓ {result.message}")
            msg_lines.append(f"\n复制数据：{format_size_chinese(result.bytes_moved)}")
            msg_lines.append(f"耗时：{result.elapsed_seconds:.1f} 秒")
            msg_lines.append("\n应用现在仍通过原路径访问文件，您可以立即启动验证。")
            msg_lines.append("如有问题，可使用底部的「回滚」功能恢复。")
            box = MessageBox("搬家完成", "\n".join(msg_lines), self.window())
            box.yesButton.setText("确定")
            box.cancelButton.hide()
            box.exec()
            # 刷新
            self._start_load_apps()
            self._load_history()
        else:
            msg_lines.append(f"✗ 搬家失败：{result.error}")
            box = MessageBox("搬家失败", "\n".join(msg_lines), self.window())
            box.yesButton.setText("确定")
            box.cancelButton.hide()
            box.exec()

    def _load_history(self):
        svc = MoverService()
        self._history = svc.list_history()
        # 仅显示 active 的
        active = [h for h in self._history if h.status == "active"]
        self.history_table.setRowCount(len(active))
        for row, h in enumerate(active):
            self.history_table.setItem(row, 0, QTableWidgetItem(h.app_name))
            self.history_table.setItem(row, 1, QTableWidgetItem(h.source_path))
            self.history_table.setItem(row, 2, QTableWidgetItem(h.target_path))
            self.history_table.setItem(row, 3, QTableWidgetItem(h.moved_at))
            self.history_table.setItem(row, 4, QTableWidgetItem(h.status))
            self.history_table.setRowHeight(row, 28)

    def _on_rollback_clicked(self):
        rows = self.history_table.selectionModel().selectedRows()
        if not rows:
            InfoBar.warning(
                title="请先选择",
                content="在搬家历史表格中选择要回滚的记录",
                parent=self, duration=2000, position=InfoBarPosition.TOP,
            )
            return
        idx = rows[0].row()
        active = [h for h in self._history if h.status == "active"]
        if idx >= len(active):
            return
        record = active[idx]

        box = MessageBox(
            f"回滚 {record.app_name}",
            f"回滚操作将：\n"
            f"1. 删除 {record.source_path} 处的链接\n"
            f"2. 把备份目录恢复到原位置\n"
            f"3. 标记该搬家记录为「已回滚」\n\n"
            f"⚠ 请确保应用已关闭\n\n"
            f"是否继续？",
            self.window(),
        )
        box.yesButton.setText("回滚")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        svc = MoverService()
        result = svc.rollback(record.id)

        msg = result.message if result.success else f"✗ 回滚失败：{result.error}"
        box = MessageBox("回滚结果", msg, self.window())
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()

        if result.success:
            self._load_history()
            self._start_load_apps()

    def cancel_running(self):
        if self._load_worker and self._load_worker.isRunning():
            self._load_worker.quit()
            self._load_worker.wait(2000)
        if self._move_worker and self._move_worker.isRunning():
            self._move_worker._service.cancel()
            self._move_worker.quit()
            self._move_worker.wait(2000)