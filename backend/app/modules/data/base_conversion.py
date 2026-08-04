"""基数转换 — 三调 DLBM → 规划用途 GHYTBM (附录5) 转换.

这是 HUMAN_PLANNING_WORKFLOW §8 要求的"现状→规划第一步"。
转换表来源: dlbm_to_ghytbm.yaml (单一真相源).

两种转换类型:
  - 一一对应: 确定性, 直接返回
  - 一对多: 需消歧, 返回主映射 + 可选替代

用法:
    from app.modules.data.base_conversion import lookup_ghytbm

    ghytbm = lookup_ghytbm("0101")       # -> "1100" (耕地)
    info = lookup_ghytbm_with_info("0301")  # -> ("1340", "一对多", "商品林")
"""

from typing import Dict, Optional, Tuple

from app.modules.schema.advisory_crosswalks import (
    get_ghytbm_for_dlbm,
    get_ghytbm_conversion_info,
)


def lookup_ghytbm(dlbm: str) -> str:
    """DLBM -> GHYTBM 基数转换.

    对"一一对应"类型直接返回 GHYTBM 编码。
    对"一对多"类型返回主映射（默认选项）。
    对无映射的 DLBM 返回空字符串。

    Args:
        dlbm: 三调编码 (4 位, 如 "0101").

    Returns:
        GHYTBM 编码 (4 位, 如 "1100"), 或空字符串。
    """
    return get_ghytbm_for_dlbm(dlbm)


def lookup_ghytbm_with_info(dlbm: str) -> Tuple[str, str, str]:
    """DLBM -> GHYTBM 基数转换（含转换类型和条件信息）.

    Returns:
        (ghytbm, conversion_type, condition):
        - ghytbm: GHYTBM 编码 (或空)
        - conversion_type: "一一对应" / "一对多" / ""
        - condition: 消歧条件 (仅"一对多"时有意义)
    """
    return get_ghytbm_conversion_info(dlbm)


def is_ambiguous(dlbm: str) -> bool:
    """判断该 DLBM 是否存在一对多消歧需求."""
    _ghytbm, ctype, _cond = get_ghytbm_conversion_info(dlbm)
    return ctype == "一对多"


def get_alternative_ghytbms(dlbm: str) -> Dict[str, str]:
    """获取一对多 DLBM 的替代映射选项.

    Returns:
        {ghytbm: condition, ...} 例如:
        {"1340": "商品林", "1350": "生态林"}
    """
    from app.modules.schema.encodings.dicts.loader import get_center
    center = get_center()
    dlbm_ghytbm = center.get("dlbm_to_ghytbm")
    raw = dlbm_ghytbm.raw.get("mappings", []) if dlbm_ghytbm else []
    result: Dict[str, str] = {}
    for entry in raw:
        if entry.get("dlbm") == dlbm and entry.get("conversion_type") == "一对多":
            alt = entry.get("alternative_ghytbm", "")
            alt_cond = entry.get("alternative_condition", "")
            if alt:
                result[entry.get("ghytbm", "")] = entry.get("condition", "")
                result[alt] = alt_cond
    return result


__all__ = [
    "lookup_ghytbm",
    "lookup_ghytbm_with_info",
    "is_ambiguous",
    "get_alternative_ghytbms",
]