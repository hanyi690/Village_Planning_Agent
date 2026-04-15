"""
差异化切片策略

针对政策/案例/标准/指南等不同类型文档，提供定制化的切片策略。
"""
import logging
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class SlicingStrategy(ABC):
    """切片策略抽象基类"""

    MAX_CHUNK_LEN = 2000  # 安全最大切片长度（考虑中文 Token 比例）

    def _preprocess(self, text: str) -> str:
        """预处理文本：统一换行符、压缩空行"""
        text = re.sub(r'\r\n|\r', '\n', text)  # 统一换行符
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # 压缩多余空行
        return text.strip()

    def _check_chunk_lengths(self, slices: List[str], content: str) -> List[str]:
        """检查切片长度，超长时强制重新分割"""
        if not slices:
            return slices

        oversized = [s for s in slices if len(s) > self.MAX_CHUNK_LEN]
        if not oversized:
            return slices

        logger.warning(f"发现 {len(oversized)} 个超长切片，强制重新分割")
        return self._fallback_split(content)

    @abstractmethod
    def _fallback_split(self, content: str) -> List[str]:
        """默认分割方法，子类必须实现"""
        pass

    @abstractmethod
    def slice(self, content: str, metadata: Optional[Dict] = None) -> List[str]:
        """
        将文档内容切分为片段

        Args:
            content: 文档完整内容
            metadata: 文档元数据（可选）

        Returns:
            切片列表
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """返回策略名称"""
        pass


class PolicySlicer(SlicingStrategy):
    """
    政策文档切片策略

    特点：
    - 按"第 X 条"分割，保持条款完整性
    - 按章节分割，保持政策结构
    - 最小切片长度 50 字符，避免碎片化
    - 最大切片长度 2500 字符，避免切片过大
    """

    # 配置常量
    MAX_CHUNK_LEN = 2500  # 最大切片长度
    MIN_CHUNK_LEN = 50    # 最小切片长度

    def slice(self, content: str, metadata: Optional[Dict] = None) -> List[str]:
        content = self._preprocess(content)
        slices = []

        # 策略 1: 按"第 X 条"分割（放宽空格匹配）
        clause_pattern = r'\n(?=第\s*[一二三四五六七八九十百千万0-9]+\s*条)'
        clauses = re.split(clause_pattern, content)

        if len(clauses) > 1:
            current = ""
            for clause in clauses:
                clause = clause.strip()
                if not clause:
                    continue
                # 合并时检查最大长度限制
                if len(current) + len(clause) < self.MAX_CHUNK_LEN:
                    current += "\n" + clause
                else:
                    if current and len(current) >= self.MIN_CHUNK_LEN:
                        slices.append(current.strip())
                    current = clause
            # 保存最后一个
            if current and len(current) >= self.MIN_CHUNK_LEN:
                slices.append(current.strip())

        # 回退条件：无结果时才尝试下一策略
        if not slices:
            slices = self._split_by_sections(content)
        if not slices:
            slices = self._fallback_split(content)

        # 检查切片长度，防止超长
        slices = self._check_chunk_lengths(slices, content)

        return slices

    def _split_by_sections(self, content: str) -> List[str]:
        """按章节标题分割"""
        section_pattern = r'\n(?=[一二三四五六七八九十]+[、.])'
        sections = re.split(section_pattern, content)

        result = []
        for section in sections:
            section = section.strip()
            if len(section) >= 100:
                result.append(section)

        return result if result else []

    def _fallback_split(self, content: str) -> List[str]:
        """默认的 RecursiveCharacterTextSplitter 分割"""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=2500,
            chunk_overlap=500,
            length_function=len,
        )
        return splitter.split_text(content)

    def get_name(self) -> str:
        return "policy_slicer"


class CaseSlicer(SlicingStrategy):
    """
    案例文档切片策略

    特点：
    - 按项目阶段分割（一、项目背景 / 二、规划思路...）
    - 保持案例叙述的连贯性
    - 每个切片至少 200 字符
    """

    def slice(self, content: str, metadata: Optional[Dict] = None) -> List[str]:
        content = self._preprocess(content)

        # 策略 1: 按阶段标题分割（放宽匹配，移除关键词硬匹配）
        stage_patterns = [
            r'\n(?=[一二三四五六七八九十]+[、.])',  # 一、二、
            r'\n(?=\d+\.[^\d])',  # 1. 开头（非数字编号）
        ]

        sections = content
        for pattern in stage_patterns:
            result = re.split(pattern, sections)
            if len(result) > 1:
                sections = result
                break

        if isinstance(sections, str):
            return self._fallback_split(content)

        result = [s.strip() for s in sections if len(s.strip()) >= 200]
        if not result:
            return self._fallback_split(content)

        # 检查切片长度，防止超长
        result = self._check_chunk_lengths(result, content)

        return result

    def _fallback_split(self, content: str) -> List[str]:
        """默认的 RecursiveCharacterTextSplitter 分割"""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000,
            chunk_overlap=400,
            length_function=len,
        )
        return splitter.split_text(content)

    def get_name(self) -> str:
        return "case_slicer"


class StandardSlicer(SlicingStrategy):
    """
    标准规范文档切片策略

    特点：
    - 按章节条款分割（3.1, 3.2 或 4.1.2）
    - 保持技术参数的完整性
    - 保留标准编号和术语
    """

    def slice(self, content: str, metadata: Optional[Dict] = None) -> List[str]:
        content = self._preprocess(content)
        slices = []

        # 策略 1: 按标准章节编号分割（放宽空格要求）
        standard_pattern = r'\n(?=\d+\.\d+(?:\.\d+)?)'  # 不强制空格
        sections = re.split(standard_pattern, content)

        if len(sections) > 1:
            slices = [s.strip() for s in sections if len(s.strip()) >= 100]

        if not slices:
            # 策略 2: 按条分割（放宽空格匹配）
            clause_pattern = r'\n(?=第\s*\d+\s*条)'
            clauses = re.split(clause_pattern, content)
            slices = [c.strip() for c in clauses if len(c.strip()) >= 80]

        if not slices:
            slices = self._fallback_split(content)

        # 检查切片长度，防止超长
        slices = self._check_chunk_lengths(slices, content)

        return slices

    def _fallback_split(self, content: str) -> List[str]:
        """默认分割，使用较小的 chunk_size"""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500,
            chunk_overlap=300,
            length_function=len,
        )
        return splitter.split_text(content)

    def get_name(self) -> str:
        return "standard_slicer"


class GuideSlicer(SlicingStrategy):
    """
    指南/教材类文档切片策略

    特点：
    - 按 Markdown 标题分割（# ## ###）
    - 支持教材章节结构（第一章、第一节）
    - OCR 输出预处理（移除 ## Page N 标记）
    - 最小切片长度 150 字符
    """

    # OCR 页面标记（需排除，不当作标题）
    OCR_PAGE_MARKER = r'^#{1,6}\s+Page\s+\d+'

    def slice(self, content: str, metadata: Optional[Dict] = None) -> List[str]:
        # 预处理：统一换行符、压缩空行
        content = self._preprocess(content)
        # 移除 OCR 页面标记和包装
        content = self._remove_ocr_markers(content)

        # 策略 1: 按标题分割（#{1,3}）
        header_pattern = r'\n(?=#{1,3}\s)'
        sections = re.split(header_pattern, content)

        result = [s.strip() for s in sections if len(s.strip()) >= 150]
        if not result:
            result = self._fallback_split(content)

        # 检查切片长度，防止超长
        result = self._check_chunk_lengths(result, content)

        return result

    def _remove_ocr_markers(self, content: str) -> str:
        """移除 OCR 页面标记，避免被误判为标题"""
        content = re.sub(self.OCR_PAGE_MARKER, '', content, flags=re.MULTILINE)
        content = re.sub(r'\*\[Image OCR\]\n|\n\[End OCR\]\*\s*', '', content)
        content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)
        return content.strip()

    def _fallback_split(self, content: str) -> List[str]:
        """默认分割"""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1800,
            chunk_overlap=350,
            length_function=len,
        )
        return splitter.split_text(content)

    def get_name(self) -> str:
        return "guide_slicer"


class DefaultSlicer(SlicingStrategy):
    """
    默认切片策略

    使用 RecursiveCharacterTextSplitter，适用于无法识别类型的文档。
    """

    def __init__(
        self,
        chunk_size: int = 2500,
        chunk_overlap: int = 500,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
        )

    def slice(self, content: str, metadata: Optional[Dict] = None) -> List[str]:
        return self.splitter.split_text(content)

    def _fallback_split(self, content: str) -> List[str]:
        """默认分割"""
        return self.splitter.split_text(content)

    def get_name(self) -> str:
        return "default_slicer"


class SlicingStrategyFactory:
    """
    切片策略工厂

    根据文档类型自动选择合适的切片策略。
    """

    _strategies: Dict[str, SlicingStrategy] = {
        "policy": PolicySlicer(),
        "case": CaseSlicer(),
        "standard": StandardSlicer(),
        "guide": GuideSlicer(),
        "report": DefaultSlicer(chunk_size=2000, chunk_overlap=400),
        "domain": GuideSlicer(),
        "textbook": GuideSlicer(),
    }

    @classmethod
    def get_strategy(cls, doc_type: str) -> SlicingStrategy:
        """
        根据文档类型获取对应的切片策略

        Args:
            doc_type: 文档类型（policy/case/standard/guide/report）

        Returns:
            切片策略实例
        """
        return cls._strategies.get(doc_type, cls._strategies.get("report"))

    @classmethod
    def slice_document(
        cls,
        content: str,
        doc_type: str,
        metadata: Optional[Dict] = None,
    ) -> List[str]:
        """
        根据文档类型切片

        Args:
            content: 文档内容
            doc_type: 文档类型
            metadata: 元数据

        Returns:
            切片列表
        """
        strategy = cls.get_strategy(doc_type)
        slices = strategy.slice(content, metadata)

        # 记录切片结果
        logger.info(f"[{strategy.get_name()}] {doc_type}: {len(slices)} slices")
        if len(slices) == 1 and len(content) > 500:
            logger.warning(
                f"单切片警告: {doc_type} 可能回退到默认分割"
            )

        return slices

    @classmethod
    def register_strategy(
        cls,
        doc_type: str,
        strategy: SlicingStrategy,
    ) -> None:
        """
        注册自定义切片策略

        Args:
            doc_type: 文档类型标识
            strategy: 策略实例
        """
        cls._strategies[doc_type] = strategy
