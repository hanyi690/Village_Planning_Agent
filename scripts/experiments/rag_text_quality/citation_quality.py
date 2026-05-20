"""
Citation Quality Module
引用质量专项评估模块

评估引用的质量：
- 引用存在性：引用名称是否在 KB 中出现
- 引用准确性：引用内容与 KB 原文的语义相似度
- 支持性引用比例：引用是否支撑关键论点（vs 装饰性引用）

使用方法:
    evaluator = CitationQualityEvaluator()
    result = evaluator.evaluate_citations(text, kb_context)
"""

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set

# 添加项目路径
script_dir = Path(__file__).parent.resolve()
project_root = script_dir.parent.parent.parent.resolve()
backend_root = (project_root / "backend").resolve()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

logger = logging.getLogger(__name__)


# ============================================
# 数据类定义
# ============================================

@dataclass
class Citation:
    """引用"""
    text: str                    # 引用原文
    type: str                    # 引用类型：law, clause, indicator, standard
    context: str                 # 引用上下文（前后文本）
    position: int               # 在原文中的位置
    exists_in_kb: bool = False  # 是否存在于 KB
    kb_match_content: str = ""  # KB 中匹配的内容
    accuracy_score: float = 0.0 # 准确性评分
    is_supportive: bool = False # 是否为支持性引用
    support_type: str = ""      # 支持类型：supportive, decorative, unsupported


@dataclass
class CitationQualityResult:
    """引用质量评估结果"""
    dimension_key: str
    total_citations: int
    existing_citations: int
    accurate_citations: int
    supportive_citations: int
    decorative_citations: int
    
    existence_rate: float       # 引用存在率
    accuracy_rate: float        # 引用准确率
    supportive_rate: float      # 支持性引用比例
    
    citations: List[Citation]
    hallucination_citations: List[Citation]  # 幻觉引用列表


# ============================================
# 引用提取器
# ============================================

class CitationExtractor:
    """
    引用提取器
    
    从文本中提取法规引用、条款引用、指标引用、标准引用。
    """

    # 引用模式
    PATTERNS = {
        "law": [
            r'《[^》]+法》',
            r'《[^》]+条例》',
            r'《[^》]+规定》',
            r'《[^》]+办法》',
            r'《[^》]+导则》',
            r'《[^》]+标准》',
            r'《[^》]+规范》',
        ],
        "clause": [
            r'第[一二三四五六七八九十百]+条',
            r'第\d+条',
        ],
        "indicator": [
            r'不少于\s*\d+\s*米',
            r'不低于\s*\d+\s*米',
            r'≥\s*\d+\s*米',
            r'\d+\s*年一遇',
            r'人均\s*\d+[-~]\d+\s*平方米',
            r'不超过\s*\d+%',
            r'不低于\s*\d+%',
        ],
        "standard": [
            r'GB\s*\d+[-\d]*',
            r'GB/T\s*\d+[-\d]*',
            r'DB\d+/\d+[-\d]*',
            r'CJJ\s*\d+[-\d]*',
            r'SL\s*\d+[-\d]*',
        ],
    }

    def __init__(self, context_chars: int = 100):
        """
        初始化提取器
        
        Args:
            context_chars: 提取上下文的字符数
        """
        self.context_chars = context_chars
        self._compiled_patterns = {
            k: [re.compile(p) for p in v]
            for k, v in self.PATTERNS.items()
        }

    def extract(self, text: str) -> List[Citation]:
        """
        从文本中提取引用
        
        Args:
            text: 输入文本
            
        Returns:
            引用列表
        """
        citations = []
        seen: Set[Tuple[str, str]] = set()
        
        for citation_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    citation_text = match.group()
                    
                    # 去重
                    key = (citation_text, citation_type)
                    if key in seen:
                        continue
                    seen.add(key)
                    
                    # 提取上下文
                    context_start = max(0, match.start() - self.context_chars)
                    context_end = min(len(text), match.end() + self.context_chars)
                    context = text[context_start:context_end]
                    
                    citations.append(Citation(
                        text=citation_text,
                        type=citation_type,
                        context=context,
                        position=match.start(),
                    ))
        
        # 按位置排序
        citations.sort(key=lambda c: c.position)
        
        return citations


