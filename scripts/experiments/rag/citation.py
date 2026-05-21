"""
Citation Quality Module
引用质量专项评估模块

评估引用的质量：
- 引用存在性：引用名称是否在 RAG 文档库中出现
- 引用准确性：引用内容与 KB 原文的语义相似度
- 支持性引用比例：引用是否支撑关键论点（vs 装饰性引用）

使用方法:
    # 方式1：使用 RAG 文档库验证
    loader = RAGDocumentLoader(project_root)
    evaluator = CitationQualityEvaluator()
    evaluator.set_rag_loader(loader)
    result = evaluator.evaluate_citations(text)

    # 方式2：批量验证所有迭代（使用 LLM 提取器）
    results = verify_all_iterations(reports_dir, project_root)

    # 方式3：简单验证（向后兼容）
    evaluator = CitationQualityEvaluator(kb_context)
    result = evaluator.evaluate_citations(text, dimension_key)
"""

import asyncio
import json
import logging
import os
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

# 导入 verify_citations.py 中的 LLM 提取器
verify_citations_path = script_dir / "verify_citations.py"
if verify_citations_path.exists():
    import importlib.util
    spec = importlib.util.spec_from_file_location("verify_citations", verify_citations_path)
    verify_citations_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_citations_module)
    LLMCitationExtractor = verify_citations_module.LLMCitationExtractor
else:
    LLMCitationExtractor = None

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
    # 新增字段：源文档信息
    source_doc_path: str = ""   # 源文档路径（相对路径）
    source_doc_name: str = ""   # 源文档名称
    confidence: float = 0.0     # 匹配置信度（0-1）


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
# RAG 文档加载器
# ============================================

