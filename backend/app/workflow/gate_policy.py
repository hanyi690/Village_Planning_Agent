"""Declarative gate-route policy for the post-L3 stage chain.

A1: 路由策略表化 —— 把 root_graph.py 里散落的 7 个 route_after_* 的
if-else 分支收敛成一张 ``(source_stage, gate_route) -> (action, *args)``
策略表。路由函数只做“查表 + 特例”，不再各自维护分支语义。

每个策略是 ``(action, arg1, arg2)`` 元组：

- ``("forward", target)``            -> 直接跳转 target
- ``("retry", stage, retry_target)`` -> 走根图 ``_retry_or_human`` 重试预算检查
- ``("retry_from_route", stage)``    -> retry 目标由 gate route 后缀派生（validate）
- ``("human",)``                     -> human_review
- ``("end",)``                       -> END
- ``("end_diagnostic",)``            -> END_DIAGNOSTIC
- ``("revision_or_human",)``         -> 有修订目标走 revision_dispatch，否则 HUMAN

GATE_LOAD_FAILED 不属于策略表：统一由 ``normalize_gate_route`` 折叠成
END_DIAGNOSTIC 哨兵（A3），因此表内不需要为每个阶段重复这一行。
"""

from __future__ import annotations

from typing import Dict, Tuple

GATE_ROUTE_POLICY: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "target_projection": {
        "PASS": ("forward", "ground"),
        "REPAIR": ("retry", "target_projection", "target_projection"),
        "REVISE": ("retry", "target_projection", "target_projection"),
        "L3": ("retry", "target_projection", "target_projection"),
    },
    "ground": {
        "PASS": ("forward", "select"),
        "EXPLORE": ("retry", "ground", "ground"),
    },
    "select": {
        "PASS": ("forward", "execute"),
        "RETRY_GROUND": ("retry", "select", "ground"),
    },
    "validate": {
        "PASS": ("forward", "reconcile"),
        "END_DIAGNOSTIC": ("forward", "reconcile"),
        "RETRY_EXECUTE": ("retry_from_route", "validate"),
        "RETRY_SELECT": ("retry_from_route", "validate"),
        "RETRY_GROUND": ("retry_from_route", "validate"),
        "RETRY_TARGET_PROJECTION": ("retry_from_route", "validate"),
        "RETRY_L3": ("revision_or_human",),
    },
    "reconcile": {
        "PASS": ("forward", "deliver"),
        "END_DIAGNOSTIC": ("forward", "deliver"),
        "RETRY_EXECUTE": ("retry", "reconcile", "execute"),
        "RETRY_L3": ("human",),
    },
    "deliver": {
        "PASS": ("end",),
    },
}

#: 未命中表项时的兜底策略（fail-closed：除 deliver 外一律 HUMAN）。
DEFAULT_GATE_ROUTE_POLICY: Dict[str, Tuple[str, ...]] = {
    "target_projection": ("human",),
    "ground": ("human",),
    "select": ("human",),
    "validate": ("human",),
    "reconcile": ("human",),
    "deliver": ("end_diagnostic",),
}

#: 参与 gate 路由的 post-L3 阶段。``execute`` 是显式豁免（A4）：EXECUTE
#: 阶段不产出 gate artifact，路由只看 fatal_error，见 root_graph 注释。
GATE_ROUTED_STAGES: Tuple[str, ...] = (
    "target_projection",
    "ground",
    "select",
    "validate",
    "reconcile",
    "deliver",
)

__all__ = [
    "DEFAULT_GATE_ROUTE_POLICY",
    "GATE_ROUTE_POLICY",
    "GATE_ROUTED_STAGES",
]
