"""
文档上下文管理器

用于在检索时提供完整的章节上下文，而非孤立切片。
支持决策智能体深度理解文档结构。

来源：src/rag/core/context_manager.py
"""
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List

from langchain_core.documents import Document
from app.core.settings import CHROMA_PERSIST_DIR


@dataclass
class ChunkInfo:
    """文档切片信息"""
    chunk_index: int
    start_index: int
    content_preview: str


@dataclass
class DocumentIndex:
    """原文档索引条目"""
    source: str
    doc_type: str
    total_chunks: int = 0
    full_content: str = ""
    metadata: dict = None
    chunks_info: list = None
    executive_summary: str | None = None
    chapter_summaries: list | None = None
    key_points: list | None = None

    def __post_init__(self):
        if self.metadata is None: self.metadata = {}
        if self.chunks_info is None: self.chunks_info = []


class DocumentContextManager:
    """文档上下文管理器"""

    def __init__(self, index_path: Path | None = None):
        self.index_path = Path(index_path or CHROMA_PERSIST_DIR / "document_index.json")
        self.doc_index: dict[str, DocumentIndex] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def build_index(self, documents: list[Document], splits: list[Document]) -> None:
        splits_by_source: dict[str, list[Document]] = {}
        for split in splits:
            source = split.metadata.get("source", "unknown")
            splits_by_source.setdefault(source, []).append(split)

        docs_by_source: dict[str, list[Document]] = {}
        for doc in documents:
            source = doc.metadata.get("source", "unknown")
            docs_by_source.setdefault(source, []).append(doc)

        self.doc_index = {}
        for source, source_docs in docs_by_source.items():
            merged = "\n\n".join([doc.page_content for doc in source_docs])
            ss = splits_by_source.get(source, [])
            chunks_info = [{"start_index": s.metadata.get("start_index", 0), "content_preview": s.page_content[:100] + "...", "metadata": s.metadata} for s in ss]
            first = source_docs[0]
            self.doc_index[source] = DocumentIndex(source=source, doc_type=first.metadata.get("type", "unknown"), full_content=merged, metadata=first.metadata, chunks_info=chunks_info)
        self._loaded = True

    def save(self) -> None:
        from dataclasses import asdict
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {s: asdict(i) for s, i in self.doc_index.items()}
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)

    def load(self) -> None:
        if not self.index_path.exists():
            raise FileNotFoundError(f"Document index not found: {self.index_path}")
        with open(self.index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.doc_index = {}
        for source, item in data.items():
            item.setdefault('executive_summary', None)
            item.setdefault('chapter_summaries', None)
            item.setdefault('key_points', None)
            self.doc_index[source] = DocumentIndex(**item)
        self._loaded = True

    def get_context_around_chunk(self, source: str, chunk_start_index: int, context_chars: int = 500) -> dict:
        self._ensure_loaded()
        if source not in self.doc_index: return {"error": f"Document not found: {source}"}
        doc = self.doc_index[source]
        content = doc.full_content
        start = max(0, chunk_start_index - context_chars)
        end = min(len(content), chunk_start_index + context_chars)
        return {"source": source, "before": content[start:chunk_start_index].strip(), "current": content[chunk_start_index:min(len(content), chunk_start_index + context_chars)], "after": content[chunk_start_index + context_chars:end].strip()}

    def get_full_document(self, source: str) -> dict:
        self._ensure_loaded()
        if source not in self.doc_index: return {"error": f"Document not found: {source}"}
        doc = self.doc_index[source]
        return {"source": source, "doc_type": doc.doc_type, "content": doc.full_content, "metadata": doc.metadata, "total_chunks": len(doc.chunks_info)}

    def get_chapter_by_header(self, source: str, header_pattern: str) -> dict:
        self._ensure_loaded()
        if source not in self.doc_index: return {"error": f"Document not found: {source}"}
        doc = self.doc_index[source]
        lines = doc.full_content.split('\n')
        chapter_start = None
        chapter_end = None
        for i, line in enumerate(lines):
            if header_pattern.lower() in line.lower():
                chapter_start = i
                for j in range(i + 1, len(lines)):
                    if lines[j].strip().startswith('#') and j > i + 1:
                        chapter_end = j
                        break
                break
        if chapter_start is None: return {"error": f"Chapter not found: {header_pattern}"}
        content = '\n'.join(lines[chapter_start:chapter_end if chapter_end else len(lines)])
        return {"source": source, "chapter_title": lines[chapter_start].strip(), "content": content}

    def get_executive_summary(self, source: str) -> dict:
        self._ensure_loaded()
        if source not in self.doc_index: return {"error": f"Document not found: {source}"}
        doc = self.doc_index[source]
        if not doc.executive_summary: return {"source": source, "executive_summary": None, "message": "Summary not generated"}
        return {"source": source, "doc_type": doc.doc_type, "executive_summary": doc.executive_summary}

    def list_chapter_summaries(self, source: str) -> dict:
        self._ensure_loaded()
        if source not in self.doc_index: return {"error": f"Document not found: {source}"}
        doc = self.doc_index[source]
        if not doc.chapter_summaries: return {"source": source, "chapters": [], "message": "No chapter summaries"}
        chapters = [{"title": c.get("title"), "level": c.get("level"), "summary": c.get("summary"), "key_points": c.get("key_points", [])} for c in doc.chapter_summaries]
        return {"source": source, "total_chapters": len(chapters), "chapters": chapters}

    def search_key_points(self, query: str, sources: list[str] | None = None) -> dict:
        self._ensure_loaded()
        results = []
        search_docs = sources or list(self.doc_index.keys())
        for source in search_docs:
            if source not in self.doc_index: continue
            doc = self.doc_index[source]
            if not doc.key_points: continue
            for point in doc.key_points:
                if query.lower() in point.lower():
                    results.append({"source": source, "point": point})
        return {"query": query, "total_matches": len(results), "matches": results}


_context_manager = None


def get_context_manager() -> DocumentContextManager:
    global _context_manager
    if _context_manager is None:
        _context_manager = DocumentContextManager()
        if _context_manager.index_path.exists():
            _context_manager.load()
    return _context_manager


__all__ = ["ChunkInfo", "DocumentIndex", "DocumentContextManager", "get_context_manager"]