class RAGDocumentLoader:
    """
    RAG 文档库加载器

    加载 data/RAG_doc/_doc_md 目录下的所有文档，
    建立索引以支持引用验证。
    """

    RAG_DOC_PATH = "data/RAG_doc/_doc_md"

    # 文档类别映射
    CATEGORY_NAMES = {
        "01_专业教材": "专业教材",
        "02_法律法规": "法律法规",
        "03_政策文件": "政策文件",
        "04_技术规范": "技术规范",
        "05_上位规划": "上位规划",
        "06_相关案例": "相关案例",
    }

    def __init__(self, project_root: Path):
        """
        初始化加载器

        Args:
            project_root: 项目根目录
        """
        self.project_root = project_root
        self.rag_doc_path = project_root / self.RAG_DOC_PATH
        self.documents: Dict[str, Dict] = {}  # 文档名 -> {path, category, content, normalized_content}
        self._load_all()

    def _load_all(self):
        """加载所有 RAG 文档"""
        if not self.rag_doc_path.exists():
            logger.warning(f"RAG 文档库路径不存在: {self.rag_doc_path}")
            return

        for root, dirs, files in os.walk(self.rag_doc_path):
            for file in files:
                if file.endswith("_minerU_parsed.md"):
                    full_path = Path(root) / file

                    # 提取文档名称（去掉 _minerU_parsed.md 后缀）
                    doc_name = file.replace("_minerU_parsed.md", "")
                    # 去掉序号前缀（如 "01 "）
                    if doc_name[0:2].isdigit() and doc_name[2] in [' ', '_', '《']:
                        doc_name = doc_name[3:].lstrip()
                    # 去掉书名号
                    doc_name = re.sub(r'[《》]', '', doc_name)

                    # 提取类别
                    rel_path = full_path.relative_to(self.rag_doc_path)
                    category = self._extract_category(rel_path)

                    # 加载文档内容
                    try:
                        content = full_path.read_text(encoding="utf-8")
                        normalized = self._normalize_content(content)
                    except Exception as e:
                        logger.warning(f"加载文档失败: {full_path}, {e}")
                        content = ""
                        normalized = ""

                    # 存储文档信息
                    self.documents[doc_name] = {
                        "path": str(full_path.relative_to(self.project_root)),
                        "full_path": str(full_path),
                        "category": category,
                        "content": content,
                        "normalized_content": normalized,
                        "file_name": file,
                    }

        logger.info(f"已加载 {len(self.documents)} 个 RAG 文档")

    def _extract_category(self, rel_path: Path) -> str:
        """提取文档类别"""
        parts = rel_path.parts
        if parts:
            top_category = parts[0]
            return self.CATEGORY_NAMES.get(top_category, top_category)
        return "未知"

    def _normalize_content(self, content: str) -> str:
        """标准化文档内容用于匹配"""
        # 移除空格、连字符等
        normalized = content.replace(" ", "").replace("-", "").replace("—", "")
        normalized = normalized.replace("(", "").replace(")", "")
        normalized = normalized.replace("（", "").replace("）", "")
        return normalized.lower()

    def search(self, citation_text: str) -> Tuple[bool, str, str, float]:
        """
        搜索引用在文档库中的位置

        Args:
            citation_text: 引用文本

        Returns:
            (是否找到, 源文档路径, 源文档名称, 置信度)
        """
        # 标准化引用文本
        normalized_citation = self._normalize_citation(citation_text)

        # 1. 直接匹配（书名号内的内容）
        doc_name_match = self._match_by_doc_name(citation_text)
        if doc_name_match:
            doc_info = self.documents[doc_name_match]
            return True, doc_info["path"], doc_name_match, 1.0

        # 2. 标准化匹配（忽略空格和连字符）
        for doc_name, doc_info in self.documents.items():
            normalized_doc_name = self._normalize_citation(doc_name)
            if normalized_citation in normalized_doc_name or normalized_doc_name in normalized_citation:
                return True, doc_info["path"], doc_name, 0.9

        # 3. 内容匹配（在文档内容中搜索）
        for doc_name, doc_info in self.documents.items():
            if normalized_citation in doc_info["normalized_content"]:
                return True, doc_info["path"], doc_name, 0.8
            # 原始内容匹配
            if citation_text in doc_info["content"]:
                return True, doc_info["path"], doc_name, 0.8

        # 4. 关键词匹配（提取核心关键词）
        keywords = self._extract_keywords(citation_text)
        if keywords:
            for doc_name, doc_info in self.documents.items():
                keyword_matches = sum(1 for kw in keywords if kw in doc_info["normalized_content"])
                if keyword_matches >= len(keywords) * 0.5:
                    confidence = keyword_matches / len(keywords)
                    return True, doc_info["path"], doc_name, confidence * 0.7

        return False, "", "", 0.0

    def _normalize_citation(self, citation_text: str) -> str:
        """标准化引用文本"""
        # 移除书名号
        text = re.sub(r'[《》]', '', citation_text)
        # 标准化空格和连字符
        text = text.replace(" ", "").replace("-", "").replace("—", "")
        text = text.replace("(", "").replace(")", "")
        text = text.replace("（", "").replace("）", "")
        return text.lower()

    def _match_by_doc_name(self, citation_text: str) -> Optional[str]:
        """通过文档名称匹配"""
        # 提取书名号内的内容
        book_title_match = re.search(r'《([^》]+)》', citation_text)
        if book_title_match:
            law_name = book_title_match.group(1)
            # 直接匹配
            if law_name in self.documents:
                return law_name
            # 部分匹配
            for doc_name in self.documents:
                if law_name in doc_name or doc_name in law_name:
                    return doc_name

        # 对于标准编号（如 GB 50188-2007）
        if re.match(r'GB\s*\d+', citation_text) or re.match(r'GB/T\s*\d+', citation_text):
            normalized_std = self._normalize_citation(citation_text)
            for doc_name in self.documents:
                normalized_doc = self._normalize_citation(doc_name)
                if normalized_std in normalized_doc:
                    return doc_name

        return None

    def _extract_keywords(self, citation_text: str) -> List[str]:
        """提取引用的关键词"""
        keywords = []

        # 提取地名（如"梅州市"、"平远县"）
        place_match = re.findall(r'[一-龥]{2,4}(?:市|县|镇|省)', citation_text)
        keywords.extend(place_match)

        # 提取规划类型（如"国土空间总体规划"、"乡村振兴"）
        plan_match = re.findall(r'(?:国土空间|乡村振兴|村庄规划|总体规划)', citation_text)
        keywords.extend(plan_match)

        # 提取标准编号
        std_match = re.findall(r'GB\s*\d+[-\d]*|GB/T\s*\d+[-\d]*', citation_text)
        keywords.extend([self._normalize_citation(s) for s in std_match])

        return keywords

    def get_document_count(self) -> int:
        """获取文档总数"""
        return len(self.documents)

    def get_documents_by_category(self) -> Dict[str, int]:
        """获取各类别文档数量"""
        counts = {}
        for doc_info in self.documents.values():
            category = doc_info["category"]
            counts[category] = counts.get(category, 0) + 1
        return counts


# ============================================
# 引用提取器
# ============================================

