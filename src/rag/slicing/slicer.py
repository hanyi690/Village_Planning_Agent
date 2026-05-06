"""
统一 Markdown 切片器

配置驱动，动态策略，合并原有 5 个独立切片器类。
支持：pattern-based 切分、parent-child 模式、语义切分。
"""
import logging
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """切片数据结构"""
    content: str
    metadata: Dict
    parent_id: Optional[str] = None  # Small-to-Big 架构使用


@dataclass
class SlicerConfig:
    """切片配置"""
    split_on: List[str] = None  # 分割正则表达式列表
    chunk_size: int = 2000
    overlap: int = 400
    min_chunk: int = 100
    parent_child: bool = False  # Small-to-Big 模式
    child_size: int = 400  # 子块大小
    parent_size: int = 2000  # 父块大小
    semantic: bool = False  # 语义切分（暂未实现）
    max_chunk: int = 2500  # 安全最大长度


class UnifiedMarkdownSlicer:
    """
    统一 Markdown 切片器

    特性：
    - 配置驱动：通过 CONFIGS 字典定义不同文档类型的策略
    - 动态策略：根据文档类型自动选择最佳切分方式
    - Small-to-Big：支持父子块架构，提升检索命中率
    """

    # ==================== 预编译切片模式（类级别常量）====================
    SPLIT_PATTERNS_RE: Dict[str, List] = {
        "policy": [re.compile(r'\n(?=第\s*[一二三四五六七八九十百千万0-9]+\s*条)')],
        "case": [
            re.compile(r'\n(?=[一二三四五六七八九十]+[、.])'),
            re.compile(r'\n(?=\d+\.[^\d])')
        ],
        "standard": [
            re.compile(r'\n(?=\d+\.\d+(?:\.\d+)?)'),
            re.compile(r'\n(?=第\s*\d+\s*条)')
        ],
        "guide": [re.compile(r'\n(?=#{1,3}\s)')],
        "textbook": [
            re.compile(r'\n(?=#{1,3}\s)'),
            re.compile(r'\n(?=第[一二三四五六七八九十百]+章)')
        ],
    }

    # 预编译预处理模式
    NEWLINE_NORMALIZE_RE = re.compile(r'\r\n|\r')
    MULTIPLE_NEWLINES_RE = re.compile(r'\n\s*\n\s*\n+')
    OCR_MARKER_RE = re.compile(r'^#{1,6}\s+Page\s+\d+', re.MULTILINE)
    OCR_WRAPPER_RE = re.compile(r'\*\[Image OCR\]\n|\n\[End OCR\]\*\s*')

    # 文档类型配置字典
    CONFIGS: Dict[str, SlicerConfig] = {
        "policy": SlicerConfig(
            split_on=[r'\n(?=第\s*[一二三四五六七八九十百千万0-9]+\s*条)'],
            chunk_size=2500,
            overlap=500,
            min_chunk=50,
            max_chunk=2500,
        ),
        "case": SlicerConfig(
            split_on=[r'\n(?=[一二三四五六七八九十]+[、.])', r'\n(?=\d+\.[^\d])'],
            chunk_size=2000,
            overlap=400,
            min_chunk=200,
            max_chunk=2000,
        ),
        "standard": SlicerConfig(
            split_on=[r'\n(?=\d+\.\d+(?:\.\d+)?)', r'\n(?=第\s*\d+\s*条)'],
            chunk_size=1500,
            overlap=300,
            min_chunk=80,
            max_chunk=1500,
        ),
        "guide": SlicerConfig(
            split_on=[r'\n(?=#{1,3}\s)'],
            chunk_size=1800,
            overlap=350,
            min_chunk=150,
            max_chunk=1800,
        ),
        "report": SlicerConfig(
            parent_child=True,
            child_size=400,
            parent_size=2000,
            chunk_size=2000,
            overlap=400,
            min_chunk=100,
        ),
        "textbook": SlicerConfig(
            split_on=[r'\n(?=#{1,3}\s)', r'\n(?=第[一二三四五六七八九十百]+章)'],
            chunk_size=1800,
            overlap=350,
            min_chunk=150,
            semantic=False,  # 可扩展为语义切分
        ),
        "default": SlicerConfig(
            chunk_size=2500,
            overlap=500,
            min_chunk=100,
            max_chunk=2500,
        ),
    }

    # OCR 页面标记（需排除，不当作标题）
    OCR_PAGE_MARKER = r'^#{1,6}\s+Page\s+\d+'

    def slice(
        self,
        content: str,
        doc_type: str,
        metadata: Optional[Dict] = None,
    ) -> List[Chunk]:
        """
        将文档内容切分为切片

        Args:
            content: 文档完整内容
            doc_type: 文档类型（policy/case/standard/guide/report/textbook）
            metadata: 文档元数据（可选）

        Returns:
            切片列表
        """
        # 预处理
        content = self._preprocess(content)
        content = self._remove_ocr_markers(content)

        # 获取配置
        config = self.CONFIGS.get(doc_type, self.CONFIGS["default"])
        logger.info(f"[UnifiedMarkdownSlicer] 类型: {doc_type}, 配置: parent_child={config.parent_child}")

        # 选择切分策略
        if config.parent_child:
            chunks = self._slice_parent_child(content, config, metadata)
        elif config.semantic:
            chunks = self._slice_semantic(content, config, metadata)
        else:
            chunks = self._slice_by_pattern(content, config, metadata, doc_type)

        # 验证切片长度
        chunks = self._check_chunk_lengths(chunks, content, config)

        logger.info(f"  切分完成: {len(chunks)} 个切片")
        return chunks

    def _preprocess(self, text: str) -> str:
        """预处理文本：统一换行符、压缩空行、清理表格乱码、清理书脊文字"""
        text = self.NEWLINE_NORMALIZE_RE.sub('\n', text)
        text = self.MULTIPLE_NEWLINES_RE.sub('\n\n', text)
    
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.strip()
            # 跳过表格行
            if stripped.count('|') > 3:
                continue
            # 跳过书脊文字：单个中文字符独占一行
            if len(stripped) == 1 and '\u4e00' <= stripped <= '\u9fff':
                continue
            # 跳过纯点线（目录分隔符）
            if stripped and all(c in '．。·.…' for c in stripped):
                continue
            # 跳过噪音行
            if len(stripped) > 20:
                chinese_count = sum(1 for c in stripped if '\u4e00' <= c <= '\u9fff')
                ascii_count = sum(1 for c in stripped if c.isascii() and c.isalpha())
                total_alpha = chinese_count + ascii_count
                if total_alpha > 0 and (1 - total_alpha / len(stripped)) > 0.6:
                    continue
            cleaned.append(line)
    
        text = '\n'.join(cleaned)
        text = self.MULTIPLE_NEWLINES_RE.sub('\n\n', text)
        return text.strip()

    def _remove_ocr_markers(self, content: str) -> str:
        """移除 OCR 页面标记（使用预编译模式）"""
        content = self.OCR_MARKER_RE.sub('', content)
        content = self.OCR_WRAPPER_RE.sub('', content)
        content = self.MULTIPLE_NEWLINES_RE.sub('\n\n', content)
        return content.strip()

    def _slice_by_pattern(
        self,
        content: str,
        config: SlicerConfig,
        metadata: Optional[Dict] = None,
        doc_type: str = "default",
    ) -> List[Chunk]:
        """
        按正则模式切分（使用预编译模式优先）

        优先级：
        1. 使用 SPLIT_PATTERNS_RE 中该 doc_type 的预编译模式
        2. 回退到 config.split_on（自定义配置）
        """
        # 优先使用预编译模式
        patterns = self.SPLIT_PATTERNS_RE.get(doc_type, [])

        # 如果没有预编译模式，使用配置中的自定义模式（需编译）
        if not patterns and config.split_on:
            patterns = [re.compile(p) for p in config.split_on]

        if not patterns:
            return self._fallback_split(content, config, metadata)

        slices = []
        for compiled_pattern in patterns:
            parts = compiled_pattern.split(content)
            if len(parts) > 1:
                # 合并小切片
                current = ""
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if len(current) + len(part) < config.max_chunk:
                        current += "\n" + part
                    else:
                        if current and len(current) >= config.min_chunk:
                            slices.append(current.strip())
                        current = part
                if current and len(current) >= config.min_chunk:
                    slices.append(current.strip())
                break

        if not slices:
            return self._fallback_split(content, config, metadata)

        return self._create_chunks(slices, metadata)

    def _slice_parent_child(
        self,
        content: str,
        config: SlicerConfig,
        metadata: Optional[Dict] = None,
    ) -> List[Chunk]:
        """
        Small-to-Big 切分：子块用于检索，父块用于返回上下文

        流程：
        1. 先按 parent_size 切分为父块
        2. 每个父块再切分为 child_size 的子块
        3. 子块引用父块 ID
        """
        # 第一步：切分父块
        parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.parent_size,
            chunk_overlap=config.overlap,
            length_function=len,
        )
        parent_texts = parent_splitter.split_text(content)

        # 第二步：每个父块切分为子块
        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.child_size,
            chunk_overlap=min(100, config.child_size // 4),
            length_function=len,
        )

        chunks = []
        for parent_idx, parent_text in enumerate(parent_texts):
            parent_id = f"parent_{parent_idx}"
            child_texts = child_splitter.split_text(parent_text)

            for child_idx, child_text in enumerate(child_texts):
                chunk = Chunk(
                    content=child_text,
                    metadata={
                        **(metadata or {}),
                        "parent_id": parent_id,
                        # 注意：parent_content 不存储在子块元数据中
                        # 由 ParentChildVectorStore 的 _parent_cache 单独存储
                        "child_index": child_idx,
                        "total_children": len(child_texts),
                    },
                    parent_id=parent_id,
                )
                chunks.append(chunk)

        return chunks

    def _slice_semantic(
        self,
        content: str,
        config: SlicerConfig,
        metadata: Optional[Dict] = None,
    ) -> List[Chunk]:
        """
        语义切分（暂未实现）

        未来可集成：
        - LangChain SemanticSplitter
        - LLM 辅助切分
        """
        logger.warning("语义切分暂未实现，使用 fallback")
        return self._fallback_split(content, config, metadata)

    def _fallback_split(
        self,
        content: str,
        config: SlicerConfig,
        metadata: Optional[Dict] = None,
    ) -> List[Chunk]:
        """默认 RecursiveCharacterTextSplitter 分割"""
        # 每次创建新实例以避免缓存实例的属性修改问题
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.overlap,
            length_function=len,
        )

        slices = splitter.split_text(content)
        return self._create_chunks(slices, metadata)

    def _create_chunks(
        self,
        slices: List[str],
        metadata: Optional[Dict] = None,
    ) -> List[Chunk]:
        """将切片文本转换为 Chunk 对象，过滤低质量切片"""
        result = []
        idx = 0
        for s in slices:
            if self._is_quality_chunk(s):
                result.append(
                    Chunk(content=s, metadata={**(metadata or {}), "chunk_index": idx})
                )
                idx += 1
        return result

    def _is_quality_chunk(self, text: str) -> bool:
        if len(text.strip()) < 30:
            return False
        chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        ratio = chinese_count / len(text)
        if ratio < 0.05:
            return False
        # 过滤书脊文字
        lines = [l for l in text.split('\n') if l.strip()]
        if lines:
            single_char_lines = sum(1 for l in lines if len(l.strip()) == 1)
            if single_char_lines / len(lines) > 0.4:
                return False
            # 过滤目录页：大量短行（section numbers like "5.3.1", page numbers）
            short_lines = sum(1 for l in lines if len(l.strip()) < 8)
            if short_lines / len(lines) > 0.6:
                return False
        return True
    
    def _check_chunk_lengths(
        self,
        chunks: List[Chunk],
        content: str,
        config: SlicerConfig,
    ) -> List[Chunk]:
        """检查切片长度，超长时强制重新分割"""
        if not chunks:
            return chunks

        oversized = [c for c in chunks if len(c.content) > config.max_chunk]
        if not oversized:
            return chunks

        logger.warning(f"发现 {len(oversized)} 个超长切片，强制重新分割")
        return self._fallback_split(content, config, chunks[0].metadata if chunks else None)


