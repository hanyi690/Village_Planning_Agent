"""
统一 Markdown 切片器

配置驱动，动态策略，合并原有 5 个独立切片器类。
支持：pattern-based 切分、parent-child 模式、语义切分。

来源：src/rag/slicing/slicer.py
"""
import logging
import re
from typing import List, Dict, Optional
from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """切片数据结构"""
    content: str
    metadata: Dict
    parent_id: Optional[str] = None


@dataclass
class SlicerConfig:
    """切片配置"""
    split_on: List[str] = None
    chunk_size: int = 2000
    overlap: int = 400
    min_chunk: int = 100
    parent_child: bool = False
    child_size: int = 400
    parent_size: int = 2000
    semantic: bool = False
    max_chunk: int = 2500


class UnifiedMarkdownSlicer:
    """统一 Markdown 切片器"""

    SPLIT_PATTERNS_RE: Dict[str, List] = {
        "policy": [re.compile(r'\n(?=第\s*[一二三四五六七八九十百千万0-9]+\s*条)')],
        "case": [re.compile(r'\n(?=[一二三四五六七八九十]+[、.])'), re.compile(r'\n(?=\d+\.[^\d])')],
        "standard": [re.compile(r'\n(?=\d+\.\d+(?:\.\d+)?)'), re.compile(r'\n(?=第\s*\d+\s*条)')],
        "guide": [re.compile(r'\n(?=#{1,3}\s)')],
        "textbook": [re.compile(r'\n(?=#{1,3}\s)'), re.compile(r'\n(?=第[一二三四五六七八九十百]+章)')],
    }

    NEWLINE_NORMALIZE_RE = re.compile(r'\r\n|\r')
    MULTIPLE_NEWLINES_RE = re.compile(r'\n\s*\n\s*\n+')
    OCR_MARKER_RE = re.compile(r'^#{1,6}\s+Page\s+\d+', re.MULTILINE)
    OCR_WRAPPER_RE = re.compile(r'\*\[Image OCR\]\n|\n\[End OCR\]\*\s*')

    CONFIGS: Dict[str, SlicerConfig] = {
        "policy": SlicerConfig(split_on=[r'\n(?=第\s*[一二三四五六七八九十百千万0-9]+\s*条)'], chunk_size=2500, overlap=500, min_chunk=50, max_chunk=2500),
        "case": SlicerConfig(split_on=[r'\n(?=[一二三四五六七八九十]+[、.])', r'\n(?=\d+\.[^\d])'], chunk_size=2000, overlap=400, min_chunk=200, max_chunk=2000),
        "standard": SlicerConfig(split_on=[r'\n(?=\d+\.\d+(?:\.\d+)?)', r'\n(?=第\s*\d+\s*条)'], chunk_size=1500, overlap=300, min_chunk=80, max_chunk=1500),
        "guide": SlicerConfig(split_on=[r'\n(?=#{1,3}\s)'], chunk_size=1800, overlap=350, min_chunk=150, max_chunk=1800),
        "report": SlicerConfig(parent_child=True, child_size=400, parent_size=2000, chunk_size=2000, overlap=400, min_chunk=100),
        "textbook": SlicerConfig(split_on=[r'\n(?=#{1,3}\s)', r'\n(?=第[一二三四五六七八九十百]+章)'], chunk_size=1800, overlap=350, min_chunk=150),
        "laws": SlicerConfig(split_on=[r'\n(?=第\s*[一二三四五六七八九十百千万0-9]+\s*条)'], chunk_size=2500, overlap=500, min_chunk=50, max_chunk=2500),
        "plans": SlicerConfig(split_on=[r'\n(?=#{1,3}\s)', r'\n(?=第[一二三四五六七八九十百]+章)'], chunk_size=2000, overlap=400, min_chunk=100, max_chunk=2000),
        "domain": SlicerConfig(split_on=[r'\n(?=#{1,3}\s)', r'\n(?=第[一二三四五六七八九十百]+章)'], chunk_size=1800, overlap=350, min_chunk=150, max_chunk=1800),
        "default": SlicerConfig(chunk_size=2500, overlap=500, min_chunk=100, max_chunk=2500),
    }

    def slice(self, content: str, doc_type: str, metadata: Optional[Dict] = None) -> List[Chunk]:
        content = self._preprocess(content)
        content = self._remove_ocr_markers(content)
        config = self.CONFIGS.get(doc_type, self.CONFIGS["default"])
        if config.parent_child:
            chunks = self._slice_parent_child(content, config, metadata)
        else:
            chunks = self._slice_by_pattern(content, config, metadata, doc_type)
        chunks = self._check_chunk_lengths(chunks, content, config)
        return chunks

    def _preprocess(self, text: str) -> str:
        text = self.NEWLINE_NORMALIZE_RE.sub('\n', text)
        text = self.MULTIPLE_NEWLINES_RE.sub('\n\n', text)
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.strip()
            if stripped.count('|') > 3: continue
            if len(stripped) == 1 and '\u4e00' <= stripped <= '\u9fff': continue
            if stripped and all(c in '．。·.…' for c in stripped): continue
            cleaned.append(line)
        return self.MULTIPLE_NEWLINES_RE.sub('\n\n', '\n'.join(cleaned)).strip()

    def _remove_ocr_markers(self, content: str) -> str:
        content = self.OCR_MARKER_RE.sub('', content)
        content = self.OCR_WRAPPER_RE.sub('', content)
        return self.MULTIPLE_NEWLINES_RE.sub('\n\n', content).strip()

    def _slice_by_pattern(self, content: str, config: SlicerConfig, metadata: Optional[Dict], doc_type: str) -> List[Chunk]:
        patterns = self.SPLIT_PATTERNS_RE.get(doc_type, [])
        if not patterns and config.split_on:
            patterns = [re.compile(p) for p in config.split_on]
        if not patterns:
            return self._fallback_split(content, config, metadata)
        slices = []
        for cp in patterns:
            parts = cp.split(content)
            if len(parts) > 1:
                current = ""
                for part in parts:
                    part = part.strip()
                    if not part: continue
                    if len(current) + len(part) < config.max_chunk:
                        current += "\n" + part
                    else:
                        if current and len(current) >= config.min_chunk: slices.append(current.strip())
                        current = part
                if current and len(current) >= config.min_chunk: slices.append(current.strip())
                break
        if not slices: return self._fallback_split(content, config, metadata)
        return self._create_chunks(slices, metadata)

    def _slice_parent_child(self, content: str, config: SlicerConfig, metadata: Optional[Dict]) -> List[Chunk]:
        ps = RecursiveCharacterTextSplitter(chunk_size=config.parent_size, chunk_overlap=config.overlap, length_function=len)
        parent_texts = ps.split_text(content)
        cs = RecursiveCharacterTextSplitter(chunk_size=config.child_size, chunk_overlap=min(100, config.child_size // 4), length_function=len)
        chunks = []
        for pi, pt in enumerate(parent_texts):
            pid = f"parent_{pi}"
            cts = cs.split_text(pt)
            for ci, ct in enumerate(cts):
                chunks.append(Chunk(content=ct, metadata={**(metadata or {}), "parent_id": pid, "child_index": ci, "total_children": len(cts)}, parent_id=pid))
        return chunks

    def _fallback_split(self, content: str, config: SlicerConfig, metadata: Optional[Dict]) -> List[Chunk]:
        s = RecursiveCharacterTextSplitter(chunk_size=config.chunk_size, chunk_overlap=config.overlap, length_function=len)
        return self._create_chunks(s.split_text(content), metadata)

    def _create_chunks(self, slices: List[str], metadata: Optional[Dict]) -> List[Chunk]:
        result = []
        idx = 0
        for s in slices:
            if self._is_quality_chunk(s):
                result.append(Chunk(content=s, metadata={**(metadata or {}), "chunk_index": idx}))
                idx += 1
        return result

    def _is_quality_chunk(self, text: str) -> bool:
        if len(text.strip()) < 30: return False
        if sum(1 for c in text if '\u4e00' <= c <= '\u9fff') / len(text) < 0.05: return False
        return True

    def _check_chunk_lengths(self, chunks: List[Chunk], content: str, config: SlicerConfig) -> List[Chunk]:
        if not chunks: return chunks
        oversized = [c for c in chunks if len(c.content) > config.max_chunk]
        if oversized: return self._fallback_split(content, config, chunks[0].metadata)
        return chunks


class SlicingStrategyFactory:
    """切片策略工厂（向后兼容）"""
    _slicer = UnifiedMarkdownSlicer()

    @classmethod
    def get_strategy(cls, doc_type: str) -> UnifiedMarkdownSlicer:
        return cls._slicer

    @classmethod
    def slice_document(cls, content: str, doc_type: str, metadata: Optional[Dict] = None) -> List[str]:
        return [c.content for c in cls._slicer.slice(content, doc_type, metadata)]

    @classmethod
    def register_strategy(cls, doc_type: str, config: SlicerConfig) -> None:
        cls._slicer.CONFIGS[doc_type] = config


__all__ = ["Chunk", "SlicerConfig", "UnifiedMarkdownSlicer", "SlicingStrategyFactory"]