"""
C 盘清理页面：
  - 左侧：分类列表（系统/用户/浏览器/应用/开发工具/高级）
  - 右侧：当前分类规则 CheckBox 列表（可勾选）
  - 顶部：扫描 / 一键清理选中 按钮
  - 底部：进度条
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QFrame, QSizePolicy,
)

from qfluentwidgets import (
    ScrollArea, TitleLabel, SubtitleLabel, BodyLabel, StrongBodyLabel,
    PrimaryPushButton, PushButton, FluentIcon as FIF,
    ListWidget, CheckBox, MessageBox, InfoBar, InfoBarPosition,
    IndeterminateProgressRing, ProgressRing, ProgressBar,
    CardWidget, IconWidget,
)

from app.common.logger import get_logger
from app.common.size_fmt import format_size_chinese
from app.models.clean_rule import CleanItem, CleanRule, ScanResult
from app.services.cleaner import CleanerService
from app.services.rules import group_by_category, load_default_rules

logger = get_logger("cleaner_page")


class _ScanWorker(QThread):
    """后台扫描线程。"""
    progress = Signal(int, str)
    finished_signal = Signal(object)  # ScanResult

    def __init__(self, rules: List[CleanRule], parent=None):
        super().__init__(parent)
        self._rules = rules
        self._service = CleanerService()

    def run(self):
        result = self._service.scan(
            self._rules,
            progress_cb=lambda p, m: self.progress.emit(p, m),
        )
        self.finished_signal.emit(result)


class _CleanWorker(QThread):
    """后台清理线程。"""
    progress = Signal(int, str)
    finished_signal = Signal(object)

    def __init__(self, items: List[CleanItem], use_recycle_bin: bool = True, parent=None):
        super().__init__(parent)
        self._items = items
        self._use_recycle_bin = use_recycle_bin
        self._service = CleanerService()

    def run(self):
        result = self._service.clean(
            self._items,
            use_recycle_bin=self._use_recycle_bin,
            progress_cb=lambda p, m: self.progress.emit(p, m),
        )
        self.finished_signal.emit(result)


class _RuleCheckRow(QWidget):
    """单条规则的勾选行：复选框 + 名称 + 描述 + 风险标签 + 可回收大小。"""

    def __init__(self, rule: CleanRule, parent=None):
        super().__init__(parent)
        self.rule = rule
        self._items: List[CleanItem] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # 复选框
        self.checkbox = CheckBox()
        self.checkbox.setChecked(rule.enabled_by_default)
        self.checkbox.setEnabled(False)  # 扫描前不可用
        layout.addWidget(self.checkbox)

        # 中间信息
        middle = QVBoxLayout()
        middle.setSpacing(2)
        name_layout = QHBoxLayout()
        name_layout.setSpacing(8)
        self.name_label = StrongBodyLabel(rule.name)
        name_layout.addWidget(self.name_label)
        # 风险标签
        risk_color = {"safe": "#107C10", "moderate": "#F7630C", "risky": "#D13438"}.get(rule.risk, "#666")
        risk_text = {"safe": "安全", "moderate": "中等风险", "risky": "高风险"}.get(rule.risk, "")
        if risk_text:
            self.risk_label = BodyLabel(f"  {risk_text}")
            self.risk_label.setStyleSheet(f"color: {risk_color}; font-size: 12px;")
            name_layout.addWidget(self.risk_label)
        name_layout.addStretch()
        middle.addLayout(name_layout)

        self.desc_label = BodyLabel(rule.description)
        self.desc_label.setStyleSheet("color: #888; font-size: 12px;")
        self.desc_label.setWordWrap(True)
        middle.addWidget(self.desc_label)
        layout.addLayout(middle, 1)

        # 大小
        self.size_label = TitleLabel("—")
        self.size_label.setStyleSheet("font-size: 18px; font-weight: 600; color: #0078D4;")
        self.size_label.setFixedWidth(110)
        self.size_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.size_label)

    def set_items(self, items: List[CleanItem]):
        self._items = items
        self.checkbox.setEnabled(len(items) > 0)
        self.checkbox.setChecked(len(items) > 0 and self.checkbox.isChecked())
        total = sum(i.size_bytes for i in items)
        self.size_label.setText(format_size_chinese(total))

    def get_items(self) -> List[CleanItem]:
        return self._items if self.checkbox.isChecked() else []

    def count(self) -> int:
        return len(self._items)

    def total_bytes(self) -> int:
        return sum(i.size_bytes for i in self._items)


class CleanerPage(QWidget):
    """C 盘清理页面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cleanerPage")

        self._all_rules = load_default_rules()
        self._rules_by_category = group_by_category(self._all_rules)
        self._rows: List[_RuleCheckRow] = []   # 当前分类的行
        self._scan_worker = None
        self._clean_worker = None
        self._current_scan_result: ScanResult = None
        self._selected_category: str = "系统"

        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ============== 左侧分类列表 ==============
        left_panel = QWidget()
        left_panel.setFixedWidth(220)
        left_panel.setStyleSheet("background-color: transparent;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 24, 8, 16)
        left_layout.setSpacing(4)

        cat_label = SubtitleLabel("分类")
        cat_label.setStyleSheet("padding-left: 8px; color: #888;")
        left_layout.addWidget(cat_label)
        left_layout.addSpacing(8)

        self.category_list = ListWidget()
        categories = sorted(self._rules_by_category.keys())
        if "高级" in categories:
            categories.remove("高级")
            categories.append("高级")
        for cat in categories:
            count = len(self._rules_by_category[cat])
            item_text = f"  {cat}  ({count})"
            self.category_list.addItem(item_text)

        self.category_list.setCurrentRow(0)
        self.category_list.currentRowChanged.connect(self._on_category_changed)
        left_layout.addWidget(self.category_list)

        # 全选 / 全不选
        left_layout.addSpacing(12)
        self.btn_select_all = PushButton("全选")
        self.btn_select_all.clicked.connect(self._select_all)
        left_layout.addWidget(self.btn_select_all)
        self.btn_deselect_all = PushButton("全不选")
        self.btn_deselect_all.clicked.connect(self._deselect_all)
        left_layout.addWidget(self.btn_deselect_all)

        left_layout.addStretch()

        # ============== 右侧内容 ==============
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(24, 24, 24, 24)
        right_layout.setSpacing(16)

        # 标题 + 操作
        header = QHBoxLayout()
        self.title_label = TitleLabel("C 盘清理")
        header.addWidget(self.title_label)
        header.addStretch()
        self.btn_scan = PrimaryPushButton(FIF.SEARCH, "扫描")
        self.btn_scan.clicked.connect(self._on_scan_clicked)
        header.addWidget(self.btn_scan)
        self.btn_clean = PrimaryPushButton(FIF.BROOM, "一键清理选中")
        self.btn_clean.setEnabled(False)
        self.btn_clean.clicked.connect(self._on_clean_clicked)
        header.addWidget(self.btn_clean)
        right_layout.addLayout(header)

        # 进度条 + 状态
        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(28, 28)
        self.progress_ring.setVisible(False)
        progress_layout = QHBoxLayout()
        self.status_label = BodyLabel("准备就绪 - 点击「扫描」开始")
        self.status_label.setStyleSheet("color: #888;")
        progress_layout.addWidget(self.progress_ring)
        progress_layout.addWidget(self.status_label)
        progress_layout.addStretch()
        right_layout.addLayout(progress_layout)

        # 规则列表（滚动）
        self.rules_scroll = ScrollArea()
        self.rules_scroll.setWidgetResizable(True)
        self.rules_container = QWidget()
        self.rules_layout = QVBoxLayout(self.rules_container)
        self.rules_layout.setContentsMargins(0, 0, 0, 0)
        self.rules_layout.setSpacing(6)
        self.rules_layout.addStretch()
        self.rules_scroll.setWidget(self.rules_container)
        right_layout.addWidget(self.rules_scroll, 1)

        # 底部摘要
        self.summary_label = BodyLabel("")
        self.summary_label.setStyleSheet("color: #666; padding: 6px;")
        right_layout.addWidget(self.summary_label)

        # 装配
        root.addWidget(left_panel)
        root.addWidget(right_panel, 1)

        # 渲染默认分类
        self._on_category_changed(0)

    def _on_category_changed(self, row: int):
        """切换分类时刷新右侧规则列表。"""
        # 取当前分类名
        if row < 0 or row >= self.category_list.count():
            return
        text = self.category_list.item(row).text().strip()
        # text 形如 "系统  (5)"
        cat_name = text.split("  ")[0].strip()
        self._selected_category = cat_name

        # 清空旧行
        for r in self._rows:
            r.deleteLater()
        self._rows.clear()
        # 清空 layout 中之前的 widgets
        while self.rules_layout.count() > 1:  # 保留 addStretch
            item = self.rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rules = self._rules_by_category.get(cat_name, [])
        for rule in rules:
            row_widget = _RuleCheckRow(rule)
            self.rules_layout.insertWidget(self.rules_layout.count() - 1, row_widget)
            self._rows.append(row_widget)

        self._update_summary()

    def _select_all(self):
        for r in self._rows:
            if r.checkbox.isEnabled():
                r.checkbox.setChecked(True)
        self._update_summary()

    def _deselect_all(self):
        for r in self._rows:
            if r.checkbox.isEnabled():
                r.checkbox.setChecked(False)
        self._update_summary()

    def _on_scan_clicked(self):
        """开始扫描。"""
        # 获取所有可见分类的所有规则
        rules_to_scan = list(self._all_rules)
        if self._scan_worker and self._scan_worker.isRunning():
            return
        self.btn_scan.setEnabled(False)
        self.btn_clean.setEnabled(False)
        self.status_label.setText("扫描中...")
        self.progress_ring.setVisible(True)
        self.progress_ring.setValue(0)

        self._scan_worker = _ScanWorker(rules_to_scan, parent=self)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished_signal.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_progress(self, percent: int, message: str):
        self.progress_ring.setValue(percent)
        self.status_label.setText(message)

    def _on_scan_finished(self, result: ScanResult):
        self.progress_ring.setVisible(False)
        self.btn_scan.setEnabled(True)
        self._current_scan_result = result
        if result.cancelled:
            self.status_label.setText("扫描已取消")
            return

        # 把扫描结果按 rule_id 分发到对应行
        from collections import defaultdict
        by_rule: Dict[str, List[CleanItem]] = defaultdict(list)
        for item in result.items:
            by_rule[item.rule_id].append(item)

        for row in self._rows:
            items = by_rule.get(row.rule.id, [])
            row.set_items(items)

        total = result.total_size
        self.status_label.setText(
            f"扫描完成 - 共发现 {len(result.items)} 项, "
            f"可释放 {format_size_chinese(total)}（耗时 {result.elapsed_seconds:.1f} 秒）"
        )
        self.btn_clean.setEnabled(total > 0)
        self._update_summary()

    def _on_clean_clicked(self):
        """开始清理。"""
        items = []
        for r in self._rows:
            items.extend(r.get_items())
        if not items:
            InfoBar.warning(
                title="无可清理项",
                content="请先扫描并勾选要清理的项",
                parent=self,
                duration=2000,
                position=InfoBarPosition.TOP,
            )
            return

        total_size = sum(i.size_bytes for i in items)
        # 弹确认框
        msg_box = MessageBox(
            f"准备清理 {len(items)} 项（{format_size_chinese(total_size)}）",
            "清理操作不可撤销！\n\n"
            "• 文件将进入回收站，可在回收站还原\n"
            "• 跳过正在使用的锁定文件\n"
            "• 不会删除用户文档、桌面、下载\n\n"
            "是否继续？",
            self.window(),
        )
        msg_box.yesButton.setText("开始清理")
        msg_box.cancelButton.setText("取消")
        if not msg_box.exec():
            return

        self.btn_clean.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.status_label.setText("清理中...")
        self.progress_ring.setVisible(True)
        self.progress_ring.setValue(0)

        self._clean_worker = _CleanWorker(items, use_recycle_bin=True, parent=self)
        self._clean_worker.progress.connect(self._on_clean_progress)
        self._clean_worker.finished_signal.connect(self._on_clean_finished)
        self._clean_worker.start()

    def _on_clean_progress(self, percent: int, message: str):
        self.progress_ring.setValue(percent)
        self.status_label.setText(message)

    def _on_clean_finished(self, result):
        self.progress_ring.setVisible(False)
        self.btn_scan.setEnabled(True)
        if result.cancelled:
            self.status_label.setText("清理已取消")
            return

        msg = (
            f"清理完成\n\n"
            f"• 成功删除 {result.deleted_count} 项\n"
            f"• 释放 {format_size_chinese(result.deleted_bytes)}\n"
            f"• 失败 {result.failed_count} 项（可能正在被使用）"
        )
        if result.errors and result.failed_count > 0:
            msg += f"\n\n失败详情（前 5 条）：\n"
            msg += "\n".join(f"  {e}" for e in result.errors[:5])

        box = MessageBox("清理完成", msg, self.window())
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()

        # 自动重扫
        self._on_scan_clicked()

    def _update_summary(self):
        total = sum(r.total_bytes() for r in self._rows)
        count = sum(r.count() for r in self._rows if r.checkbox.isChecked())
        self.summary_label.setText(
            f"当前分类：{self._selected_category} · "
            f"已勾选 {count} 项 · "
            f"合计 {format_size_chinese(total)}"
        )

    def cancel_running(self):
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker._service.cancel()
            self._scan_worker.quit()
            self._scan_worker.wait(2000)
        if self._clean_worker and self._clean_worker.isRunning():
            self._clean_worker._service.cancel()
            self._clean_worker.quit()
            self._clean_worker.wait(2000)