"""rag_search / index_bundle_texts — 会话文本清单检索。

文本源收口：bundle 快照的 ``documents.planning_texts`` 是会话可检索文本的
权威清单。检索时以清单为准：
  - 提供 source/name 过滤时，只在清单命中范围内做关键词检索；
  - 未过滤时，先尝试向量库语义检索（仅收进清单内已有同名文档的结果），
    再补关键词兜底，保证口径统一、无全库漂移。
所有结果经 TokenBudget 预算标注。
"""

from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .shared import budget_check, resolve_bundle, tool_reply

_SESSION_SOURCES = {"village_data", "task_description", "constraints", "upload", "project_doc"}


def _rag_service():
    from app.infrastructure.rag.service import RagService

    return RagService.get_instance()


def _indexed_sources() -> set:
    try:
        docs = _rag_service().list_documents()
        return {str(d.get("source") or "") for d in docs}
    except Exception:
        return set()


def _query_chars(query: str) -> List[str]:
    return [c for c in query if c.strip() and not c.isspace()]


def _snippet(content: str, query: str, width: int = 120) -> str:
    if not content:
        return ""
    idx = len(content)
    for c in _query_chars(query):
        hit = content.find(c)
        if 0 <= hit < idx:
            idx = hit
    start = max(0, idx - width // 3)
    return content[start : start + width]


def _keyword_search(
    texts: List[Dict[str, Any]],
    query: str,
    top_k: int,
) -> List[Dict[str, Any]]:
    chars = _query_chars(query)
    if not chars:
        return []
    scored: List[Dict[str, Any]] = []
    for t in texts:
        content = str(t.get("content") or "")
        if not content:
            continue
        hits = sum(1 for c in chars if c in content)
        if hits == 0:
            continue
        scored.append({
            "source": t.get("source"),
            "name": t.get("name"),
            "category": t.get("category"),
            "score": round(hits / len(chars), 3),
            "snippet": _snippet(content, query),
        })
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


async def rag_search_impl(
    session_id: str,
    query: str,
    source: str = "",
    name: str = "",
    top_k: int = 5,
) -> Dict[str, Any]:
    if not query:
        return {"success": False, "error": "query 不能为空"}

    bundle = await resolve_bundle(session_id)
    inventory = list(bundle.documents.planning_texts or [])

    if source and source not in _SESSION_SOURCES:
        return {"success": False, "error": f"未知 source: {source}（可选: {'/'.join(sorted(_SESSION_SOURCES))}）"}

    if source or name:
        filtered = [
            t for t in inventory
            if (not source or t.get("source") == source)
            and (not name or name in str(t.get("name") or ""))
        ]
        if not filtered:
            return budget_check({"query": query, "results": [], "scope": "filtered", "matched_inventory": 0})
        results = _keyword_search(filtered, query, top_k)
        return budget_check({
            "query": query,
            "results": results,
            "scope": "filtered",
            "matched_inventory": len(filtered),
        })

    # No filters — vector search first (scoped to indexed inventory), then keyword fallback.
    results: List[Dict[str, Any]] = []
    indexed = _indexed_sources()
    if indexed:
        try:
            hits = _rag_service().search(query, top_k=top_k)
            for h in hits:
                src = str((h.get("metadata") or {}).get("source") or "")
                if src in indexed and any(
                    str(t.get("name") or "") == src for t in inventory
                ):
                    results.append({
                        "source": "vector",
                        "name": src,
                        "doc_type": (h.get("metadata") or {}).get("doc_type", ""),
                        "content": str(h.get("content") or "")[:600],
                    })
        except Exception as e:
            results = [{"vector_error": str(e)}]

    keyword_hits = _keyword_search(inventory, query, top_k)
    seen = {r.get("name") for r in results}
    results.extend(k for k in keyword_hits if k.get("name") not in seen)

    return budget_check({
        "query": query,
        "results": results,
        "scope": "session_inventory",
        "inventory_size": len(inventory),
        "indexed_in_inventory": sum(
            1 for t in inventory if str(t.get("name") or "") in indexed
        ),
    })


@tool
async def rag_search(
    session_id: str = "",
    query: str = "",
    source: str = "",
    name: str = "",
    top_k: int = 5,
    state: Annotated[Optional[Dict[str, Any]], InjectedState()] = None,
) -> str:
    """在会话文本清单内检索相关内容。

    ``source`` 限定来源（village_data/task_description/constraints/upload/
    project_doc），``name`` 限定文档名（子串）。未过滤时综合向量库语义检索
    与清单关键词兜底。返回带来源与摘要片段的结果列表。
    """
    if not session_id and state:
        session_id = state.get("session_id", "")
    return tool_reply(await rag_search_impl(session_id, query, source, name, top_k))


async def index_bundle_texts_impl(
    session_id: str,
    source: str = "",
) -> Dict[str, Any]:
    """将 bundle 清单中尚未进入向量库的文本补索引（渐进启用）。"""
    bundle = await resolve_bundle(session_id)
    inventory = list(bundle.documents.planning_texts or [])
    if source:
        inventory = [t for t in inventory if t.get("source") == source]

    indexed = _indexed_sources()
    service = _rag_service()
    added = 0
    skipped = 0
    errors = []

    with TemporaryDirectory(prefix="bundle_text_") as tmp:
        for t in inventory:
            name = str(t.get("name") or "untitled")
            if name in indexed:
                skipped += 1
                continue
            content = str(t.get("content") or "")
            if not content.strip():
                skipped += 1
                continue
            md_path = Path(tmp) / f"{re.sub(r'[^\\w\\u4e00-\\u9fff.-]', '_', name)}.md"
            try:
                md_path.write_text(content, encoding="utf-8")
                result = service.add_markdown_document(str(md_path), use_llm_inference=False)
                status = result.get("status")
                if status == "success":
                    added += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    errors.append(f"{name}: {status}")
            except Exception as e:
                errors.append(f"{name}: {e}")

    return budget_check({"added": added, "skipped": skipped, "errors": errors[:10]})


@tool
async def index_bundle_texts(
    session_id: str = "",
    source: str = "",
    state: Annotated[Optional[Dict[str, Any]], InjectedState()] = None,
) -> str:
    """把会话清单中尚未进向量库的文本补索引（渐进同步）。

    幂等：已在库中的跳过。``source`` 限定仅同步某类来源。
    """
    if not session_id and state:
        session_id = state.get("session_id", "")
    return tool_reply(await index_bundle_texts_impl(session_id, source))


__all__ = [
    "rag_search",
    "rag_search_impl",
    "index_bundle_texts",
    "index_bundle_texts_impl",
]
