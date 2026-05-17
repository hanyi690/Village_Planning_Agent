"""
Hallucination Validator - Validates references against knowledge base

Validation Logic:
1. Law references: Check if document exists in KB
2. Clause references: Check if clause content matches KB
3. Indicators: Check if numerical values match KB
4. Standards: Check if standard exists and values match

Usage:
    from scripts.experiments.rag_hallucination.hallucination_validator import HallucinationValidator

    validator = HallucinationValidator()
    result = validator.validate_reference(ref, kb_context)
    rate = validator.calculate_hallucination_rate(validations)
"""

import re
import json
import sys
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Set
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend"))

from scripts.experiments.rag_hallucination.reference_extractor import (
    ExtractedReference,
    ReferenceType,
    ReferenceExtractor,
)

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    """验证状态枚举"""
    VALID = "valid"                    # 验证通过
    HALLUCINATION = "hallucination"    # 幻觉（KB无匹配）
    PARTIAL = "partial"                # 部分匹配
    UNVERIFIED = "unverified"          # 无法验证


@dataclass
class ValidationResult:
    """验证结果"""
    reference: ExtractedReference       # 原引用
    status: ValidationStatus            # 验证状态
    kb_match: bool = False              # 是否在KB中找到匹配
    kb_source: str = ""                  # KB来源文件名
    kb_content: str = ""                 # KB中匹配的内容
    match_score: float = 0.0             # 匹配度评分 (0-100)
    error_type: str = ""                 # 错误类型（如果是幻觉）
    note: str = ""                       # 备注

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference_text": self.reference.text,
            "reference_type": self.reference.type.value,
            "status": self.status.value,
            "kb_match": self.kb_match,
            "kb_source": self.kb_source,
            "kb_content": self.kb_content[:200] if self.kb_content else "",
            "match_score": self.match_score,
            "error_type": self.error_type,
            "note": self.note,
        }