class CitationExtractor:
    """
    引用提取器

    从文本中提取法规引用、条款引用、指标引用、标准引用。
    支持合并相邻引用为完整引用（如 "GB 50188-2007《镇规划标准》第5.2条"）。
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
            # 通用法规名称（不含上述特定后缀）
            r'《[^》]+》',
        ],
        "clause": [
            r'第[一二三四五六七八九十百]+条',
            r'第\d+\.?\d*条',  # 支持第5.2条格式
        ],
        "indicator": [
            r'不少于\s*\d+\.?\d*\s*米',
            r'不低于\s*\d+\.?\d*\s*米',
            r'≥\s*\d+\.?\d*\s*米',
            r'\d+\s*年一遇',
            r'人均\s*\d+[-~]\d+\s*平方米',
            r'不超过\s*\d+\.?\d*%',
            r'不低于\s*\d+\.?\d*%',
        ],
        "standard": [
            r'GB/T\s*\d+[-\d]*',
            r'GB\s*\d+[-\d]*',
            r'DB\d+/\d+[-\d]*',
            r'CJJ\s*\d+[-\d]*',
            r'SL\s*\d+[-\d]*',
            r'JGJ\s*\d+[-\d]*',
            r'HJ\s*\d+[-\d]*',
        ],
    }

    def __init__(self, context_chars: int = 100, merge_adjacent: bool = True):
        """
        初始化提取器

        Args:
            context_chars: 提取上下文的字符数
            merge_adjacent: 是否合并相邻引用为完整引用
        """
        self.context_chars = context_chars
        self.merge_adjacent = merge_adjacent
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
        # 第一步：提取所有原始匹配
        raw_matches = []

        for citation_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    raw_matches.append({
                        "text": match.group(),
                        "type": citation_type,
                        "start": match.start(),
                        "end": match.end(),
                    })

        # 按位置排序
        raw_matches.sort(key=lambda m: m["start"])

        # 第二步：合并相邻引用
        if self.merge_adjacent and raw_matches:
            merged = self._merge_adjacent_citations(text, raw_matches)
        else:
            merged = raw_matches

        # 第三步：去重并构建 Citation 对象
        citations = []
        seen_texts: Set[str] = set()

        for m in merged:
            # 去重
            if m["text"] in seen_texts:
                continue
            seen_texts.add(m["text"])

            # 提取上下文
            context_start = max(0, m["start"] - self.context_chars)
            context_end = min(len(text), m["end"] + self.context_chars)
            context = text[context_start:context_end]

            citations.append(Citation(
                text=m["text"],
                type=m["type"],
                context=context,
                position=m["start"],
            ))

        return citations

    def _merge_adjacent_citations(
        self,
        text: str,
        matches: List[Dict],
    ) -> List[Dict]:
        """
        合并相邻的引用为完整引用

        例如: "GB 50188-2007《镇规划标准》第5.2条" 合并为一个引用

        Args:
            text: 原始文本
            matches: 已排序的匹配列表

        Returns:
            合并后的匹配列表
        """
        if not matches:
            return []

        merged = []
        current = matches[0].copy()

        for i in range(1, len(matches)):
            next_match = matches[i]

            # 检查是否相邻（中间只允许空白或标点）
            gap = text[current["end"]:next_match["start"]]
            # 允许的间隔：空白、书名号、括号、空格等
            if re.match(r'^[\s\(\)（）\[\]【】]*$', gap) and len(gap) <= 3:
                # 合并
                current["text"] = text[current["start"]:next_match["end"]]
                current["end"] = next_match["end"]
                # 类型标记为复合类型
                if current["type"] != next_match["type"]:
                    current["type"] = f"{current["type"]}+{next_match["type"]}"
            else:
                # 不相邻，保存当前并开始新的
                merged.append(current)
                current = next_match.copy()

        # 保存最后一个
        merged.append(current)

        return merged


# ============================================
# 引用质量评估器
# ============================================

class CitationQualityEvaluator:
    """
    引用质量评估器

    评估引用的存在性、准确性、支持性。
    支持使用 RAG 文档库进行验证。
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
        self.rag_loader: Optional[RAGDocumentLoader] = None

    def set_kb_context(self, kb_context: str, kb_sources: List[str] = None):
        """
        设置 KB 上下文

        Args:
            kb_context: KB 上下文文本
            kb_sources: KB 来源文件列表
        """
        self.kb_context = kb_context
        self.kb_sources = kb_sources or []

    def set_rag_loader(self, rag_loader: RAGDocumentLoader):
        """
        设置 RAG 文档加载器

        Args:
            rag_loader: RAG 文档加载器实例
        """
        self.rag_loader = rag_loader
        logger.info(f"已设置 RAG 文档加载器，共 {rag_loader.get_document_count()} 个文档")

    def check_existence(self, citation: Citation) -> bool:
        """
        检查引用是否存在

        Args:
            citation: 引用

        Returns:
            是否存在于 KB
        """
        citation_text = citation.text

        # 优先使用 RAG 文档加载器
        if self.rag_loader:
            exists, source_path, source_name, confidence = self.rag_loader.search(citation_text)
            if exists:
                citation.exists_in_kb = True
                citation.source_doc_path = source_path
                citation.source_doc_name = source_name
                citation.confidence = confidence
                return True
            citation.exists_in_kb = False
            return False

        # 回退到 KB 上下文验证
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
# 新增指标计算函数
# ============================================

def is_substantive_citation(text: str) -> bool:
    """
    判断是否为实质引用（包含具体条款/章节）

    实质引用：引用中包含具体的条款号、章节号或条文编号
    非实质引用：仅引用法规/标准名称，未指定具体条款

    Args:
        text: 引用文本

    Returns:
        是否为实质引用
    """
    patterns = [
        r'第[一二三四五六七八九十百]+条',      # 第X条（中文数字）
        r'第\d+\.?\d*条',                    # 第5条、第5.2条
        r'第[一二三四五六七八九十]+章',       # 第X章
        r'[第]?[一二三四五六七八九十\d]+[节款]', # 第X节/款
        r'GB\s*\d+[-\d]*第\d+',              # GB标准+条款
        r'第[一二三四五六七八九十百]+条\s*规定', # 第X条规定
    ]
    return any(re.search(p, text) for p in patterns)


def calculate_substantive_rate(citations: List[Citation]) -> float:
    """
    计算实质引用率

    Args:
        citations: 引用列表

    Returns:
        实质引用率（0-1）
    """
    if not citations:
        return 0.0
    substantive = sum(1 for c in citations if is_substantive_citation(c.text))
    return substantive / len(citations)


