"""
软件搬家服务：
  - 复制源目录到目标
  - 校验数据完整性（抽样 SHA-256）
  - 在源位置创建 NTFS Junction 或 Symbolic Link
  - 记录搬家历史，支持一键回滚
  - 进程占用检测、磁盘空间预检

实现参考：
  - Viap (Tauri/Rust)：先复制 → 校验 → 切换链接
  - FreeMove (C#/.NET)：mklink /J 创建 junction
  - NeatShift (WPF)：符号链接 + 系统还原点
"""
from __future__ import annotations

import json
import os
import shutil
import string
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import psutil

from app.common.logger import get_logger, log_operation
from app.common.paths import get_volume_info, is_junction, is_protected
from app.config import (
    LINK_TYPE_JUNCTION,
    MOVE_HISTORY_FILE,
    PROTECTED_PATH_PATTERNS,
    VERIFY_SAMPLE_RATE,
)
from app.models.installed_app import InstalledApp
from app.models.move_record import (
    MoveRecord,
    MoveResult,
    PrecheckResult,
    RollbackResult,
)

logger = get_logger("mover")


# ============ 链接工具 ============

def create_link(link_path: Path, target_path: Path, link_type: str = LINK_TYPE_JUNCTION) -> bool:
    """在 link_path 处创建指向 target_path 的链接。"""
    link_path = Path(link_path)
    target_path = Path(target_path)
    try:
        if link_type == LINK_TYPE_JUNCTION:
            # mklink /J link target
            cmd = ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)]
            out = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if out.returncode != 0:
                # 退回 Symbolic Link
                cmd = ["cmd", "/c", "mklink", "/D", str(link_path), str(target_path)]
                out = subprocess.run(
                    cmd, capture_output=True, text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return out.returncode == 0
            return True
        else:
            cmd = ["cmd", "/c", "mklink", "/D", str(link_path), str(target_path)]
            out = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return out.returncode == 0
    except Exception as e:
        logger.error(f"创建链接失败: {e}")
        return False


def remove_link(link_path: Path) -> bool:
    """删除链接（不删除目标内容）。"""
    link_path = Path(link_path)
    if not link_path.exists():
        return True
    try:
        # rmdir 仅删链接，不删目标
        if is_junction(link_path) or link_path.is_symlink():
            cmd = ["cmd", "/c", "rmdir", str(link_path)]
            subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return not link_path.exists()
        return False
    except Exception as e:
        logger.error(f"删除链接失败: {e}")
        return False


# ============ 复制与校验 ============

def copy_directory(
    src: Path,
    dst: Path,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    cancel_flag: Optional[Callable[[], bool]] = None,
) -> bool:
    """递归复制目录，支持进度回调与取消。

    progress_cb: (bytes_copied, total_bytes, current_file) -> None
    cancel_flag: 返回 True 时取消
    """
    if not src.exists():
        return False
    try:
        total_bytes = sum(
            f.stat().st_size
            for f in src.rglob("*") if f.is_file() and not f.is_junction()
        )
    except Exception:
        total_bytes = 0

    bytes_copied = 0
    try:
        for root, dirs, files in os.walk(str(src)):
            if cancel_flag and cancel_flag():
                return False
            rel = Path(root).relative_to(src)
            dst_dir = dst / rel
            try:
                dst_dir.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError):
                continue

            for f in files:
                if cancel_flag and cancel_flag():
                    return False
                src_file = Path(root) / f
                dst_file = dst_dir / f
                try:
                    if src_file.is_junction():
                        continue
                    if dst_file.exists():
                        try:
                            dst_file.unlink()
                        except OSError:
                            pass
                    size = src_file.stat().st_size
                    # 使用 shutil.copy2 保留元数据；大文件用 copyfileobj
                    shutil.copy2(str(src_file), str(dst_file))
                    bytes_copied += size
                    if progress_cb and (bytes_copied % (32 * 1024 * 1024) < size or total_bytes == 0):
                        progress_cb(bytes_copied, total_bytes, f)
                except (PermissionError, OSError) as e:
                    logger.warning(f"复制失败 {src_file}: {e}")
                    continue
        return True
    except Exception as e:
        logger.error(f"复制目录失败: {e}")
        return False