class HallucinationValidator:
    """幻觉验证器 - 支持动态KB加载"""

    # 扩展的法规名称提取正则（覆盖更多文种）
    LAW_PATTERNS = [
        r'《[^》]+法》',           # 法律
        r'《[^》]+条例》',         # 条例
        r'《[^》]+规定》',         # 规定
        r'《[^》]+办法》',         # 办法
        r'《[^》]+意见》',         # 意见
        r'《[^》]+方案》',         # 方案
        r'《[^》]+规范》',         # 规范（新增）
        r'《[^》]+规程》',         # 规程（新增）
        r'《[^》]+细则》',         # 细则（新增）
        r'《[^》]+导则》',         # 导则（新增）
        r'《[^》]+标准》',         # 标准（新增）
        r'《[^》]+（[^）]+）》',    # 带括号的法规名（如《城乡规划法》（2019修正））
    ]

    # 扩展的标准编号提取正则
    STANDARD_PATTERNS = [
        r'GB[\s\-]?\d+(?:[\-\:]\d+)?',      # 国家标准
        r'GB/T[\s\-]?\d+(?:[\-\:]\d+)?',    # 国家推荐标准
        r'DB\d+/\d+(?:[\-\:]\d+)?',         # 地方标准
        r'DZ/T\s*\d+(?:[\-\:]\d+)?',        # 地质矿产
        r'CJJ[\s\-]?\d+(?:[\-\:]\d+)?',     # 城镇建设
        r'JGJ[\s\-]?\d+(?:[\-\:]\d+)?',     # 建筑工业
        r'JCJ[\s\-]?\d+(?:[\-\:]\d+)?',     # 建材行业
        r'T/CECS[\s\-]?\d+(?:[\-\:]\d+)?',  # 团体标准（新增）
        r'CECS[\s\-]?\d+(?:[\-\:]\d+)?',    # 工程建设标准化协会
        r'HJ[\s\-]?\d+(?:[\-\:]\d+)?',      # 环境保护（新增）
        r'SL[\s\-]?\d+(?:[\-\:]\d+)?',      # 水利（新增）
    ]

    def __init__(self, rag_service=None, kb_index_dir: str = None):
        """
        初始化验证器

        Args:
            rag_service: RAG服务实例（用于检索验证）
            kb_index_dir: KB索引目录路径
        """
        self.rag_service = rag_service
        self.kb_index_dir = Path(kb_index_dir or "data/RAG_doc/_cache/outline_index")

        # 缓存
        self._known_laws: Optional[Set[str]] = None
        self._known_standards: Optional[Set[str]] = None
        self._kb_context: Optional[str] = None
        self._kb_sources: Optional[List[str]] = None
        self._extractor = ReferenceExtractor()

        # 预编译正则
        self._compiled_law_patterns = [re.compile(p) for p in self.LAW_PATTERNS]
        self._compiled_standard_patterns = [re.compile(p) for p in self.STANDARD_PATTERNS]

    def _parse_source_name(self, index_file: Path) -> str:
        """解析索引文件名，兼容多种命名模式

        Args:
            index_file: 索引文件路径

        Returns:
            解析后的源文档名称
        """
        stem = index_file.stem

        # 尝试多种后缀移除
        suffixes_to_remove = [
            "_minerU_parsed_index",
            "_parsed_index",
            "_index",
            "_outline",
        ]

        for suffix in suffixes_to_remove:
            if stem.endswith(suffix):
                return stem[:-len(suffix)]

        # 无法识别时记录警告
        logger.warning(f"[KB] Unknown index file naming: {index_file.name}")
        return stem

    def load_kb_documents(self) -> Tuple[Set[str], Set[str], List[str], str]:
        """从KB动态加载已知法规、标准和上下文

        Returns:
            (known_laws, known_standards, kb_sources, kb_context)
        """
        if self._known_laws is not None:
            return (self._known_laws, self._known_standards,
                    self._kb_sources, self._kb_context)

        laws = set()
        standards = set()
        sources = []
        context_parts = []

        # 从索引文件加载
        if self.kb_index_dir.exists():
            for index_file in self.kb_index_dir.glob("*.json"):
                try:
                    with open(index_file, "r", encoding="utf-8") as f:
                        index_data = json.load(f)

                    source_name = self._parse_source_name(index_file)
                    sources.append(source_name)

                    # 使用扩展正则提取法规名称
                    for pattern in self._compiled_law_patterns:
                        matches = pattern.findall(source_name)
                        for law in matches:
                            laws.add(law)

                    # 使用扩展正则提取标准编号
                    for pattern in self._compiled_standard_patterns:
                        matches = pattern.findall(source_name)
                        standards.update(matches)

                    # 提取内容作为上下文
                    corrected_content = index_data.get("corrected_content", "")
                    if corrected_content:
                        context_parts.append(corrected_content[:5000])

                except Exception as e:
                    logger.warning(f"Failed to load {index_file}: {e}")
                    continue

        # 添加硬编码的常见法规（作为兜底）
        laws.update({
            "《中华人民共和国城乡规划法》",
            "《中华人民共和国土地管理法》",
            "《中华人民共和国环境保护法》",
            "《中华人民共和国文物保护法》",
            "《历史文化名城名镇名村保护条例》",
            "《地质灾害防治条例》",
        })

        standards.update({
            "GB50223",
            "GB50445",
            "GB/T 50445",
        })

        self._known_laws = laws
        self._known_standards = standards
        self._kb_sources = sources
        self._kb_context = "\n\n".join(context_parts)

        # 添加统计日志
        logger.info(f"[KB] Loaded {len(laws)} laws, {len(standards)} standards from {len(sources)} sources")

        # 添加告警
        if len(laws) < 10:
            logger.warning(f"[KB] Low law count ({len(laws)}), check KB index files")
        if len(standards) < 5:
            logger.warning(f"[KB] Low standard count ({len(standards)}), check KB index files")

        return (self._known_laws, self._known_standards,
                self._kb_sources, self._kb_context)

    def validate_reference(self, ref: ExtractedReference,
                          kb_context: str = "",
                          kb_sources: List[str] = None) -> ValidationResult:
        """
        验证单个引用

        Args:
            ref: 提取的引用
            kb_context: KB上下文文本（用于匹配）
            kb_sources: KB来源文件列表

        Returns:
            验证结果
        """
        kb_sources = kb_sources or []

        if ref.type == ReferenceType.LAW:
            return self._validate_law_reference(ref, kb_context, kb_sources)
        elif ref.type == ReferenceType.CLAUSE:
            return self._validate_clause_reference(ref, kb_context, kb_sources)
        elif ref.type == ReferenceType.INDICATOR:
            return self._validate_indicator_reference(ref, kb_context, kb_sources)
        elif ref.type == ReferenceType.STANDARD:
            return self._validate_standard_reference(ref, kb_context, kb_sources)
        elif ref.type == ReferenceType.POLICY:
            return self._validate_policy_reference(ref, kb_context, kb_sources)
        else:
            return ValidationResult(
                reference=ref,
                status=ValidationStatus.UNVERIFIED,
                note="未知引用类型",
            )

    def _normalize_law_name(self, name: str) -> str:
        """归一化法规名称（去除空格差异）

        Args:
            name: 法规名称

        Returns:
            归一化后的名称
        """
        # 去除书名号内的多余空格
        normalized = name.replace(" ", "")
        return normalized

    def _validate_law_reference(self, ref: ExtractedReference,
                                kb_context: str,
                                kb_sources: List[str]) -> ValidationResult:
        """验证法规引用"""
        law_name = ref.text
        law_name_normalized = self._normalize_law_name(law_name)

        # 动态加载KB文档
        known_laws, known_standards, default_sources, default_context = self.load_kb_documents()
        kb_context = kb_context or default_context
        kb_sources = kb_sources or default_sources

        # 1. 检查动态加载的已知法规列表（使用归一化匹配）
        for known_law in known_laws:
            if self._normalize_law_name(known_law) == law_name_normalized:
                return ValidationResult(
                    reference=ref,
                    status=ValidationStatus.VALID,
                    kb_match=True,
                    kb_source="KB文档列表",
                    match_score=95.0,
                    note="KB中存在该法规文档",
                )

        # 2. 检查KB来源文件（使用归一化匹配）
        for source in kb_sources:
            source_normalized = self._normalize_law_name(source)
            if law_name_normalized.replace("《", "").replace("》", "") in source_normalized:
                return ValidationResult(
                    reference=ref,
                    status=ValidationStatus.VALID,
                    kb_match=True,
                    kb_source=source,
                    match_score=85.0,
                    note="KB中找到匹配文档",
                )

        # 3. 在KB上下文中搜索（使用归一化匹配）
        law_clean = law_name_normalized.replace("《", "").replace("》", "")
        kb_context_normalized = self._normalize_law_name(kb_context)
        if law_clean in kb_context_normalized:
            match_score = self._calculate_text_match_score(law_clean, kb_context_normalized)
            return ValidationResult(
                reference=ref,
                status=ValidationStatus.VALID if match_score > 70 else ValidationStatus.PARTIAL,
                kb_match=True,
                kb_content=self._extract_kb_content(law_clean, kb_context),
                match_score=match_score,
                note="KB上下文中找到匹配",
            )

        # 4. 使用RAG服务检索（如果可用）
        if self.rag_service:
            rag_result = self._search_with_rag(law_name)
            if rag_result:
                return ValidationResult(
                    reference=ref,
                    status=ValidationStatus.VALID,
                    kb_match=True,
                    kb_source=rag_result.get("source", ""),
                    kb_content=rag_result.get("content", ""),
                    match_score=rag_result.get("score", 80.0),
                    note="RAG检索验证通过",
                )

        # 5. 未找到匹配 - 标记为幻觉
        return ValidationResult(
            reference=ref,
            status=ValidationStatus.HALLUCINATION,
            kb_match=False,
            error_type="A-法规文件名虚构",
            note="KB中未找到该法规",
        )

    def _validate_clause_reference(self, ref: ExtractedReference,
                                   kb_context: str,
                                   kb_sources: List[str]) -> ValidationResult:
        """验证条款引用"""
        clause_text = ref.text

        if clause_text in kb_context:
            return ValidationResult(
                reference=ref,
                status=ValidationStatus.VALID,
                kb_match=True,
                kb_content=self._extract_kb_content(clause_text, kb_context),
                match_score=80.0,
                note="KB中找到条款",
            )

        clause_num = ref.metadata.get("clause_number", 0)
        if clause_num > 0:
            patterns = [
                f"第{clause_num}条",
                f"第{self._number_to_chinese(clause_num)}条",
            ]
            for pattern in patterns:
                if pattern in kb_context:
                    return ValidationResult(
                        reference=ref,
                        status=ValidationStatus.PARTIAL,
                        kb_match=True,
                        kb_content=self._extract_kb_content(pattern, kb_context),
                        match_score=60.0,
                        note="找到类似条款编号",
                    )

        return ValidationResult(
            reference=ref,
            status=ValidationStatus.PARTIAL,
            kb_match=False,
            error_type="B-条款编号需上下文",
            note="条款引用需配合法规名称验证",
        )

    def _validate_indicator_reference(self, ref: ExtractedReference,
                                      kb_context: str,
                                      kb_sources: List[str]) -> ValidationResult:
        """验证技术指标"""
        indicator_text = ref.text
        values = ref.metadata.get("values", [])
        unit = ref.metadata.get("unit", "")

        if indicator_text in kb_context:
            return ValidationResult(
                reference=ref,
                status=ValidationStatus.VALID,
                kb_match=True,
                kb_content=self._extract_kb_content(indicator_text, kb_context),
                match_score=90.0,
                note="KB中找到精确匹配的技术指标",
            )

        if values:
            primary_value = values[0]
            value_patterns = [
                f"{primary_value}{unit}",
                f"{primary_value} {unit}",
                f"{primary_value}米",
                f"{primary_value}%"
            ]
            for pattern in value_patterns:
                if pattern in kb_context:
                    return ValidationResult(
                        reference=ref,
                        status=ValidationStatus.PARTIAL,
                        kb_match=True,
                        kb_content=self._extract_kb_content(pattern, kb_context),
                        match_score=70.0,
                        note=f"KB中找到相同数值({primary_value})",
                    )

        if self.rag_service:
            rag_result = self._search_with_rag(indicator_text)
            if rag_result:
                kb_content = rag_result.get("content", "")
                if values and any(str(v) in kb_content for v in values):
                    return ValidationResult(
                        reference=ref,
                        status=ValidationStatus.VALID,
                        kb_match=True,
                        kb_source=rag_result.get("source", ""),
                        kb_content=kb_content,
                        match_score=85.0,
                        note="RAG检索验证通过，数值匹配",
                    )

        return ValidationResult(
            reference=ref,
            status=ValidationStatus.HALLUCINATION,
            kb_match=False,
            error_type="C-技术指标数值错误",
            note=f"KB中未找到该技术指标({indicator_text})",
        )

    def _validate_standard_reference(self, ref: ExtractedReference,
                                     kb_context: str,
                                     kb_sources: List[str]) -> ValidationResult:
        """验证标准编号"""
        standard_id = ref.text

        # 动态加载KB文档
        known_laws, known_standards, default_sources, default_context = self.load_kb_documents()
        kb_context = kb_context or default_context
        kb_sources = kb_sources or default_sources

        # 检查动态加载的已知标准
        for known in known_standards:
            if known in standard_id or standard_id in known:
                return ValidationResult(
                    reference=ref,
                    status=ValidationStatus.VALID,
                    kb_match=True,
                    kb_source="KB标准列表",
                    match_score=90.0,
                    note="已知国家标准",
                )

        for source in kb_sources:
            if standard_id in source:
                return ValidationResult(
                    reference=ref,
                    status=ValidationStatus.VALID,
                    kb_match=True,
                    kb_source=source,
                    match_score=85.0,
                    note="KB中找到匹配标准文档",
                )

        if standard_id in kb_context:
            return ValidationResult(
                reference=ref,
                status=ValidationStatus.VALID,
                kb_match=True,
                kb_content=self._extract_kb_content(standard_id, kb_context),
                match_score=80.0,
                note="KB上下文中找到标准编号",
            )

        return ValidationResult(
            reference=ref,
            status=ValidationStatus.HALLUCINATION,
            kb_match=False,
            error_type="A-标准编号虚构",
            note=f"KB中未找到该标准({standard_id})",
        )

    def _validate_policy_reference(self, ref: ExtractedReference,
                                   kb_context: str,
                                   kb_sources: List[str]) -> ValidationResult:
        """验证政策文件引用"""
        policy_name = ref.text.replace("《", "").replace("》", "")

        for source in kb_sources:
            if policy_name in source:
                return ValidationResult(
                    reference=ref,
                    status=ValidationStatus.VALID,
                    kb_match=True,
                    kb_source=source,
                    match_score=85.0,
                    note="KB中找到匹配政策文档",
                )

        if policy_name in kb_context:
            return ValidationResult(
                reference=ref,
                status=ValidationStatus.VALID,
                kb_match=True,
                kb_content=self._extract_kb_content(policy_name, kb_context),
                match_score=75.0,
                note="KB上下文中找到政策名称",
            )

        return ValidationResult(
            reference=ref,
            status=ValidationStatus.HALLUCINATION,
            kb_match=False,
            error_type="A-政策文件名虚构",
            note="KB中未找到该政策文件",
        )

    def _search_with_rag(self, query: str) -> Optional[Dict[str, Any]]:
        """使用RAG服务检索"""
        if not self.rag_service:
            return None

        try:
            results = self.rag_service.search(query, top_k=1)
            if results:
                return {
                    "source": results[0].get("metadata", {}).get("source", ""),
                    "content": results[0].get("content", ""),
                    "score": 100 - results[0].get("score", 50),
                }
        except Exception:
            pass

        return None

    def _calculate_text_match_score(self, text: str, context: str) -> float:
        """计算文本匹配度评分"""
        if not text or not context:
            return 0.0

        if text in context:
            return 90.0

        words = list(text)
        matched = sum(1 for w in words if w in context)
        return (matched / len(words)) * 80 if words else 0.0

    def _extract_kb_content(self, text: str, context: str,
                            context_chars: int = 100) -> str:
        """提取KB中匹配内容的上下文"""
        pos = context.find(text)
        if pos == -1:
            return ""

        start = max(0, pos - context_chars)
        end = min(len(context), pos + len(text) + context_chars)

        result = context[start:end]
        if start > 0:
            result = "..." + result
        if end < len(context):
            result = result + "..."

        return result.strip()

    def _number_to_chinese(self, num: int) -> str:
        """数字转中文"""
        if num <= 10:
            return "一二三四五六七八九十"[num - 1] if num >= 1 else ""
        elif num < 20:
            return "十" + ("一二三四五六七八九"[num - 11] if num > 10 else "")
        else:
            tens = num // 10
            ones = num % 10
            result = "一二三四五六七八九"[tens - 1] + "十"
            if ones > 0:
                result += "一二三四五六七八九"[ones - 1]
            return result

    def calculate_hallucination_rate(self,
                                     validations: List[ValidationResult]) -> Dict[str, float]:
        """计算幻觉率（多种定义）

        Returns:
            {
                "strict": 仅HALLUCINATION状态,
                "lenient": HALLUCINATION + PARTIAL,
                "weighted": 加权计算,
            }
        """
        if not validations:
            return {"strict": 0.0, "lenient": 0.0, "weighted": 0.0}

        hallucinations = sum(1 for v in validations if v.status == ValidationStatus.HALLUCINATION)
        partials = sum(1 for v in validations if v.status == ValidationStatus.PARTIAL)
        total = len(validations)

        return {
            "strict": hallucinations / total,
            "lenient": (hallucinations + partials) / total,
            "weighted": (hallucinations + partials * 0.5) / total,
        }

    def validate_with_injected_knowledge(
        self,
        ref: ExtractedReference,
        injected_knowledge: Dict[str, Any],
    ) -> ValidationResult:
        """使用注入知识验证引用

        方案2核心方法：验证阶段利用保存的实际注入知识

        Args:
            ref: 提取的引用
            injected_knowledge: 保存的实际注入知识，包含:
                - rag_context: {source: content} RAG检索内容
                - dimension_knowledge: {dim_key: {references, content_snippets}}
                - retrieved_sources: [source_names]

        Returns:
            验证结果
        """
        ref_text = ref.text
        ref_clean = ref_text.replace("《", "").replace("》", "")

        # 1. 检查维度知识中的引用
        for dim_key, dim_knowledge in injected_knowledge.get("dimension_knowledge", {}).items():
            references = dim_knowledge.get("references", [])
            if ref_text in references:
                return ValidationResult(
                    reference=ref,
                    status=ValidationStatus.VALID,
                    kb_match=True,
                    kb_source=f"注入知识-{dim_key}",
                    match_score=95.0,
                    note="引用来自实际注入的知识",
                )

        # 2. 检查RAG上下文
        for source, content in injected_knowledge.get("rag_context", {}).items():
            if ref_text in content or ref_clean in content:
                return ValidationResult(
                    reference=ref,
                    status=ValidationStatus.VALID,
                    kb_match=True,
                    kb_source=source,
                    kb_content=content[:200] if content else "",
                    match_score=90.0,
                    note="引用在RAG检索内容中找到",
                )

        # 3. 检查检索来源列表
        for source in injected_knowledge.get("retrieved_sources", []):
            if ref_clean in source:
                return ValidationResult(
                    reference=ref,
                    status=ValidationStatus.VALID,
                    kb_match=True,
                    kb_source=source,
                    match_score=85.0,
                    note="引用来源文档被检索过",
                )

        # 4. 未在注入知识中找到，使用KB全局验证
        return self.validate_reference(ref)

    def get_validation_statistics(self,
                                  validations: List[ValidationResult]) -> Dict[str, Any]:
        """获取验证统计信息"""
        if not validations:
            return {
                "total": 0,
                "valid": 0,
                "hallucination": 0,
                "partial": 0,
                "unverified": 0,
                "hallucination_rates": {"strict": 0.0, "lenient": 0.0, "weighted": 0.0},
                "kb_match_rate": 0.0,
            }

        stats = {
            "total": len(validations),
            "valid": 0,
            "hallucination": 0,
            "partial": 0,
            "unverified": 0,
            "kb_matched": 0,
        }

        for v in validations:
            stats[v.status.value] = stats.get(v.status.value, 0) + 1
            if v.kb_match:
                stats["kb_matched"] += 1

        # 使用新的幻觉率计算
        stats["hallucination_rates"] = self.calculate_hallucination_rate(validations)
        stats["kb_match_rate"] = stats["kb_matched"] / stats["total"]

        return stats