# ============================================
# 引用质量评估器
# ============================================

class CitationQualityEvaluator:
    """
    引用质量评估器
    
    评估引用的存在性、准确性、支持性。
    """

    def __init__(self, kb_context: str = "", kb_sources: List[str] = None):
        """
        初始化评估器
        
        Args:
            kb_context: KB 上下文文本
            kb_sources: KB 来源文件列表
        """
        self.kb_context = kb_context
        self.kb_sources = kb_sources or []
        self.extractor = CitationExtractor()

    def set_kb_context(self, kb_context: str, kb_sources: List[str] = None):
        """
        设置 KB 上下文
        
        Args:
            kb_context: KB 上下文文本
            kb_sources: KB 来源文件列表
        """
        self.kb_context = kb_context
        self.kb_sources = kb_sources or []

    def check_existence(self, citation: Citation) -> bool:
        """
        检查引用是否存在
        
        Args:
            citation: 引用
            
        Returns:
            是否存在于 KB
        """
        citation_text = citation.text
        
        # 检查 KB 上下文
        if citation_text in self.kb_context:
            return True
        
        # 检查 KB 来源文件
        for source in self.kb_sources:
            if citation_text in source:
                return True
        
        # 对于法规引用，检查法规名称是否匹配
        if citation.type == "law":
            law_name = citation_text.replace("《", "").replace("》", "")
            if law_name in self.kb_context:
                return True
            for source in self.kb_sources:
                if law_name in source:
                    return True
        
        # 对于标准引用，检查标准编号是否匹配
        if citation.type == "standard":
            std_id = citation_text.replace(" ", "").replace("-", "")
            kb_normalized = self.kb_context.replace(" ", "").replace("-", "")
            if std_id in kb_normalized:
                return True
        
        return False

    def calculate_accuracy(self, citation: Citation) -> float:
        """
        计算引用准确性
        
        Args:
            citation: 引用
            
        Returns:
            准确性评分（0-100）
        """
        if not citation.exists_in_kb:
            return 0.0
        
        # 简单匹配评分
        citation_text = citation.text
        
        # 检查引用上下文是否与 KB 内容匹配
        if citation_text in self.kb_context:
            # 提取 KB 中包含该引用的内容片段
            pos = self.kb_context.find(citation_text)
            kb_snippet = self.kb_context[max(0, pos-50):pos+100]
            
            # 计算引用上下文与 KB 片段的相似度
            # 简单方法：检查共同关键词
            citation_keywords = set(re.findall(r'\w+', citation.context))
            kb_keywords = set(re.findall(r'\w+', kb_snippet))
            
            if citation_keywords and kb_keywords:
                overlap = len(citation_keywords & kb_keywords)
                similarity = overlap / min(len(citation_keywords), len(kb_keywords))
                return similarity * 100
        
        return 50.0  # 存在但无法验证准确性时返回中等分数

    def check_supportiveness(self, citation: Citation) -> Tuple[bool, str]:
        """
        检查引用是否为支持性引用
        
        支持性引用：引用支撑关键论点
        装饰性引用：引用仅作为背景信息，不支撑具体论点
        
        Args:
            citation: 引用
            
        Returns:
            (是否为支持性引用, 支持类型)
        """
        context = citation.context
        
        # 检查引用是否与具体论点关联
        # 支持性引用通常出现在论点之后，如"根据...规定，应..."
        supportive_patterns = [
            r'根据.*应',
            r'依据.*须',
            r'按照.*要求',
            r'按照.*标准',
            r'符合.*规定',
            r'遵守.*条例',
        ]
        
        for pattern in supportive_patterns:
            if re.search(pattern, context):
                return True, "supportive"
        
        # 检查是否为装饰性引用
        decorative_patterns = [
            r'参考',
            r'借鉴',
            r'参照',
            r'可参考',
            r'详见',
        ]
        
        for pattern in decorative_patterns:
            if re.search(pattern, context):
                return False, "decorative"
        
        # 默认为支持性引用
        return True, "supportive"

    def evaluate_citations(
        self,
        text: str,
        dimension_key: str = ""
    ) -> CitationQualityResult:
        """
        评估文本中的引用质量
        
        Args:
            text: 输入文本
            dimension_key: 维度键
            
        Returns:
            引用质量评估结果
        """
        # 提取引用
        citations = self.extractor.extract(text)
        
        if not citations:
            return CitationQualityResult(
                dimension_key=dimension_key,
                total_citations=0,
                existing_citations=0,
                accurate_citations=0,
                supportive_citations=0,
                decorative_citations=0,
                existence_rate=0.0,
                accuracy_rate=0.0,
                supportive_rate=0.0,
                citations=[],
                hallucination_citations=[],
            )
        
        # 评估每个引用
        hallucination_citations = []
        for citation in citations:
            # 检查存在性
            citation.exists_in_kb = self.check_existence(citation)
            
            # 计算准确性
            citation.accuracy_score = self.calculate_accuracy(citation)
            
            # 检查支持性
            citation.is_supportive, citation.support_type = self.check_supportiveness(citation)
            
            # 记录幻觉引用
            if not citation.exists_in_kb:
                hallucination_citations.append(citation)
        
        # 计算统计指标
        total = len(citations)
        existing = sum(1 for c in citations if c.exists_in_kb)
        accurate = sum(1 for c in citations if c.accuracy_score >= 70)
        supportive = sum(1 for c in citations if c.is_supportive)
        decorative = sum(1 for c in citations if c.support_type == "decorative")
        
        return CitationQualityResult(
            dimension_key=dimension_key,
            total_citations=total,
            existing_citations=existing,
            accurate_citations=accurate,
            supportive_citations=supportive,
            decorative_citations=decorative,
            existence_rate=existing / total if total > 0 else 0.0,
            accuracy_rate=accurate / total if total > 0 else 0.0,
            supportive_rate=supportive / total if total > 0 else 0.0,
            citations=citations,
            hallucination_citations=hallucination_citations,
        )


