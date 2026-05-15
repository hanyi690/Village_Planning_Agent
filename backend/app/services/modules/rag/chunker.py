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
        "case": SlicerConfig(parent_child=True, child_size=400, parent_size=2000, chunk_size=2000, overlap=400, min_chunk=200),
        "standard": SlicerConfig(split_on=[r'\n(?=\d+\.\d+(?:\.\d+)?)', r'\n(?=第\s*\d+\s*条)'], chunk_size=1500, overlap=300, min_chunk=80, max_chunk=1500),
        "guide": SlicerConfig(parent_child=True, child_size=400, parent_size=1800, chunk_size=1800, overlap=350, min_chunk=150),
        "report": SlicerConfig(parent_child=True, child_size=400, parent_size=2000, chunk_size=2000, overlap=400, min_chunk=100),
        "textbook": SlicerConfig(parent_child=True, child_size=400, parent_size=1800, chunk_size=1800, overlap=350, min_chunk=150),
        "laws": SlicerConfig(split_on=[r'\n(?=第\s*[一二三四五六七八九十百千万0-9]+\s*条)'], chunk_size=2500, overlap=500, min_chunk=50, max_chunk=2500),
        "plans": SlicerConfig(parent_child=True, child_size=400, parent_size=2000, chunk_size=2000, overlap=400, min_chunk=100),
        "domain": SlicerConfig(parent_child=True, child_size=400, parent_size=1800, chunk_size=1800, overlap=350, min_chunk=150),
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


__all__ = ["Chunk", "SlicerConfig", "UnifiedMarkdownSlicer", "SlicingStrategyFactory", "LLMBoundaryDetector", "SemanticChunkScorer", "EnhancedMarkdownSlicer"]


# ==========================================
# LLM 辅助切分（v5.0 新增）
# ==========================================

