"""
软件卸载枚举测试：列出已安装程序。
"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from app.services.uninstaller import UninstallerService
from app.common.size_fmt import format_size_chinese


def main():
    service = UninstallerService()
    start = time.time()
    print("正在枚举已安装程序（首次较慢，需扫描注册表 + AppX）...")
    apps = service.list_installed(include_appx=True)
    elapsed = time.time() - start

    print(f"\n枚举完成: {len(apps)} 个程序, 耗时 {elapsed:.1f} 秒")

    # 按类型统计
    from collections import Counter
    type_counter = Counter(a.app_type for a in apps)
    print("\n按类型:")
    for t, n in type_counter.items():
        print(f"  {t}: {n}")

    sys_count = sum(1 for a in apps if a.is_system)
    print(f"\n系统程序: {sys_count} 个")
    print(f"普通程序: {len(apps) - sys_count} 个")

    # 大文件 top 10
    with_size = [a for a in apps if a.actual_size > 0]
    print(f"\n已计算出实际占用的程序: {len(with_size)} 个")
    if with_size:
        top = sorted(with_size, key=lambda a: -a.actual_size)[:10]
        print("\n占用最大的 10 个程序:")
        for a in top:
            print(f"  {format_size_chinese(a.actual_size):>10s}  {a.name[:40]} ({a.publisher[:30] if a.publisher else '?'})")


if __name__ == "__main__":
    main()