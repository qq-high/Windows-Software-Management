"""
C 盘清理核心服务：
  1. scan(rules, ...)   按规则扫描可清理项（含安全过滤）
  2. preview(items)     生成预览列表
  3. clean(items, ...)   执行清理（默认走回收站）

安全机制：
  - 受保护路径前缀检测（is_protected）
  - 不跟随 Junction/Symlink
  - 跳过最近 min_age_days 内文件
  - 删除前二次校验路径未越界
  - 默认走 send2trash，可切换为永久删除
  - 所有失败/跳过都记录但不阻塞
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from send2trash import send2trash

from app.common.logger import get_logger, log_operation
from app.common.paths import expand_env_vars, is_junction, is_protected
from app.config import PROTECTED_PATH_PATTERNS
from app.models.clean_rule import CleanItem, CleanResult, CleanRule, ScanResult

logger = get_logger("cleaner")


def _stat_size(path: Path) -> int:
    """获取文件/目录大小（目录递归）。"""
    try:
        if path.is_file() and not is_junction(path):
            return path.stat().st_size
        if path.is_dir() and not is_junction(path):
            total = 0
            for entry in path.rglob("*"):
                try:
                    if entry.is_file() and not is_junction(entry):
                        total += entry.stat().st_size
                except (OSError, PermissionError):
                    continue
            return total
    except (OSError, PermissionError):
        pass
    return 0


def _is_recent(path: Path, min_age_days: int) -> bool:
    """判断路径下是否有最近 N 天内被修改的文件（用于跳过）。

    对于目录，递归检查最深子文件的最新 mtime。
    注意：NTFS 目录自身的 mtime 会随子文件更新而刷新，所以**不能**直接看目录 mtime。
    策略：
      - 如果目录里有任何文件 mtime > cutoff，视为"近期" → 跳过
      - 否则（所有子文件都够旧）→ 不跳过
    """
    if min_age_days <= 0:
        return False
    cutoff = time.time() - min_age_days * 86400
    try:
        if path.is_file():
            return path.stat().st_mtime > cutoff
        elif path.is_dir():
            try:
                for child in path.rglob("*"):
                    try:
                        if child.is_file():
                            if child.stat().st_mtime > cutoff:
                                return True  # 有近期文件，整目录视为近期
                    except (OSError, PermissionError):
                        continue
                return False  # 所有子文件都够旧
            except (OSError, PermissionError):
                return False
    except (OSError, PermissionError):
        return False
    return False


def _matches_pattern(name: str, patterns: List[str]) -> bool:
    """检查文件名是否匹配任一通配符（*、?）。空 patterns 返回 True。"""
    if not patterns or patterns == ["*"]:
        return True
    import fnmatch
    for pat in patterns:
        if fnmatch.fnmatch(name.lower(), pat.lower()):
            return True
    return False


@dataclass
class _ScanContext:
    cancel: bool = False


class CleanerService:
    """C 盘清理服务。"""

    def __init__(self):
        self._ctx: Optional[_ScanContext] = None

    def cancel(self):
        if self._ctx:
            self._ctx.cancel = True

    def scan(
        self,
        rules: List[CleanRule],
        progress_cb: Optional[Callable[[int, str], None]] = None,
        filter_categories: Optional[List[str]] = None,
    ) -> ScanResult:
        """扫描所有规则，生成 ScanResult。

        progress_cb: 回调函数 (percent, current_path) -> None
        """
        result = ScanResult()
        self._ctx = _ScanContext()
        start = time.time()

        # 过滤分类
        if filter_categories:
            rules = [r for r in rules if r.category in filter_categories]

        total_rules = len(rules)
        for i, rule in enumerate(rules):
            if self._ctx.cancel:
                result.cancelled = True
                break

            if progress_cb:
                percent = int(i / max(total_rules, 1) * 100)
                progress_cb(percent, f"扫描: {rule.name}")

            try:
                items = self._scan_rule(rule)
                result.items.extend(items)
            except Exception as e:
                logger.warning(f"扫描规则 {rule.id} 失败: {e}")

        result.total_size = sum(item.size_bytes for item in result.items)
        result.elapsed_seconds = time.time() - start

        if progress_cb:
            progress_cb(100, "扫描完成")

        logger.info(
            f"扫描完成: {len(result.items)} 项, 总大小 "
            f"{result.total_size / (1024*1024):.1f} MB, "
            f"耗时 {result.elapsed_seconds:.1f} 秒"
        )
        return result

    def _scan_rule(self, rule: CleanRule) -> List[CleanItem]:
        """扫描单条规则，返回 CleanItem 列表。"""
        items: List[CleanItem] = []

        for raw_path in rule.paths:
            if self._ctx and self._ctx.cancel:
                break
            try:
                expanded = expand_env_vars(raw_path)
                # 处理 * 通配符（如 JetBrains 多版本）
                if "*" in expanded:
                    import glob as glob_mod
                    parent_dir = expanded.split("*")[0]
                    # 如果有 * 用 rglob 处理（粗略）
                    base = Path(expand_env_vars(parent_dir.rstrip("\\/")))
                    if not base.exists():
                        continue
                    for p in base.parent.iterdir():
                        if not p.name.startswith(base.name):
                            continue
                        full = str(p) + expanded[len(parent_dir):]
                        items.extend(self._scan_path(Path(full), rule))
                else:
                    p = Path(expanded)
                    items.extend(self._scan_path(p, rule))
            except Exception as e:
                logger.debug(f"扫描路径 {raw_path} 出错: {e}")
        return items

    def _scan_path(self, path: Path, rule: CleanRule) -> List[CleanItem]:
        """扫描单个具体路径。"""
        items: List[CleanItem] = []
        try:
            if not path.exists():
                return items

            # 受保护路径 → 跳过
            if is_protected(path, PROTECTED_PATH_PATTERNS):
                logger.debug(f"受保护路径，跳过: {path}")
                return items

            # 如果是符号链接/junction → 跳过
            if is_junction(path):
                return items

            if path.is_dir():
                try:
                    for entry in path.iterdir():
                        if self._ctx and self._ctx.cancel:
                            break
                        if is_junction(entry):
                            continue
                        if not _matches_pattern(entry.name, rule.patterns):
                            continue
                        if _is_recent(entry, rule.min_age_days):
                            continue
                        # 子项也做受保护检查
                        if is_protected(entry, PROTECTED_PATH_PATTERNS):
                            continue
                        size = _stat_size(entry)
                        if size <= 0:
                            continue
                        items.append(CleanItem(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            path=str(entry),
                            is_dir=entry.is_dir(),
                            size_bytes=size,
                            risk=rule.risk,
                            reason=rule.description[:100],
                        ))
                except (PermissionError, OSError):
                    pass
            else:
                if _matches_pattern(path.name, rule.patterns):
                    if not _is_recent(path, rule.min_age_days):
                        size = _stat_size(path)
                        if size > 0:
                            items.append(CleanItem(
                                rule_id=rule.id,
                                rule_name=rule.name,
                                path=str(path),
                                is_dir=False,
                                size_bytes=size,
                                risk=rule.risk,
                                reason=rule.description[:100],
                            ))
        except (PermissionError, OSError) as e:
            logger.debug(f"扫描路径失败 {path}: {e}")
        return items

    def clean(
        self,
        items: List[CleanItem],
        use_recycle_bin: bool = True,
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> CleanResult:
        """执行清理。

        use_recycle_bin=True 走 send2trash（安全）；False 则永久删除。
        """
        result = CleanResult()
        total = len(items)
        if total == 0:
            return result

        log_operation("C盘清理", f"开始清理 {total} 项, use_recycle_bin={use_recycle_bin}")

        for i, item in enumerate(items):
            if self._ctx and self._ctx.cancel:
                result.cancelled = True
                break
            if progress_cb:
                percent = int(i / max(total, 1) * 100)
                progress_cb(percent, f"清理: {Path(item.path).name}")

            # 二次安全检查
            try:
                p = Path(item.path)
                if is_protected(p, PROTECTED_PATH_PATTERNS):
                    result.failed_count += 1
                    result.errors.append(f"受保护路径，跳过: {item.path}")
                    continue
                if not p.exists():
                    continue  # 已不存在
                if is_junction(p):
                    result.failed_count += 1
                    result.errors.append(f"符号链接，跳过: {item.path}")
                    continue

                if use_recycle_bin:
                    try:
                        send2trash(str(p))
                        result.deleted_count += 1
                        result.deleted_bytes += item.size_bytes
                    except Exception as e:
                        # 部分 send2trash 失败时回退到永久删除（仅目录）
                        try:
                            if p.is_dir():
                                shutil.rmtree(str(p), ignore_errors=True)
                            else:
                                os.remove(str(p))
                            result.deleted_count += 1
                            result.deleted_bytes += item.size_bytes
                        except Exception as e2:
                            result.failed_count += 1
                            result.errors.append(f"{item.path}: {e2}")
                else:
                    # 永久删除
                    try:
                        if p.is_dir():
                            shutil.rmtree(str(p), ignore_errors=True)
                        else:
                            os.remove(str(p))
                        result.deleted_count += 1
                        result.deleted_bytes += item.size_bytes
                    except Exception as e:
                        result.failed_count += 1
                        result.errors.append(f"{item.path}: {e}")
            except Exception as e:
                result.failed_count += 1
                result.errors.append(f"{item.path}: {e}")

        if progress_cb:
            progress_cb(100, "清理完成")
        log_operation(
            "C盘清理",
            f"完成: 成功 {result.deleted_count}, 失败 {result.failed_count}, "
            f"释放 {result.deleted_bytes / (1024*1024):.1f} MB"
        )
        return result