def normalize_for_matching(text: str) -> str:
    """
    标准化文本用于匹配

    Args:
        text: 输入文本

    Returns:
        标准化后的文本
    """
    # 移除空格、连字符、书名号等
    normalized = text.replace(" ", "").replace("-", "").replace("—", "")
    normalized = normalized.replace("(", "").replace(")", "")
    normalized = normalized.replace("（", "").replace("）", "")
    normalized = normalized.replace("《", "").replace("》", "")
    return normalized.lower()


def calculate_traceability_rate(
    citations: List[Citation],
    knowledge_sources: Dict,
) -> float:
    """
    计算知识溯源率

    知识溯源率：引用在本次检索的知识片段中出现的比例
    反映 RAG 检索对引用生成的直接支撑程度

    Args:
        citations: 引用列表
        knowledge_sources: RAG 检索的知识片段（来自 rag_knowledge.json）

    Returns:
        知识溯源率（0-1）
    """
    if not knowledge_sources or not citations:
        return 0.0

    # 获取检索到的知识片段内容
    chunks = knowledge_sources.get("retrieved_chunks", [])
    if not chunks:
        return 0.0

    # 合并所有片段内容
    all_content = " ".join(
        chunk.get("content_preview", "") or chunk.get("content", "")
        for chunk in chunks
    )
    normalized_content = normalize_for_matching(all_content)

    # 检查每个引用是否在片段中出现
    traced = 0
    for c in citations:
        normalized_cite = normalize_for_matching(c.text)
        if normalized_cite and normalized_cite in normalized_content:
            traced += 1

    return traced / len(citations) if citations else 0.0


def extract_numeric_indicators(citations: List[Citation]) -> List[Dict]:
    """
    提取带数值的引用（用于指标准确性抽样验证）

    Args:
        citations: 引用列表

    Returns:
        包含数值指标的引用列表
    """
    patterns = [
        r'不少于\s*\d+\.?\d*\s*米',
        r'不低于\s*\d+\.?\d*\s*米',
        r'≥\s*\d+\.?\d*\s*米',
        r'\d+\s*年一遇',
        r'人均\s*\d+[-~]\d+\s*平方米',
        r'不超过\s*\d+\.?\d*%',
        r'不低于\s*\d+\.?\d*%',
        r'\d+[-~]\d+\s*平方米',
    ]

    indicators = []
    for c in citations:
        for p in patterns:
            if re.search(p, c.context) or re.search(p, c.text):
                indicators.append({
                    "citation": c.text,
                    "sentence": c.context,
                    "source_doc": c.source_doc_name,
                    "exists_in_kb": c.exists_in_kb,
                })
                break  # 只记录一次

    return indicators


# ============================================
# 批量验证功能
# ============================================

@dataclass
class IterationVerificationResult:
    """单次迭代验证结果"""
    group: str
    iteration: str
    rag_config: str
    total_citations: int
    verified_citations: int
    hallucination_count: int
    existence_rate: float
    citations: List[Citation]
    # 新增指标
    substantive_rate: float = 0.0      # 实质引用率
    traceability_rate: float = 0.0     # 知识溯源率
    substantive_count: int = 0         # 实质引用数
    traceable_count: int = 0           # 可溯源引用数


async def verify_all_iterations_async(
    reports_dir: Path,
    project_root: Path,
    groups: List[str] = None,
) -> Dict[str, Dict[str, IterationVerificationResult]]:
    """
    验证所有迭代的引用质量（使用 LLM 提取器）

    Args:
        reports_dir: 报告目录（包含 g1/g2/g3 子目录）
        project_root: 项目根目录
        groups: 要验证的组别，默认为 ["g1", "g2", "g3"]

    Returns:
        {group: {iteration: IterationVerificationResult}}
    """
    groups = groups or ["g1", "g2", "g3"]

    # RAG 配置映射
    rag_configs = {
        "g1": "无RAG",
        "g2": "L3 RAG",
        "g3": "L1+L3 RAG",
    }

    # 初始化 RAG 文档加载器
    rag_loader = RAGDocumentLoader(project_root)
    evaluator = CitationQualityEvaluator()
    evaluator.set_rag_loader(rag_loader)

    # 使用 LLM 提取器（如果可用）
    llm_extractor = None
    if LLMCitationExtractor is not None:
        llm_extractor = LLMCitationExtractor()
        logger.info("使用 LLM 提取器（qwen-flash）")
    else:
        logger.warning("LLM 提取器不可用，使用正则提取器")

    results: Dict[str, Dict[str, IterationVerificationResult]] = {}

    for group in groups:
        results[group] = {}
        group_dir = reports_dir / group

        if not group_dir.exists():
            logger.warning(f"组目录不存在: {group_dir}")
            continue

        # 遍历迭代目录
        for iter_dir in sorted(group_dir.iterdir()):
            if not iter_dir.is_dir() or not iter_dir.name.startswith("iter"):
                continue

            iteration = iter_dir.name
            logger.info(f"验证 {group} {iteration}...")

            # 加载 reports.json
            report_json = iter_dir / "reports.json"
            if not report_json.exists():
                logger.warning(f"报告文件不存在: {report_json}")
                continue

            try:
                with open(report_json, "r", encoding="utf-8") as f:
                    report_data = json.load(f)
                reports = report_data.get("reports", {})
            except Exception as e:
                logger.error(f"读取 JSON 报告失败: {report_json}, {e}")
                continue

            # 使用 LLM 批量提取引用
            if llm_extractor:
                llm_citations = await llm_extractor.extract_batch(reports)
            else:
                # 回退到正则提取
                llm_citations = {}
                for dim_key, text in reports.items():
                    llm_citations[dim_key] = evaluator.extractor.extract(text)

            # 合并所有维度的引用
            all_citations = []
            for dim_key, citations_data in llm_citations.items():
                for c in citations_data:
                    text = c.get("text", "")
                    if not text:
                        continue
                    ctype = c.get("type", "unknown")
                    full_sentence = c.get("full_sentence", "")
                    context = c.get("context", full_sentence[:100] if full_sentence else "")

                    # 验证引用
                    exists, source_path, source_name, confidence = rag_loader.search(text)

                    all_citations.append(Citation(
                        text=text,
                        type=ctype,
                        context=context,
                        position=0,
                        exists_in_kb=exists,
                        source_doc_path=source_path,
                        source_doc_name=source_name,
                        confidence=confidence,
                    ))

            # 去重
            seen_texts: Set[str] = set()
            unique_citations = []
            for c in all_citations:
                if c.text not in seen_texts:
                    seen_texts.add(c.text)
                    unique_citations.append(c)

            # 计算统计
            total = len(unique_citations)
            verified = sum(1 for c in unique_citations if c.exists_in_kb)
            hallucination_count = total - verified
            existence_rate = verified / total if total > 0 else 0.0

            # 构建结果
            iter_result = IterationVerificationResult(
                group=group,
                iteration=iteration,
                rag_config=rag_configs.get(group, "未知"),
                total_citations=total,
                verified_citations=verified,
                hallucination_count=hallucination_count,
                existence_rate=existence_rate,
                citations=unique_citations,
            )
            results[group][iteration] = iter_result

            logger.info(
                f"  引用: {iter_result.total_citations}, "
                f"验证: {iter_result.verified_citations}, "
                f"存在率: {iter_result.existence_rate:.1%}"
            )

    return results


