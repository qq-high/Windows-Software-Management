"""
关于页面：版本、作者、致谢、参考资料链接。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    TitleLabel, SubtitleLabel, BodyLabel, StrongBodyLabel,
    FluentIcon as FIF, CardWidget, IconWidget, HyperlinkButton,
)

from app.common.admin import get_admin_username, is_admin
from app.common.paths import list_drives
from app.common.size_fmt import format_size_chinese
from app.config import APP_NAME, APP_VERSION, APP_AUTHOR, APP_DESCRIPTION


class AboutPage(QWidget):
    """关于页面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aboutPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 30, 30, 30)
        root.setSpacing(20)

        # 标题
        root.addWidget(TitleLabel(f"{APP_NAME}"))

        subtitle = SubtitleLabel(f"版本 {APP_VERSION}")
        subtitle.setStyleSheet("color: #888;")
        root.addWidget(subtitle)

        # 描述
        desc = BodyLabel(APP_DESCRIPTION)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666; line-height: 1.6;")
        root.addWidget(desc)

        # 主要功能
        card_widget = CardWidget()
        card_layout = QVBoxLayout(card_widget)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(10)
        card_layout.addWidget(StrongBodyLabel("主要功能"))
        features = [
            "✓ C 盘清理：50+ 内置规则，安全清理系统/用户/应用/开发工具缓存",
            "✓ 软件卸载：标准卸载 + 残留扫描 + 强制卸载 + UWP/AppX 应用",
            "✓ 软件搬家：复制 + NTFS 符号链接，一键回滚",
            "✓ 走回收站，可随时还原",
            "✓ 跳过最近修改文件、不跟随 Junction、不动用户文档",
        ]
        for f in features:
            label = BodyLabel(f)
            label.setStyleSheet("color: #444;")
            card_layout.addWidget(label)
        root.addWidget(card_widget)

        # 安全机制
        safety_card = CardWidget()
        safety_layout = QVBoxLayout(safety_card)
        safety_layout.setContentsMargins(20, 16, 20, 16)
        safety_layout.setSpacing(8)
        safety_layout.addWidget(StrongBodyLabel("安全机制"))
        safety_points = [
            "• 删除前预览，默认走回收站",
            "• 跳过 24 小时内修改的文件",
            "• 不跟随 Junction / Symbolic Link",
            "• 不删 System32、Program Files 根、用户文档",
            "• 不修改注册表" if False else "• 卸载使用程序自身的卸载命令",
            "• 搬家前预检 NTFS / 磁盘空间 / 进程占用",
            "• 校验复制完整性后才切换链接",
            "• 完整历史记录，支持一键回滚",
        ]
        for p in safety_points:
            label = BodyLabel(p)
            label.setStyleSheet("color: #555;")
            safety_layout.addWidget(label)
        root.addWidget(safety_card)

        # 系统信息
        sys_card = CardWidget()
        sys_layout = QVBoxLayout(sys_card)
        sys_layout.setContentsMargins(20, 16, 20, 16)
        sys_layout.setSpacing(8)
        sys_layout.addWidget(StrongBodyLabel("系统信息"))

        info_lines = [
            f"当前用户：{get_admin_username()}",
            f"权限状态：{'✓ 管理员' if is_admin() else '⚠ 普通用户（建议以管理员身份运行）'}",
        ]
        # C 盘容量
        for d in list_drives():
            if d["drive"].upper().startswith("C"):
                free = format_size_chinese(d.get("free", 0))
                total = format_size_chinese(d.get("total", 0))
                info_lines.append(
                    f"C 盘：{d['drive']} {free} 可用 / {total} 总量"
                )
                break

        for line in info_lines:
            label = BodyLabel(line)
            label.setStyleSheet("color: #555;")
            sys_layout.addWidget(label)
        root.addWidget(sys_card)

        # 致谢 / 参考
        ack_card = CardWidget()
        ack_layout = QVBoxLayout(ack_card)
        ack_layout.setContentsMargins(20, 16, 20, 16)
        ack_layout.setSpacing(6)
        ack_layout.addWidget(StrongBodyLabel("致谢"))
        ack_items = [
            "本项目受以下开源项目启发：",
            "• BleachBit - 通用清理标杆",
            "• BCUninstaller - 卸载机制广度",
            "• Winapp2.ini - 清理规则库标准",
            "• Viap / FreeMove / NeatShift - 软件搬家设计",
            "• BHUninstaller - 永不删除安全哲学",
            "• PySide6-Fluent-Widgets - 美观的 Fluent UI 组件",
        ]
        for it in ack_items:
            label = BodyLabel(it)
            label.setStyleSheet("color: #666;")
            ack_layout.addWidget(label)
        root.addWidget(ack_card)

        root.addStretch()