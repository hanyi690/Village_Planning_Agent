"""
RAG knowledge appendix appender.

Appends a formatted appendix section to the planning document,
listing all RAG knowledge sources grouped by dimension with labels.
"""

import logging
from typing import Any, Dict, List

from app.services.report_store import ReportStore

logger = logging.getLogger(__name__)

_TYPE_LABELS = {
    "policy": "法规",
    "standard": "标准",
    "textbook": "教材",
    "case": "案例",
    "planning": "上位规划",
    "guide": "指南",
}


class RAGAppender:

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.store = ReportStore.get_instance()

    async def append(self, document: str) -> str:
        parts = ["", "## 附录：知识来源与参考依据", ""]

        for layer in [1, 2, 3]:
            try:
                reports = await self.store.get_layer_reports_with_sources(
                    self.session_id, layer
                )
            except Exception as e:
                logger.warning(f"[RAGAppender] Failed to fetch layer {layer}: {e}")
                continue

            layer_parts = []
            for dim_key, data in reports.items():
                ks = data.get("knowledge_sources")
                if not ks:
                    continue
                chunks = self._extract_chunks(ks)
                if not chunks:
                    continue
                dim_name = self._get_dimension_name(dim_key)
                sources = self._dedup_sources(chunks)
                if sources:
                    layer_parts.append(f"### 【Layer{layer} - {dim_name}】")
                    for display_name, doc_type in sources:
                        label = _TYPE_LABELS.get(doc_type, doc_type)
                        layer_parts.append(f"- [{label}] {display_name}")
                    layer_parts.append("")

            if layer_parts:
                parts.extend(layer_parts)

        if len(parts) <= 3:
            return document

        return document + "\n".join(parts)

    @staticmethod
    def _extract_chunks(ks: Any) -> List[Dict]:
        if isinstance(ks, dict):
            chunks = ks.get("retrieved_chunks", [])
            if isinstance(chunks, list):
                return chunks
        if isinstance(ks, list):
            return [c for c in ks if isinstance(c, dict)]
        return []

    @staticmethod
    def _dedup_sources(chunks: List[Dict]) -> List[tuple]:
        seen = set()
        result = []
        for c in chunks:
            title = c.get("title", "")
            doc_type = c.get("doc_type", "")
            source = c.get("source", "")
            if not title and source:
                title, doc_type = RAGAppender._lookup_source(source)
            if not title and source:
                title = source.rsplit("_minerU_parsed", 1)[0].removesuffix(".md").strip()
            if title and title not in seen:
                seen.add(title)
                result.append((title, doc_type))
        return result

    @staticmethod
    def _lookup_source(source: str) -> tuple:
        try:
            import json
            from pathlib import Path
            cache_path = Path(__file__).parent.parent.parent.parent.parent.parent / "data" / "RAG_doc" / "_cache" / "source_metadata_map.json"
            if not hasattr(RAGAppender, '_source_map'):
                if cache_path.exists():
                    RAGAppender._source_map = json.loads(cache_path.read_text("utf-8"))
                else:
                    RAGAppender._source_map = {}
            info = RAGAppender._source_map.get(source, {})
            return info.get("title", ""), info.get("doc_type", "")
        except Exception:
            return "", ""

    def _get_dimension_name(self, dim_key: str) -> str:
        try:
            from app.config.loader import load_phases_config
            phases = load_phases_config()
            for phase in phases.get("phases", []):
                for dim in phase.get("dimensions", []):
                    if dim.get("key") == dim_key:
                        return dim.get("name", dim_key)
        except Exception:
            pass
        return dim_key