def verify_all_iterations(
    reports_dir: Path,
    project_root: Path,
    groups: List[str] = None,
) -> Dict[str, Dict[str, IterationVerificationResult]]:
    """
    验证所有迭代的引用质量（同步版本，使用 LLM 提取器）

    Args:
        reports_dir: 报告目录（包含 g1/g2/g3 子目录）
        project_root: 项目根目录
        groups: 要验证的组别，默认为 ["g1", "g2", "g3"]

    Returns:
        {group: {iteration: IterationVerificationResult}}
    """
    return asyncio.run(verify_all_iterations_async(reports_dir, project_root, groups))


def verify_citations_from_json(
    citations_json_path: Path,
    project_root: Path,
    reports_dir: Path = None,
) -> Dict[str, Dict[str, IterationVerificationResult]]:
    """
    基于 citations_llm.json 验证引用真实性

    Args:
        citations_json_path: citations_llm.json 路径
        project_root: 项目根目录
        reports_dir: 报告目录（用于加载 rag_knowledge.json）

    Returns:
        {group: {iteration: IterationVerificationResult}}
    """
    # RAG 配置映射
    rag_configs = {
        "g1": "无RAG",
        "g2": "L3 RAG",
        "g3": "L1+L3 RAG",
    }

    # 1. 加载 citations_llm.json
    logger.info(f"加载引用数据: {citations_json_path}")
    citations_data = json.loads(citations_json_path.read_text(encoding="utf-8"))

    # 2. 初始化 RAG 文档加载器
    rag_loader = RAGDocumentLoader(project_root)
    logger.info(f"已加载 {rag_loader.get_document_count()} 个 RAG 文档")

    # 3. 确定报告目录（用于加载 rag_knowledge.json）
    if reports_dir is None:
        reports_dir = citations_json_path.parent

    # 4. 验证每个引用
    results: Dict[str, Dict[str, IterationVerificationResult]] = {}

    for group, iterations in citations_data.items():
        results[group] = {}

        for iteration, dims in iterations.items():
            logger.info(f"验证 {group}/{iteration}...")

            # 加载 rag_knowledge.json（用于计算知识溯源率）
            rag_knowledge_path = reports_dir / group / iteration / "rag_knowledge.json"
            rag_knowledge: Dict[str, Dict] = {}
            if rag_knowledge_path.exists():
                try:
                    rag_knowledge_data = json.loads(rag_knowledge_path.read_text(encoding="utf-8"))
                    # 合并所有层级的知识片段
                    for layer_key, layer_data in rag_knowledge_data.items():
                        if isinstance(layer_data, dict):
                            for dim_key, dim_data in layer_data.items():
                                if isinstance(dim_data, dict) and "knowledge_sources" in dim_data:
                                    ks = dim_data["knowledge_sources"]
                                    # 处理两种格式：字典（有 retrieved_chunks）或列表（空）
                                    if isinstance(ks, dict) and ks.get("retrieved_chunks"):
                                        rag_knowledge[dim_key] = ks
                                    elif isinstance(ks, list) and ks:
                                        # 列表格式：直接作为 chunks
                                        rag_knowledge[dim_key] = {"retrieved_chunks": ks}
                    logger.info(f"  已加载 {len(rag_knowledge)} 个维度的知识片段")
                except Exception as e:
                    logger.warning(f"  加载知识片段失败: {e}")

            all_citations: List[Citation] = []
            for dim_data in dims:
                dim_key = dim_data.get("dimension", "")
                for c in dim_data.get("citations", []):
                    text = c.get("text", "")
                    if not text:
                        continue

                    # 验证引用
                    exists, source_path, source_name, confidence = rag_loader.search(text)

                    all_citations.append(Citation(
                        text=text,
                        type=c.get("type", "unknown"),
                        context=c.get("full_sentence", ""),
                        position=0,
                        exists_in_kb=exists,
                        source_doc_path=source_path,
                        source_doc_name=source_name,
                        confidence=confidence,
                    ))

            # 去重
            seen_texts: Set[str] = set()
            unique_citations = []
            for c in all_citations:
                if c.text not in seen_texts:
                    seen_texts.add(c.text)
                    unique_citations.append(c)

            # 计算统计指标
            total = len(unique_citations)
            verified = sum(1 for c in unique_citations if c.exists_in_kb)
            hallucination_count = total - verified
            existence_rate = verified / total if total > 0 else 0.0

            # 计算实质引用率
            substantive_count = sum(1 for c in unique_citations if is_substantive_citation(c.text))
            substantive_rate = substantive_count / total if total > 0 else 0.0

            # 计算知识溯源率（合并所有维度的知识片段）
            all_knowledge_sources = {"retrieved_chunks": []}
            for dim_key, ks in rag_knowledge.items():
                chunks = ks.get("retrieved_chunks", [])
                all_knowledge_sources["retrieved_chunks"].extend(chunks)

            traceable_count = 0
            if all_knowledge_sources["retrieved_chunks"]:
                traceability_rate = calculate_traceability_rate(unique_citations, all_knowledge_sources)
                traceable_count = int(traceability_rate * total)
            else:
                traceability_rate = 0.0

            # 构建结果
            iter_result = IterationVerificationResult(
                group=group,
                iteration=iteration,
                rag_config=rag_configs.get(group, "未知"),
                total_citations=total,
                verified_citations=verified,
                hallucination_count=hallucination_count,
                existence_rate=existence_rate,
                citations=unique_citations,
                substantive_rate=substantive_rate,
                traceability_rate=traceability_rate,
                substantive_count=substantive_count,
                traceable_count=traceable_count,
            )
            results[group][iteration] = iter_result

            logger.info(
                f"  引用: {iter_result.total_citations}, "
                f"验证: {iter_result.verified_citations}, "
                f"存在率: {iter_result.existence_rate:.1%}, "
                f"实质率: {iter_result.substantive_rate:.1%}, "
                f"溯源率: {iter_result.traceability_rate:.1%}"
            )

    return results