class LLMBoundaryDetector:
    """LLM 辅助语义边界检测"""

    def __init__(self):
        from app.core.llm import create_flash_llm
        self.llm = create_flash_llm(max_tokens=300, temperature=0.1)

    async def validate_boundary_async(self, left_context: str, right_context: str) -> dict:
        """
        校验边界是否合理

        Returns:
            {"should_split": bool, "reason": str}
        """
        prompt = f"""判断以下两段文本是否应该在它们之间切分。

左侧文本结尾：
{left_context[-300:]}

右侧文本开头：
{right_context[:300]}

判断标准：
1. 主题是否转换（从一个主题转向另一个主题）
2. 论述是否完整（左侧是否有完整结尾，右侧是否有完整开头）
3. 语义连贯性（两段是否属于同一论述）

返回 JSON 格式：{{"should_split": true/false, "reason": "简短理由"}}"""

        try:
            response = await self.llm.ainvoke(prompt)
            import json
            # 尝试解析 JSON
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            result = json.loads(content)
            return result
        except Exception as e:
            logger.warning(f"[LLMBoundaryDetector] Validation failed: {e}")
            return {"should_split": True, "reason": "fallback to split"}

    async def suggest_boundary_async(self, context: str) -> int:
        """
        建议新的边界位置

        Returns:
            相对于 context 开头的偏移量
        """
        prompt = f"""在以下文本中找到最佳切分位置。

文本：
{context}

要求：
1. 找到语义完整的切分点（如段落结束、论述完成）
2. 返回切分点的字符偏移量（从 0 开始）

返回 JSON 格式：{{"boundary_offset": 数字}}"""

        try:
            response = await self.llm.ainvoke(prompt)
            import json
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            result = json.loads(content)
            return result.get("boundary_offset", len(context) // 2)
        except Exception as e:
            logger.warning(f"[LLMBoundaryDetector] Suggestion failed: {e}")
            return len(context) // 2


class SemanticChunkScorer:
    """切片语义完整性评分"""

    def __init__(self):
        from app.core.llm import create_flash_llm
        self.llm = create_flash_llm(max_tokens=200, temperature=0.1)

    async def score_chunk_async(self, chunk: str) -> dict:
        """
        评估 chunk 的语义完整性

        Returns:
            {"score": float, "issues": List[str]}
        """
        prompt = f"""评估以下文本片段的语义完整性（0-1分）。

文本片段：
{chunk[:1500]}

评分标准：
1. 主题一致性（是否围绕单一主题）- 0.4分
2. 论述完整性（是否有完整的开头和结尾）- 0.3分
3. 信息密度（是否包含有效信息）- 0.3分

返回 JSON 格式：{{"score": 0.85, "issues": ["问题描述1", "问题描述2"]}}"""

        try:
            response = await self.llm.ainvoke(prompt)
            import json
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            result = json.loads(content)
            return result
        except Exception as e:
            logger.warning(f"[SemanticChunkScorer] Scoring failed: {e}")
            return {"score": 0.5, "issues": ["scoring failed"]}


class EnhancedMarkdownSlicer(UnifiedMarkdownSlicer):
    """
    增强版切分器：支持 LLM 辅助

    流程：
    1. 正则初切
    2. LLM 边界校验（可选）
    3. 语义评分（可选）
    4. 返回高质量 chunks
    """

    def __init__(self, use_llm: bool = False):
        super().__init__()
        self.use_llm = use_llm
        self.llm_detector = LLMBoundaryDetector() if use_llm else None
        self.chunk_scorer = SemanticChunkScorer() if use_llm else None

    async def slice_async(
        self,
        content: str,
        doc_type: str,
        metadata: Optional[Dict] = None,
        validate_boundaries: bool = True,
        score_chunks: bool = False
    ) -> List[Chunk]:
        """
        异步切分（支持 LLM 辅助）

        Args:
            content: 文档内容
            doc_type: 文档类型
            metadata: 元数据
            validate_boundaries: 是否校验边界
            score_chunks: 是否评分

        Returns:
            Chunk 列表
        """
        # 1. 正则初切
        chunks = self.slice(content, doc_type, metadata)

        if not self.use_llm or not self.llm_detector:
            return chunks

        # 2. LLM 边界校验
        if validate_boundaries and len(chunks) > 1:
            chunks = await self._validate_boundaries_async(content, chunks)

        # 3. 语义评分
        if score_chunks and self.chunk_scorer:
            chunks = await self._score_and_filter_async(chunks)

        return chunks

    async def _validate_boundaries_async(self, content: str, chunks: List[Chunk]) -> List[Chunk]:
        """校验边界并调整"""
        validated_chunks = []

        for i, chunk in enumerate(chunks):
            # 检查与前一个 chunk 的边界
            if i > 0 and chunks[i-1]:
                left_context = chunks[i-1].content
                right_context = chunk.content

                result = await self.llm_detector.validate_boundary_async(left_context, right_context)

                if not result.get("should_split", True):
                    # 边界不合理，合并
                    logger.info(f"[EnhancedSlicer] Merging chunks at boundary {i}: {result.get('reason')}")
                    # 合并到前一个 chunk
                    if validated_chunks:
                        validated_chunks[-1] = Chunk(
                            content=validated_chunks[-1].content + "\n" + chunk.content,
                            metadata=chunk.metadata,
                            parent_id=chunk.parent_id
                        )
                        continue

            validated_chunks.append(chunk)

        return validated_chunks

    async def _score_and_filter_async(self, chunks: List[Chunk], threshold: float = 0.5) -> List[Chunk]:
        """评分并过滤低质量 chunks"""
        from app.core.settings import LLM_CHUNK_THRESHOLD
        threshold = threshold or LLM_CHUNK_THRESHOLD

        scored_chunks = []
        for chunk in chunks:
            result = await self.chunk_scorer.score_chunk_async(chunk.content)
            score = result.get("score", 0.5)

            if score >= threshold:
                scored_chunks.append(chunk)
            else:
                logger.info(f"[EnhancedSlicer] Low score chunk filtered: {score:.2f}, issues: {result.get('issues')}")

        return scored_chunks