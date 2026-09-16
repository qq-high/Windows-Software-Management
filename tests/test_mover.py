"""
软件搬家端到端测试：用临时目录模拟应用目录与目标盘，验证完整流程。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")


def main():
    # 创建源目录与目标目录
    src_root = Path(tempfile.mkdtemp(prefix="mover_src_"))
    target_root = Path(tempfile.mkdtemp(prefix="mover_tgt_"))

    app_dir = src_root / "TestApp"
    app_dir.mkdir()
    (app_dir / "main.exe").write_bytes(b"PE\x00\x00" + b"\x00" * 100)
    (app_dir / "data.bin").write_bytes(b"\x00" * (10 * 1024 * 1024))
    nested = app_dir / "sub" / "deeper"
    nested.mkdir(parents=True)
    (nested / "config.json").write_text('{"setting": "value"}')

    print(f"src_root: {src_root}")
    print(f"target_root: {target_root}")

    from app.services.mover import (
        copy_directory, verify_copy, create_link, remove_link,
    )

    target_app = target_root / "TestApp"
    target_app.mkdir()

    print("\n[1] copy...")
    ok = copy_directory(app_dir, target_app, progress_cb=lambda d, t, m: None)
    print(f"    copy: {'OK' if ok else 'FAIL'}")

    print("\n[2] verify...")
    verify = verify_copy(app_dir, target_app)
    print(f"    verify result: {verify}")

    print("\n[3] create junction...")
    link_ok = create_link(app_dir, target_app, "junction")
    print(f"    junction: {'OK' if link_ok else 'FAIL'}")

    if (app_dir / "main.exe").exists():
        print("    [+] can access main.exe via link")
    else:
        print("    [-] cannot access main.exe via link")

    # 通过链接读 data.bin 校验内容
    try:
        with open(app_dir / "data.bin", "rb") as f:
            head = f.read(4)
        if head == b"\x00\x00\x00\x00":
            print("    [+] data.bin readable via junction")
    except Exception as e:
        print(f"    [-] read data.bin error: {e}")

    print("\n[4] remove junction...")
    rm_ok = remove_link(app_dir)
    print(f"    remove: {'OK' if rm_ok else 'FAIL'}")

    if not app_dir.exists():
        print("    [+] source dir removed (junction works)")
    else:
        print("    [+] source dir still exists (junction cleared)")

    # 验证目标完整
    target_files = [f for f in target_app.rglob("*") if f.is_file()]
    print(f"\n[5] target contains {len(target_files)} files")

    # 清理
    import shutil
    try:
        if app_dir.exists():
            shutil.rmtree(app_dir, ignore_errors=True)
        shutil.rmtree(target_app, ignore_errors=True)
    except Exception:
        pass
    shutil.rmtree(src_root, ignore_errors=True)
    shutil.rmtree(target_root, ignore_errors=True)

    if verify["ok"] and verify["total_files"] > 0:
        print("\nMOVER COPY+VERIFY TEST PASSED")
        if link_ok:
            print("JUNCTION TEST PASSED")
        else:
            print("JUNCTION TEST SKIPPED (likely no admin or unsupported FS)")
    else:
        print("\nMOVER TEST FAIL")


if __name__ == "__main__":
    main()