def generate_verification_report(
    results: Dict[str, Dict[str, IterationVerificationResult]],
    output_path: Path,
) -> str:
    """
    生成 Markdown 格式的验证报告

    Args:
        results: 验证结果
        output_path: 输出路径

    Returns:
        报告内容
    """
    lines = []

    # 标题
    lines.append("# 引用质量验证报告")
    lines.append("")
    lines.append(f"**验证日期**: 2026-05-21")
    lines.append(f"**验证方法**: RAG 文档库全文检索验证")
    lines.append("")

    # 核心结论
    total_all = sum(
        iter_result.total_citations
        for group_results in results.values()
        for iter_result in group_results.values()
    )
    verified_all = sum(
        iter_result.verified_citations
        for group_results in results.values()
        for iter_result in group_results.values()
    )
    existence_rate_all = verified_all / total_all if total_all > 0 else 0.0

    # 计算新指标汇总
    substantive_all = sum(
        iter_result.substantive_count
        for group_results in results.values()
        for iter_result in group_results.values()
    )
    traceable_all = sum(
        iter_result.traceable_count
        for group_results in results.values()
        for iter_result in group_results.values()
    )
    substantive_rate_all = substantive_all / total_all if total_all > 0 else 0.0
    traceability_rate_all = traceable_all / total_all if total_all > 0 else 0.0

    lines.append("## 一、核心结论")
    lines.append("")
    lines.append(f"> **所有 {total_all} 个引用中，{verified_all} 个在 RAG 文档库中找到对应文档。**")
    lines.append(f"> **引用真实存在率为 {existence_rate_all:.1%}。**")
    lines.append(f"> **实质引用率为 {substantive_rate_all:.1%}，知识溯源率为 {traceability_rate_all:.1%}。**")
    lines.append("")

    # 按迭代汇总
    lines.append("## 二、按迭代汇总")
    lines.append("")
    lines.append("| 组别 | 迭代 | RAG 配置 | 总引用 | 已验证 | 幻觉 | 真实存在率 | 实质引用率 | 知识溯源率 |")
    lines.append("|------|------|----------|--------|--------|------|-----------|-----------|-----------|")

    for group in ["g1", "g2", "g3"]:
        if group not in results:
            continue
        for iteration in sorted(results[group].keys()):
            r = results[group][iteration]
            lines.append(
                f"| {r.group} | {r.iteration} | {r.rag_config} | "
                f"{r.total_citations} | {r.verified_citations} | "
                f"{r.hallucination_count} | **{r.existence_rate:.1%}** | "
                f"{r.substantive_rate:.1%} | {r.traceability_rate:.1%} |"
            )

    lines.append("")

    # 按组汇总
    lines.append("## 三、按组汇总")
    lines.append("")
    lines.append("| 组别 | RAG 配置 | 总引用 | 已验证 | 幻觉 | 真实存在率 | 实质引用率 | 知识溯源率 |")
    lines.append("|------|----------|--------|--------|------|-----------|-----------|-----------|")

    for group in ["g1", "g2", "g3"]:
        if group not in results:
            continue
        group_total = sum(r.total_citations for r in results[group].values())
        group_verified = sum(r.verified_citations for r in results[group].values())
        group_hallucination = sum(r.hallucination_count for r in results[group].values())
        group_rate = group_verified / group_total if group_total > 0 else 0.0

        # 新指标汇总
        group_substantive = sum(r.substantive_count for r in results[group].values())
        group_traceable = sum(r.traceable_count for r in results[group].values())
        group_substantive_rate = group_substantive / group_total if group_total > 0 else 0.0
        group_traceability_rate = group_traceable / group_total if group_total > 0 else 0.0

        rag_config = list(results[group].values())[0].rag_config if results[group] else "未知"
        lines.append(
            f"| {group} | {rag_config} | {group_total} | {group_verified} | "
            f"{group_hallucination} | **{group_rate:.1%}** | "
            f"{group_substantive_rate:.1%} | {group_traceability_rate:.1%} |"
        )

    # 合计行
    lines.append(
        f"| **合计** | - | **{total_all}** | **{verified_all}** | "
        f"**{total_all - verified_all}** | **{existence_rate_all:.1%}** | "
        f"**{substantive_rate_all:.1%}** | **{traceability_rate_all:.1%}** |"
    )
    lines.append("")

    # 新增：指标说明
    lines.append("## 四、指标说明")
    lines.append("")
    lines.append("### 4.1 引用真实存在率")
    lines.append("")
    lines.append("引用名称是否在 RAG 文档库中找到对应文档。")
    lines.append("")
    lines.append("### 4.2 实质引用率")
    lines.append("")
    lines.append("包含具体条款/章节的引用占比。")
    lines.append("")
    lines.append("**判断标准**：引用中包含以下模式之一：")
    lines.append("- 第X条（中文或数字）")
    lines.append("- 第X章/节/款")
    lines.append("- GB标准+条款号")
    lines.append("")
    lines.append("**意义**：实质引用比单纯引用法规名称更具说服力，表明引用者查阅了具体条款。")
    lines.append("")
    lines.append("### 4.3 知识溯源率")
    lines.append("")
    lines.append("引用在本次 RAG 检索的知识片段中出现的比例。")
    lines.append("")
    lines.append("**计算方法**：检查引用文本是否出现在 `rag_knowledge.json` 的 `retrieved_chunks` 中。")
    lines.append("")
    lines.append("**意义**：")
    lines.append("- G1（无RAG）：知识溯源率应为 0%，引用来自模型内部知识")
    lines.append("- G2/G3（有RAG）：知识溯源率反映 RAG 检索对引用生成的直接支撑程度")
    lines.append("")

    # 各组详细引用列表
    lines.append("## 五、各组详细引用列表")
    lines.append("")

    for group in ["g1", "g2", "g3"]:
        if group not in results:
            continue

        rag_config = list(results[group].values())[0].rag_config if results[group] else "未知"
        lines.append(f"### 5.{['g1', 'g2', 'g3'].index(group) + 1} {group}（{rag_config}）")
        lines.append("")

        for iteration in sorted(results[group].keys()):
            r = results[group][iteration]
            lines.append(f"#### {iteration}（{r.total_citations} 个引用）")
            lines.append("")
            lines.append("| 引用 | 类型 | 验证结果 | 源文档 |")
            lines.append("|------|------|---------|--------|")

            for citation in r.citations:
                status = "✅ 存在" if citation.exists_in_kb else "❌ 幻觉"
                source = citation.source_doc_name or citation.source_doc_path or "-"
                # 截断过长的引用
                cite_text = citation.text[:50] + "..." if len(citation.text) > 50 else citation.text
                lines.append(f"| {cite_text} | {citation.type} | {status} | {source} |")

            lines.append("")

    # 保存报告
    report_content = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_content, encoding="utf-8")
    logger.info(f"报告已保存: {output_path}")

    return report_content


