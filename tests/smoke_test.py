"""
端到端烟雾测试：使用 offscreen 平台启动应用，验证所有页面能成功初始化。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Monkey-patch 避免 HomePage 触发重的 UninstallService 枚举
from app.ui.pages import home_page as hp_module
def fast_run(self):
    self.finished_signal.emit({
        "drive_info": {"drive": "C:\\", "fs": "NTFS", "total": 500 * (1024**3), "free": 100 * (1024**3)},
        "app_count": 0,
        "cleanable_estimate": 0,
    })
hp_module._DriveStatWorker.run = fast_run

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.config import APP_NAME, APP_VERSION
from app.common.logger import setup_logging
from app.ui.main_window import MainWindow


def main():
    setup_logging()
    print(f"{APP_NAME} v{APP_VERSION}")

    app = QApplication(sys.argv)
    window = MainWindow()
    print(f"  MainWindow: {window.size().width()}x{window.size().height()}")

    pages = [
        ("home_page", window.home_page),
        ("cleaner_page", window.cleaner_page),
        ("uninstaller_page", window.uninstaller_page),
        ("mover_page", window.mover_page),
        ("about_page", window.about_page),
    ]
    for name, page in pages:
        print(f"  {name}: objName={page.objectName()} {page.size().width()}x{page.size().height()}")

    # 验证清理规则
    from collections import Counter
    print("\nCleaner rule counts by category:")
    counter = Counter(r.category for r in window.cleaner_page._all_rules)
    for cat, n in sorted(counter.items()):
        print(f"  {cat}: {n}")

    QTimer.singleShot(800, app.quit)
    app.exec()
    print("\nEND-TO-END TEST PASSED - all 5 pages initialized")


if __name__ == "__main__":
    main()