# ==================== 向后兼容接口 ====================

class SlicingStrategyFactory:
    """
    切片策略工厂（向后兼容）

    内部使用 UnifiedMarkdownSlicer 实现。
    """

    _slicer = UnifiedMarkdownSlicer()

    @classmethod
    def get_strategy(cls, doc_type: str) -> UnifiedMarkdownSlicer:
        """获取切片策略（向后兼容）"""
        return cls._slicer

    @classmethod
    def slice_document(
        cls,
        content: str,
        doc_type: str,
        metadata: Optional[Dict] = None,
    ) -> List[str]:
        """
        根据文档类型切片（向后兼容，返回字符串列表）

        Args:
            content: 文档内容
            doc_type: 文档类型
            metadata: 元数据

        Returns:
            切片文本列表
        """
        chunks = cls._slicer.slice(content, doc_type, metadata)

        # 记录切片结果
        logger.info(f"[UnifiedMarkdownSlicer] {doc_type}: {len(chunks)} slices")
        if len(chunks) == 1 and len(content) > 500:
            logger.warning(f"单切片警告: {doc_type} 可能回退到默认分割")

        # 返回字符串列表（向后兼容）
        return [c.content for c in chunks]

    @classmethod
    def register_strategy(
        cls,
        doc_type: str,
        config: SlicerConfig,
    ) -> None:
        """注册自定义切片配置"""
        cls._slicer.CONFIGS[doc_type] = config