"""
清理功能测试：用临时目录模拟清理流程（不会动真实系统）。
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from app.models.clean_rule import CleanRule, CleanItem
from app.services.cleaner import CleanerService
from app.common.size_fmt import format_size_chinese


def main():
    # 创建临时测试目录
    test_root = Path(tempfile.mkdtemp(prefix="cleaner_test_"))
    print(f"测试根目录: {test_root}")

    # 创建模拟的可清理文件
    sub1 = test_root / "app1" / "cache"
    sub1.mkdir(parents=True)
    # 5 个 1MB 文件
    for i in range(5):
        (sub1 / f"file_{i}.log").write_bytes(b"x" * (1024 * 1024))

    sub2 = test_root / "app2" / "temp"
    sub2.mkdir(parents=True)
    for i in range(3):
        (sub2 / f"tmp_{i}.tmp").write_bytes(b"y" * (512 * 1024))

    # 模拟时间：让文件 mtime 变成 7 天前
    old_time = time.time() - 7 * 86400
    for p in test_root.rglob("*"):
        if p.is_file():
            os.utime(str(p), (old_time, old_time))

    # 创建测试规则
    rule = CleanRule(
        id="test_rule",
        category="测试",
        name="测试规则",
        description="仅用于测试",
        paths=[str(test_root)],
        patterns=["*"],
        min_age_days=1,
        risk="safe",
    )

    # 扫描
    service = CleanerService()
    result = service.scan([rule])
    print(f"\n扫描: 发现 {len(result.items)} 项, 总大小 {format_size_chinese(result.total_size)}")

    if not result.items:
        print("FAIL: 没扫描到测试文件")
        shutil.rmtree(test_root)
        return

    # 清理（走回收站）
    clean_result = service.clean(result.items, use_recycle_bin=True)
    print(f"\n清理结果:")
    print(f"  成功: {clean_result.deleted_count}")
    print(f"  失败: {clean_result.failed_count}")
    print(f"  释放: {format_size_chinese(clean_result.deleted_bytes)}")

    # 验证文件已被移到回收站（Windows） / 直接删除（非 Windows）
    remaining = list(test_root.rglob("*"))
    files_remaining = [r for r in remaining if r.is_file()]
    print(f"\n剩余文件数: {len(files_remaining)}（清理后应为 0）")

    if clean_result.deleted_count == len(result.items) and len(files_remaining) == 0:
        print("\nCLEAN TEST PASSED")
    else:
        print(f"\nCLEAN TEST FAIL: deleted={clean_result.deleted_count}, "
              f"remaining={len(files_remaining)}, errors={clean_result.errors[:3]}")

    # 清理测试目录
    shutil.rmtree(test_root, ignore_errors=True)


if __name__ == "__main__":
    main()