def save_verification_json(
    results: Dict[str, Dict[str, IterationVerificationResult]],
    output_path: Path,
) -> None:
    """
    保存验证结果为 JSON 格式

    Args:
        results: 验证结果
        output_path: 输出路径
    """
    # 转换为可序列化格式
    serializable = {}
    for group, group_results in results.items():
        serializable[group] = {}
        for iteration, iter_result in group_results.items():
            serializable[group][iteration] = {
                "group": iter_result.group,
                "iteration": iter_result.iteration,
                "rag_config": iter_result.rag_config,
                "total_citations": iter_result.total_citations,
                "verified_citations": iter_result.verified_citations,
                "hallucination_count": iter_result.hallucination_count,
                "existence_rate": iter_result.existence_rate,
                # 新增指标
                "substantive_rate": iter_result.substantive_rate,
                "traceability_rate": iter_result.traceability_rate,
                "substantive_count": iter_result.substantive_count,
                "traceable_count": iter_result.traceable_count,
                "citations": [
                    {
                        "text": c.text,
                        "type": c.type,
                        "full_sentence": c.context,
                        "exists_in_kb": c.exists_in_kb,
                        "source_doc_path": c.source_doc_path,
                        "source_doc_name": c.source_doc_name,
                        "confidence": c.confidence,
                        "is_substantive": is_substantive_citation(c.text),
                    }
                    for c in iter_result.citations
                ],
            }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 已保存: {output_path}")


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
    import argparse

    parser = argparse.ArgumentParser(description="引用质量验证工具")
    parser.add_argument(
        "--input",
        type=str,
        help="citations_llm.json 路径（基于已有 JSON 验证）",
    )
    parser.add_argument(
        "--verify-all",
        action="store_true",
        help="验证所有迭代的引用质量（重新提取）",
    )
    parser.add_argument(
        "--reports-dir",
        type=str,
        default="output/experiments/rag",
        help="报告目录路径",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/experiments/rag",
        help="输出目录路径",
    )
    parser.add_argument(
        "--groups",
        nargs="+",
        default=["g1", "g2", "g3"],
        help="要验证的组别",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="运行测试",
    )

    args = parser.parse_args()

    if args.input:
        # 基于 citations_llm.json 验证
        citations_path = project_root / args.input
        output_dir = project_root / args.output_dir

        if not citations_path.exists():
            print(f"错误: 文件不存在 {citations_path}")
            sys.exit(1)

        print(f"输入文件: {citations_path}")
        print(f"输出目录: {output_dir}")
        print()

        results = verify_citations_from_json(
            citations_json_path=citations_path,
            project_root=project_root,
        )

        # 生成报告
        report_path = output_dir / "citation_verification_report.md"
        json_path = output_dir / "citation_verification_results.json"

        generate_verification_report(results, report_path)
        save_verification_json(results, json_path)

        # 打印汇总
        print("\n=== 验证汇总 ===")
        for group in ["g1", "g2", "g3"]:
            if group not in results:
                continue
            group_total = sum(r.total_citations for r in results[group].values())
            group_verified = sum(r.verified_citations for r in results[group].values())
            group_rate = group_verified / group_total if group_total > 0 else 0.0
            rag_config = list(results[group].values())[0].rag_config if results[group] else "未知"
            print(f"{group} ({rag_config}): {group_total} 引用, {group_verified} 验证, {group_rate:.1%} 存在率")

    elif args.verify_all:
        # 批量验证所有迭代
        reports_dir = project_root / args.reports_dir
        output_dir = project_root / args.output_dir

        print(f"验证目录: {reports_dir}")
        print(f"输出目录: {output_dir}")
        print(f"验证组别: {args.groups}")
        print()

        results = verify_all_iterations(
            reports_dir=reports_dir,
            project_root=project_root,
            groups=args.groups,
        )

        # 生成报告
        report_path = output_dir / "citation_quality_verification_report.md"
        json_path = output_dir / "citation_quality_verification_results.json"

        generate_verification_report(results, report_path)
        save_verification_json(results, json_path)

        # 打印汇总
        print("\n=== 验证汇总 ===")
        for group in args.groups:
            if group not in results:
                continue
            group_total = sum(r.total_citations for r in results[group].values())
            group_verified = sum(r.verified_citations for r in results[group].values())
            group_rate = group_verified / group_total if group_total > 0 else 0.0
            print(f"{group}: {group_total} 引用, {group_verified} 验证, {group_rate:.1%} 存在率")

    elif args.test:
        # 运行测试
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

        # 测试简单验证
        print("=== 测试简单验证 ===")
        result = evaluate_citation_quality(test_text, test_kb_context, "road_planning")

        print(f"总引用数: {result.total_citations}")
        print(f"存在引用数: {result.existing_citations}")
        print(f"存在率: {result.existence_rate:.2%}")
        print(f"准确率: {result.accuracy_rate:.2%}")
        print(f"支持性引用比例: {result.supportive_rate:.2%}")
        print(f"\n幻觉引用:")
        for c in result.hallucination_citations:
            print(f"  - {c.text}")

        # 测试 RAG 文档库验证
        print("\n=== 测试 RAG 文档库验证 ===")
        rag_loader = RAGDocumentLoader(project_root)
        print(f"已加载 {rag_loader.get_document_count()} 个文档")

        evaluator = CitationQualityEvaluator()
        evaluator.set_rag_loader(rag_loader)
        result = evaluator.evaluate_citations(test_text, "test")

        print(f"总引用数: {result.total_citations}")
        print(f"存在引用数: {result.existing_citations}")
        print(f"存在率: {result.existence_rate:.2%}")
        print("\n引用详情:")
        for c in result.citations:
            status = "✅" if c.exists_in_kb else "❌"
            source = c.source_doc_name or "-"
            print(f"  {status} {c.text} -> {source} (置信度: {c.confidence:.2f})")

    else:
        # 默认运行测试
        parser.print_help()