def validate_references_batch(references: List[ExtractedReference],
                             kb_context: str = "",
                             kb_sources: List[str] = None,
                             rag_service=None) -> List[ValidationResult]:
    """批量验证引用"""
    validator = HallucinationValidator(rag_service=rag_service)
    return [
        validator.validate_reference(ref, kb_context, kb_sources)
        for ref in references
    ]


if __name__ == "__main__":
    test_refs = [
        ExtractedReference(
            text="《中华人民共和国城乡规划法》",
            type=ReferenceType.LAW,
            context="根据《中华人民共和国城乡规划法》第十八条规定...",
        ),
        ExtractedReference(
            text="第十八条",
            type=ReferenceType.CLAUSE,
            context="...第十八条 乡规划、村庄规划应当从农村实际出发...",
        ),
        ExtractedReference(
            text="不少于50米",
            type=ReferenceType.INDICATOR,
            context="崩塌隐患点避让距离不少于50米...",
        ),
        ExtractedReference(
            text="《虚构的法规名称》",
            type=ReferenceType.LAW,
            context="根据《虚构的法规名称》...",
        ),
    ]

    kb_context = """
    《中华人民共和国城乡规划法》第十八条规定：乡规划、村庄规划应当从农村实际出发。
    崩塌隐患点避让距离不少于50米，滑坡隐患点避让距离不少于100米。
    """

    validator = HallucinationValidator()
    validations = [
        validator.validate_reference(ref, kb_context)
        for ref in test_refs
    ]

    print("验证结果：")
    for v in validations:
        print(f"  [{v.status.value}] {v.reference.text}")
        print(f"    KB匹配: {v.kb_match}, 评分: {v.match_score:.1f}")
        if v.error_type:
            print(f"    错误类型: {v.error_type}")
        print()

    stats = validator.get_validation_statistics(validations)
    print(f"幻觉率: {stats['hallucination_rate']:.1%}")
    print(f"KB匹配率: {stats['kb_match_rate']:.1%}")