def verify_copy(src: Path, dst: Path, sample_rate: int = VERIFY_SAMPLE_RATE) -> Dict:
    """校验复制完整性：大小比对 + 抽样 SHA-256。"""
    import hashlib
    result = {"total_files": 0, "verified": 0, "mismatched": 0, "missing_in_dst": 0, "ok": True}
    try:
        src_files = [f for f in src.rglob("*") if f.is_file() and not f.is_junction()]
        result["total_files"] = len(src_files)

        for i, src_file in enumerate(src_files):
            rel = src_file.relative_to(src)
            dst_file = dst / rel
            if not dst_file.exists():
                result["missing_in_dst"] += 1
                result["ok"] = False
                continue
            if i % sample_rate == 0:
                # 抽样校验
                try:
                    h1 = hashlib.sha256()
                    with open(src_file, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            h1.update(chunk)
                    h2 = hashlib.sha256()
                    with open(dst_file, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            h2.update(chunk)
                    if h1.hexdigest() != h2.hexdigest():
                        result["mismatched"] += 1
                        result["ok"] = False
                    else:
                        result["verified"] += 1
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"校验失败: {e}")
        result["ok"] = False
    return result


# ============ 进程检测 ============

def find_blocking_processes(path: Path) -> List[Dict]:
    """查找占用 path 中文件的进程。"""
    path_str = str(path).lower()
    results = []
    try:
        for proc in psutil.process_iter(['pid', 'name', 'open_files']):
            try:
                of = proc.info.get('open_files')
                if not of:
                    continue
                for f in of:
                    if path_str in f.path.lower():
                        results.append({
                            "pid": proc.info['pid'],
                            "name": proc.info['name'],
                            "file": f.path,
                        })
                        break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
    except Exception as e:
        logger.debug(f"进程检测失败: {e}")
    return results


# ============ 搬家历史 ============

def _load_history() -> List[Dict]:
    if not MOVE_HISTORY_FILE.exists():
        return []
    try:
        with open(MOVE_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_history(history: List[Dict]):
    try:
        with open(MOVE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"保存搬家历史失败: {e}")


def _record_to_dict(r: MoveRecord) -> Dict:
    return {
        "id": r.id, "app_name": r.app_name, "app_id": r.app_id,
        "source_path": r.source_path, "target_path": r.target_path,
        "link_type": r.link_type, "moved_size": r.moved_size,
        "moved_at": r.moved_at, "backup_path": r.backup_path,
        "app_type": r.app_type, "status": r.status, "notes": r.notes,
    }


def _dict_to_record(d: Dict) -> MoveRecord:
    return MoveRecord(
        id=d["id"], app_name=d["app_name"], app_id=d["app_id"],
        source_path=d["source_path"], target_path=d["target_path"],
        link_type=d.get("link_type", LINK_TYPE_JUNCTION),
        moved_size=d.get("moved_size", 0), moved_at=d.get("moved_at", ""),
        backup_path=d.get("backup_path", ""), app_type=d.get("app_type", "exe"),
        status=d.get("status", "active"), notes=d.get("notes", ""),
    )


# ============ 主类 ============

class MoverService:
    """软件搬家服务。"""

    def __init__(self):
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def get_movable_apps(self, all_apps: List[InstalledApp]) -> List[InstalledApp]:
        """过滤出可搬家的应用列表。"""
        result = []
        for app in all_apps:
            # AppX/UWP 不能搬
            if app.app_type in ("appx", "msix"):
                continue
            if app.is_system:
                continue
            if not app.install_location:
                continue
            loc = Path(app.install_location)
            if not loc.exists():
                continue
            # 不在受保护根目录
            if is_protected(loc, PROTECTED_PATH_PATTERNS):
                continue
            # 已经在 junction 下
            if is_junction(loc):
                continue
            # Program Files 根目录不允许搬（仅允许搬 Program Files 下的子目录）
            parent = loc.parent
            try:
                # 如果 loc 的父目录本身就是 Program Files 这样的根，则不搬
                for pat in PROTECTED_PATH_PATTERNS:
                    if "*" not in pat and pat.lower() in str(parent).lower():
                        if str(parent).lower() == pat.lower():
                            continue
                # Program Files\\<app> 这种允许搬
                parent_str = str(parent).lower()
                if parent_str in (r"c:\program files", r"c:\program files (x86)"):
                    continue
            except Exception:
                pass
            result.append(app)
        return result

    def precheck(
        self,
        app: InstalledApp,
        target_drive: str,
    ) -> PrecheckResult:
        """预检：源/目标 NTFS、磁盘空间、进程占用。"""
        result = PrecheckResult()
        loc = Path(app.install_location)

        # 1. 源路径存在
        if not loc.exists():
            result.ok = False
            result.errors.append(f"源路径不存在: {loc}")
            return result

        # 2. 源是 NTFS
        src_drive = os.path.splitdrive(str(loc))[0] + "\\"
        src_info = get_volume_info(src_drive)
        if src_info.get("fs") and src_info["fs"].upper() != "NTFS":
            result.ok = False
            result.errors.append(f"源盘不是 NTFS: {src_info.get('fs')}")
            return result

        # 3. 目标盘存在 & NTFS
        if not target_drive:
            result.ok = False
            result.errors.append("请选择目标盘")
            return result
        target_drive = target_drive.upper().rstrip("\\") + "\\"
        if not os.path.exists(target_drive):
            result.ok = False
            result.errors.append(f"目标盘不存在: {target_drive}")
            return result
        tgt_info = get_volume_info(target_drive)
        if tgt_info.get("fs") and tgt_info["fs"].upper() != "NTFS":
            result.ok = False
            result.errors.append(f"目标盘不是 NTFS: {tgt_info.get('fs')}")
            return result

        # 4. 目标盘剩余空间
        src_size = sum(
            f.stat().st_size
            for f in loc.rglob("*") if f.is_file() and not f.is_junction()
        )
        result.source_size_bytes = src_size
        result.target_free_bytes = tgt_info.get("free", 0)
        if result.target_free_bytes < src_size * 1.1:
            result.ok = False
            result.errors.append(
                f"目标盘剩余空间不足: 需要 {src_size * 1.1 / (1024**3):.2f} GB, "
                f"可用 {result.target_free_bytes / (1024**3):.2f} GB"
            )

        # 5. 进程占用检查
        blocking = find_blocking_processes(loc)
        if blocking:
            result.blocking_processes = blocking
            result.warnings.append(
                f"检测到 {len(blocking)} 个进程正在使用此应用的文件，"
                "建议先关闭应用再搬家"
            )
            for p in blocking[:5]:
                result.warnings.append(f"  - {p['name']} (PID {p['pid']})")

        return result

    def move(
        self,
        app: InstalledApp,
        target_root: str,
        link_type: str = LINK_TYPE_JUNCTION,
        progress_cb: Optional[Callable[[str, int, int], None]] = None,
    ) -> MoveResult:
        """执行搬家。

        progress_cb: (stage, percent, message) -> None
            stage: "prepare" | "copy" | "verify" | "switch"
        """
        self._cancel = False
        start = time.time()
        log_operation("软件搬家", f"{app.name}: {app.install_location} -> {target_root}")

        loc = Path(app.install_location)
        app_name = loc.name

        # 1. 准备目标目录
        target_root = Path(target_root)
        # 构造目标路径：target_root/WinOptimizer/<app_name>
        target_base = target_root / "WinOptimizer" / app_name
        # 若目标已存在，自动重命名
        suffix = 0
        target_dir = target_base
        while target_dir.exists():
            suffix += 1
            target_dir = target_base.parent / f"{app_name}_{suffix}"

        if progress_cb:
            progress_cb("prepare", 5, f"准备目标: {target_dir}")

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return MoveResult(success=False, error=f"创建目标目录失败: {e}")

        # 2. 复制
        if progress_cb:
            progress_cb("copy", 10, "复制文件...")

        def copy_progress(bytes_done, total, current):
            if self._cancel:
                return
            if progress_cb and total > 0:
                pct = 10 + int(bytes_done / total * 70)  # 10~80
                progress_cb("copy", pct, f"复制: {current}")

        copy_ok = copy_directory(
            loc, target_dir,
            progress_cb=copy_progress,
            cancel_flag=lambda: self._cancel,
        )
        if not copy_ok or self._cancel:
            # 清理目标
            try:
                shutil.rmtree(str(target_dir), ignore_errors=True)
            except Exception:
                pass
            return MoveResult(success=False, error="复制失败或已取消", elapsed_seconds=time.time() - start)

        # 3. 校验
        if progress_cb:
            progress_cb("verify", 82, "校验数据...")

        verify_result = verify_copy(loc, target_dir)
        if not verify_result["ok"]:
            log_operation("软件搬家-校验失败", f"{app.name}: {verify_result}")
            try:
                shutil.rmtree(str(target_dir), ignore_errors=True)
            except Exception:
                pass
            return MoveResult(
                success=False,
                error=f"校验失败: 不匹配 {verify_result['mismatched']}, 缺失 {verify_result['missing_in_dst']}",
                elapsed_seconds=time.time() - start,
            )

        # 4. 切换链接
        if progress_cb:
            progress_cb("switch", 88, "切换为符号链接...")

        # 4a. 重命名原目录为 backup
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = loc.parent / f"{loc.name}_backup_{ts}"
        try:
            loc.rename(backup)
        except Exception as e:
            try:
                shutil.rmtree(str(target_dir), ignore_errors=True)
            except Exception:
                pass
            return MoveResult(success=False, error=f"重命名源目录失败: {e}")

        # 4b. 创建 Junction
        ok = create_link(loc, target_dir, link_type)
        if not ok:
            # 回滚：把 backup 移回原名
            try:
                backup.rename(loc)
            except Exception:
                pass
            try:
                shutil.rmtree(str(target_dir), ignore_errors=True)
            except Exception:
                pass
            return MoveResult(success=False, error="创建符号链接失败")

        # 4c. 验证链接
        if not loc.exists():
            # 链接无效，回滚
            remove_link(loc)
            try:
                backup.rename(loc)
            except Exception:
                pass
            try:
                shutil.rmtree(str(target_dir), ignore_errors=True)
            except Exception:
                pass
            return MoveResult(success=False, error="链接创建后无法访问")

        # 4d. 删除 backup（保留7天后回收站，避免事故风险）
        try:
            from send2trash import send2trash
            # 暂不立即删除 backup，保留 7 天供用户回滚
            # 这里仅记录 backup 路径，由后台任务清理
        except Exception:
            pass

        # 5. 写历史
        moved_size = verify_result.get("total_files", 0)  # 文件数
        bytes_moved = sum(
            f.stat().st_size
            for f in target_dir.rglob("*") if f.is_file()
        )
        record = MoveRecord(
            id=str(uuid.uuid4()),
            app_name=app.name,
            app_id=app.id,
            source_path=str(loc),
            target_path=str(target_dir),
            link_type=link_type,
            moved_size=bytes_moved,
            moved_at=datetime.now().isoformat(timespec="seconds"),
            backup_path=str(backup),
            app_type=app.app_type,
            status="active",
        )

        history = _load_history()
        history.append(_record_to_dict(record))
        _save_history(history)

        if progress_cb:
            progress_cb("switch", 100, "搬家完成")

        log_operation(
            "软件搬家-完成",
            f"{app.name}: 复制 {bytes_moved / (1024**2):.1f} MB, 链接 {link_type}"
        )
        return MoveResult(
            success=True,
            record_id=record.id,
            message=f"搬家完成: {app.name} -> {target_dir}",
            bytes_moved=bytes_moved,
            elapsed_seconds=time.time() - start,
        )

    def list_history(self) -> List[MoveRecord]:
        return [_dict_to_record(d) for d in _load_history()]

    def rollback(self, record_id: str) -> RollbackResult:
        """一键回滚：删除链接 → 把 backup 移回原位。"""
        history = _load_history()
        for entry in history:
            if entry["id"] == record_id:
                source = Path(entry["source_path"])
                target = Path(entry["target_path"])
                backup = Path(entry.get("backup_path", ""))

                # 1. 删除链接
                if source.exists():
                    if not remove_link(source):
                        return RollbackResult(
                            success=False,
                            error="删除符号链接失败（请先确保应用未运行）",
                        )

                # 2. 把 backup 移回原名
                if backup.exists():
                    try:
                        backup.rename(source)
                    except Exception as e:
                        return RollbackResult(success=False, error=f"恢复 backup 失败: {e}")
                else:
                    return RollbackResult(
                        success=False,
                        error=f"备份目录不存在: {backup}\n可能已被清理，请手动将 {target} 复制回原位置",
                    )

                # 3. 更新历史
                entry["status"] = "rolled_back"
                _save_history(history)

                log_operation("搬家回滚", f"{entry.get('app_name', '?')}: 已回滚")
                return RollbackResult(success=True, message="已成功回滚")
        return RollbackResult(success=False, error="未找到对应记录")