# ============================================
# 便捷函数
# ============================================

def evaluate_citation_quality(
    text: str,
    kb_context: str,
    dimension_key: str = ""
) -> CitationQualityResult:
    """
    评估引用质量（便捷函数）
    
    Args:
        text: 输入文本
        kb_context: KB 上下文
        dimension_key: 维度键
        
    Returns:
        引用质量评估结果
    """
    evaluator = CitationQualityEvaluator(kb_context)
    return evaluator.evaluate_citations(text, dimension_key)


if __name__ == "__main__":
    # 测试
    test_text = """
    根据GB 50188-2007《镇规划标准》第5.2条规定，村庄道路密度应不低于8km/km²。
    金田村现状道路总长约15公里，道路密度为6.4km/km²，低于标准要求。
    参考《实用性村庄规划编制手册》，建议新增道路约3公里。
    """
    
    test_kb_context = """
    《镇规划标准》（GB 50188-2007）规定：
    村庄道路密度应不低于8km/km²。
    主干路红线宽度16-24米，干路10-14米，支路6-8米。
    """
    
    result = evaluate_citation_quality(test_text, test_kb_context, "road_planning")
    
    print(f"总引用数: {result.total_citations}")
    print(f"存在引用数: {result.existing_citations}")
    print(f"存在率: {result.existence_rate:.2%}")
    print(f"准确率: {result.accuracy_rate:.2%}")
    print(f"支持性引用比例: {result.supportive_rate:.2%}")
    print(f"\n幻觉引用:")
    for c in result.hallucination_citations:
        print(f"  - {c.text}")