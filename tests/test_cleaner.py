"""
扫描功能测试：实际跑一遍 CleanerService.scan，验证它能找到可清理项。
"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from app.services.rules import load_default_rules
from app.services.cleaner import CleanerService
from app.common.size_fmt import format_size_chinese


def main():
    rules = load_default_rules()
    print(f"已加载 {len(rules)} 条规则")

    service = CleanerService()
    start = time.time()
    progress_count = [0]

    def progress_cb(p, msg):
        progress_count[0] += 1
        if p % 20 == 0:
            print(f"  [{p}%] {msg}")

    print("\n开始扫描...")
    result = service.scan(rules, progress_cb=progress_cb, filter_categories=None)
    elapsed = time.time() - start

    print(f"\n扫描完成:")
    print(f"  发现 {len(result.items)} 个可清理项")
    print(f"  总大小: {format_size_chinese(result.total_size)}")
    print(f"  耗时: {elapsed:.1f} 秒")
    print(f"  进度回调次数: {progress_count[0]}")

    if result.items:
        # 按规则统计
        from collections import Counter, defaultdict
        rule_counter = Counter(item.rule_name for item in result.items)
        print(f"\n按规则统计（top 10）:")
        for name, n in rule_counter.most_common(10):
            print(f"  {n:4d} 项 - {name}")

        # 按风险等级统计
        risk_counter = Counter(item.risk for item in result.items)
        print(f"\n按风险等级:")
        for risk, n in risk_counter.items():
            print(f"  {risk}: {n}")

        # 前 5 个最大的项
        items_sorted = sorted(result.items, key=lambda i: -i.size_bytes)[:5]
        print(f"\n最大的 5 项:")
        for it in items_sorted:
            print(f"  {format_size_chinese(it.size_bytes):>10s}  {it.path[:80]}")


if __name__ == "__main__":
    main()