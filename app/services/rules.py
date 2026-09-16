"""
加载内置清理规则库。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from app.common.logger import get_logger
from app.config import RULES_FILE
from app.models.clean_rule import CleanRule

logger = get_logger("rules")


def load_default_rules() -> List[CleanRule]:
    """从 default_rules.json 加载所有规则。"""
    if not RULES_FILE.exists():
        logger.error(f"规则库文件不存在: {RULES_FILE}")
        return []
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        rules: List[CleanRule] = []
        for item in data.get("rules", []):
            try:
                rule = CleanRule(
                    id=item["id"],
                    category=item.get("category", "其他"),
                    name=item["name"],
                    description=item.get("description", ""),
                    paths=item.get("paths", []),
                    patterns=item.get("patterns", ["*"]),
                    min_age_days=item.get("min_age_days", 1),
                    risk=item.get("risk", "safe"),
                    requires_admin=item.get("requires_admin", False),
                    enabled_by_default=item.get("enabled_by_default", True),
                )
                rules.append(rule)
            except (KeyError, TypeError) as e:
                logger.warning(f"跳过无效规则: {item.get('id', '?')} - {e}")
        logger.info(f"已加载 {len(rules)} 条清理规则")
        return rules
    except Exception as e:
        logger.error(f"加载规则库失败: {e}")
        return []


def group_by_category(rules: List[CleanRule]) -> dict:
    """按 category 分组返回字典。"""
    result: dict = {}
    for r in rules:
        result.setdefault(r.category, []).append(r)
    return result