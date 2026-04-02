"""
差异化切片策略

针对政策/案例/标准/指南等不同类型文档，提供定制化的切片策略。
"""
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


class SlicingStrategy(ABC):
    """切片策略抽象基类"""

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
    """

    def slice(self, content: str, metadata: Optional[Dict] = None) -> List[str]:
        slices = []

        # 策略 1: 按"第 X 条"分割（保持条款完整性）
        clause_pattern = r'\n(?=(?:第 [一二三四五六七八九十百千万 0-9]+条))'
        clauses = re.split(clause_pattern, content)

        if len(clauses) > 1:
            # 有条款分割，合并过小片段
            current_clause = ""
            for clause in clauses:
                clause = clause.strip()
                if not clause:
                    continue

                if len(current_clause) + len(clause) < 500:
                    # 合并到当前条款
                    current_clause += "\n" + clause
                else:
                    # 保存当前条款并开始新的
                    if current_clause and len(current_clause) >= 50:
                        slices.append(current_clause.strip())
                    current_clause = clause

            # 保存最后一个条款
            if current_clause and len(current_clause) >= 50:
                slices.append(current_clause.strip())

        if len(slices) < 2:
            # 策略 2: 按章节标题分割（一、二、三...或 1.2.3....）
            slices = self._split_by_sections(content)

        if len(slices) < 2:
            # 策略 3: 使用默认的 RecursiveCharacterTextSplitter
            slices = self._fallback_split(content)

        return slices

    def _split_by_sections(self, content: str) -> List[str]:
        """按章节标题分割"""
        # 匹配中文数字章节：一、二、三...
        section_pattern = r'\n(?=[一二三四五六七八九十]+[、.])'
        sections = re.split(section_pattern, content)

        result = []
        for section in sections:
            section = section.strip()
            if len(section) >= 100:  # 章节至少 100 字符
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
        # 策略 1: 按阶段标题分割
        stage_patterns = [
            r'\n(?=[一二三四五六七八九十]+[、.].*(?:背景 | 思路 | 目标 | 措施 | 效果 | 总结))',
            r'\n(?=(?:一、|二、|三、|四、|五、|六、))',
            r'\n(?=\d+\.(?:\s|$))',  # 1. 2. 3....
        ]

        sections = content
        for pattern in stage_patterns:
            result = re.split(pattern, sections)
            if len(result) > 1:
                sections = result
                break

        # 如果 sections 是列表，直接使用；否则说明没有成功分割
        if isinstance(sections, list):
            pass  # 已经是列表
        else:
            # 回退到默认分割
            return self._fallback_split(content)

        result = []
        for section in sections:
            section = section.strip()
            if len(section) >= 200:  # 案例切片至少 200 字符
                result.append(section)

        if len(result) < 2:
            # 回退到默认分割
            result = self._fallback_split(content)

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
        slices = []

        # 策略 1: 按标准章节编号分割（如 4.1, 4.2 或 3.1.2）
        standard_pattern = r'\n(?=\d+\.\d+(?:\.\d+)?\s)'
        sections = re.split(standard_pattern, content)

        if len(sections) > 1:
            for section in sections:
                section = section.strip()
                if len(section) >= 100:  # 标准条款至少 100 字符
                    slices.append(section)

        if len(slices) < 2:
            # 策略 2: 按条分割（第 X 条）
            clause_pattern = r'\n(?=第 [0-9]+条)'
            clauses = re.split(clause_pattern, content)

            for clause in clauses:
                clause = clause.strip()
                if len(clause) >= 80:
                    slices.append(clause)

        if len(slices) < 2:
            # 策略 3: 使用较小的 chunk_size，保持技术参数完整
            slices = self._fallback_split(content)

        return slices

    def _fallback_split(self, content: str) -> List[str]:
        """默认分割，使用较小的 chunk_size"""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500,  # 标准文档使用较小的 chunk
            chunk_overlap=300,
            length_function=len,
        )
        return splitter.split_text(content)

    def get_name(self) -> str:
        return "standard_slicer"


class GuideSlicer(SlicingStrategy):
    """
    指南/手册类文档切片策略

    特点：
    - 按知识点分割
    - 保持操作说明的完整性
    - 适合教程类文档
    """

    def slice(self, content: str, metadata: Optional[Dict] = None) -> List[str]:
        # 策略 1: 按标题分割（## 或 ###）
        header_pattern = r'\n(?=#{1,3}\s)'
        sections = re.split(header_pattern, content)

        result = []
        for section in sections:
            section = section.strip()
            if len(section) >= 150:  # 知识点至少 150 字符
                result.append(section)

        if len(result) < 2:
            # 回退到默认分割
            result = self._fallback_split(content)

        return result

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
        return strategy.slice(content, metadata)

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
