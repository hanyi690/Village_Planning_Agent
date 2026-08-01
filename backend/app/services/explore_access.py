"""ExploreAccess — EXPLORE 统一读路径门面（快照优先）。

``get_context_block(session_id, kind, **params)`` 是会话数据的单一访问入口：
  - 快照优先：内存缓存 -> 版本化 bundle 快照 -> 实时构建（兜底）；
  - 语义优先：返回 token 预算内的压缩形态，绝不倾泻原始数据；
  - 任意 agent 可复用（analysis / explore / gis 都经同一门面读会话数据）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_KINDS: Dict[str, Callable[..., Any]] = {}


def _register(kind: str, func: Callable[..., Any]) -> None:
    _KINDS[kind] = func


def _register_all() -> None:
    from app.agent.explore.summaries import (
        build_report_summary_index,
        build_spatial_cognition,
    )
    from app.tools.access.bundle import (
        bundle_overview_impl,
        spatial_context_impl,
        spatial_features_impl,
    )
    from app.tools.access.knowledge import knowledge_graph_impl
    from app.tools.access.rag import rag_search_impl
    from app.tools.access.reports import layer_reports_impl

    _register("overview", bundle_overview_impl)
    _register("spatial_context", spatial_context_impl)
    _register("spatial_features", spatial_features_impl)
    _register("layer_reports", layer_reports_impl)
    _register("knowledge_graph", knowledge_graph_impl)
    _register("rag_search", rag_search_impl)
    _register("report_summary_index", build_report_summary_index)
    _register("spatial_cognition", build_spatial_cognition)


class ExploreAccess:
    """Unified session-data read facade (snapshot-first, semantic-first)."""

    _instance: Optional["ExploreAccess"] = None

    def __init__(self):
        if not _KINDS:
            _register_all()

    @classmethod
    def get_instance(cls) -> "ExploreAccess":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def kinds(self) -> list:
        return sorted(_KINDS.keys())

    async def get_context_block(
        self,
        session_id: str,
        kind: str,
        **params: Any,
    ) -> Dict[str, Any]:
        """Return a token-budgeted context block for the requested kind.

        Raises:
            ValueError: unknown kind or empty session_id.
        """
        if not session_id:
            return {"success": False, "error": "session_id 不能为空"}
        func = _KINDS.get(kind)
        if func is None:
            return {
                "success": False,
                "error": f"未知 context kind: {kind}（可选: {sorted(_KINDS.keys())}）",
            }
        try:
            payload = await func(session_id=session_id, **params)
            if isinstance(payload, dict):
                payload.setdefault("success", True)
                payload.setdefault("kind", kind)
            return payload
        except Exception as e:
            logger.error("[ExploreAccess] kind=%s failed: %s", kind, e, exc_info=True)
            return {"success": False, "kind": kind, "error": str(e)}


__all__ = ["ExploreAccess"]
