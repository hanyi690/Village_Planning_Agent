"""
Reference Extractor - Extracts and classifies regulation references from text

Reference Types:
1. law: 法规文件名 (《中华人民共和国城乡规划法》)
2. clause: 条款编号 (第十八条, 第二十七条)
3. indicator: 技术指标 (不少于50米, 20年一遇)
4. standard: 标准编号 (GB50223, DB44/2209-2019)

Usage:
    from scripts.experiments.rag_hallucination.reference_extractor import ReferenceExtractor

    extractor = ReferenceExtractor()
    references = extractor.extract_all_references(report_text)
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class ReferenceType(Enum):
    """引用类型枚举"""
    LAW = "law"           # 法规文件名
    CLAUSE = "clause"     # 条款编号
    INDICATOR = "indicator"  # 技术指标
    STANDARD = "standard"    # 标准编号
    POLICY = "policy"     # 政策文件


@dataclass
class ExtractedReference:
    """提取的引用"""
    text: str                    # 引用原文
    type: ReferenceType          # 引用类型
    context: str = ""            # 上下文（前后各50字符）
    position: int = 0            # 在原文中的位置
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "type": self.type.value,
            "context": self.context,
            "position": self.position,
            "metadata": self.metadata,
        }

    def __hash__(self):
        return hash((self.text, self.type))

    def __eq__(self, other):
        if not isinstance(other, ExtractedReference):
            return False
        return self.text == other.text and self.type == other.type


class ReferenceExtractor:
    """引用提取器"""

    # 引用模式定义（扩展版本）
    PATTERNS = {
        ReferenceType.LAW: [
            r'《[^》]+（[^）]+）》',     # 带括号的法规名：如《城乡规划法》（2019修正）
            r'《[^》]+法》',           # 法律：文物保护法、城乡规划法
            r'《[^》]+条例》',         # 条例：历史文化名城名镇名村保护条例
            r'《[^》]+规定》',         # 规定
            r'《[^》]+办法》',         # 办法
            r'《[^》]+指南》',         # 指南
            r'《[^》]+导则》',         # 导则
            r'《[^》]+规范》',         # 规范（新增）
            r'《[^》]+规程》',         # 规程（新增）
            r'《[^》]+细则》',         # 细则（新增）
            r'《[^》]+标准》',         # 标准（新增）
        ],
        ReferenceType.CLAUSE: [
            r'第[一二三四五六七八九十百零〇]+条',      # 条款编号
            r'第[一二三四五六七八九十百零〇]+款',      # 款
            r'第[一二三四五六七八九十百零〇]+章',      # 章
            r'第\d+条',                               # 阿拉伯数字条款
        ],
        ReferenceType.INDICATOR: [
            r'不少于\s*\d+\s*米',                     # 不少于X米
            r'不低于\s*\d+\s*米',                     # 不低于X米
            r'≥\s*\d+\s*米',                          # ≥X米
            r'宽度\s*[≥≥]\s*\d+\s*米',                # 宽度≥X米
            r'距离\s*[≥≥]\s*\d+\s*米',                # 距离≥X米
            r'\d+\s*年一遇',                          # X年一遇
            r'人均\s*\d+[-~]\d+\s*平方米',            # 人均X-X平方米
            r'控制在\s*\d+[-~]\d+\s*公顷',            # 控制在X-X公顷
            r'不超过\s*\d+%',                         # 不超过X%
            r'不低于\s*\d+%',                         # 不低于X%
            r'容积率[为≤≥]\s*\d+\.?\d*',              # 容积率（新增）
            r'建筑密度[为≤≥]\s*\d+\.?\d*%',            # 建筑密度（新增）
        ],
        ReferenceType.STANDARD: [
            r'GB\s*\d+[-\d]*',                        # 国家标准 GB50223
            r'GB/T\s*\d+[-\d]*',                      # 国家推荐标准
            r'DB\d+/\d+[-\d]*',                       # 地方标准 DB44/2209-2019
            r'CJJ\s*\d+[-\d]*',                       # 城镇建设行业标准
            r'CJJ/T\s*\d+[-\d]*',                     # 城镇建设推荐标准（新增）
            r'DZ/T\s*\d+[-\d]*',                      # 地质矿产行业标准
            r'JGJ\s*\d+[-\d]*',                       # 建筑工业（新增）
            r'HJ\s*\d+[-\d]*',                        # 环境保护（新增）
            r'SL\s*\d+[-\d]*',                        # 水利（新增）
            r'T/CECS\s*\d+[-\d]*',                    # 团体标准（新增）
            r'CECS\s*\d+[-\d]*',                      # 工程建设标准化协会（新增）
        ],
        ReferenceType.POLICY: [
            r'《[^》]+意见》',                         # 意见
            r'《[^》]+通知》',                         # 通知
            r'《[^》]+方案》',                         # 方案
            r'《[^》]+规划》',                         # 规划
        ],
    }

    # 中文数字转换表
    CHINESE_NUM_MAP = {
        '零': 0, '〇': 0,
        '一': 1, '二': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8,
        '九': 9, '十': 10, '百': 100,
    }

    # 法规名称归一化映射
    NAME_NORMALIZATIONS = {
        "中华人民共和国": "",  # 去除前缀
        "中华人民": "",
        "中国": "",
    }

    def __init__(self, context_chars: int = 50):
        """
        初始化引用提取器

        Args:
            context_chars: 提取上下文的字符数
        """
        self.context_chars = context_chars
        self._compiled_patterns = self._compile_patterns()

    def _compile_patterns(self) -> Dict[ReferenceType, List[re.Pattern]]:
        """预编译正则表达式"""
        compiled = {}
        for ref_type, patterns in self.PATTERNS.items():
            compiled[ref_type] = [re.compile(p) for p in patterns]
        return compiled

    def extract_all_references(self, text: str) -> List[ExtractedReference]:
        """
        从文本中提取所有引用

        Args:
            text: 待提取的文本

        Returns:
            提取的引用列表
        """
        all_references = []
        seen = set()  # 去重

        for ref_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    ref_text = match.group()

                    # 去重
                    key = (ref_text, ref_type)
                    if key in seen:
                        continue
                    seen.add(key)

                    # 提取上下文
                    context = self._extract_context(text, match.start(), match.end())

                    reference = ExtractedReference(
                        text=ref_text,
                        type=ref_type,
                        context=context,
                        position=match.start(),
                        metadata=self._extract_metadata(ref_text, ref_type),
                    )
                    all_references.append(reference)

        # 按位置排序
        all_references.sort(key=lambda r: r.position)
        return all_references

    def extract(self, text: str) -> List[ExtractedReference]:
        """extract_all_references 的便捷别名"""
        return self.extract_all_references(text)

    def _extract_context(self, text: str, start: int, end: int) -> str:
        """提取引用的上下文"""
        context_start = max(0, start - self.context_chars)
        context_end = min(len(text), end + self.context_chars)

        context = text[context_start:context_end]

        # 标记省略
        if context_start > 0:
            context = "..." + context
        if context_end < len(text):
            context = context + "..."

        return context.strip()

    def _extract_metadata(self, ref_text: str, ref_type: ReferenceType) -> Dict[str, Any]:
        """提取引用的元数据"""
        metadata = {}

        if ref_type == ReferenceType.INDICATOR:
            # 提取数值
            numbers = re.findall(r'\d+\.?\d*', ref_text)
            if numbers:
                metadata["values"] = [float(n) for n in numbers]
                metadata["primary_value"] = float(numbers[0])

            # 提取单位
            if "米" in ref_text:
                metadata["unit"] = "米"
            elif "年一遇" in ref_text:
                metadata["unit"] = "年一遇"
            elif "%" in ref_text:
                metadata["unit"] = "%"
            elif "平方米" in ref_text:
                metadata["unit"] = "平方米"
            elif "公顷" in ref_text:
                metadata["unit"] = "公顷"

        elif ref_type == ReferenceType.CLAUSE:
            # 提取条款编号
            metadata["clause_number"] = self._parse_chinese_number(ref_text)

        elif ref_type == ReferenceType.STANDARD:
            # 提取标准编号
            metadata["standard_id"] = ref_text

        elif ref_type == ReferenceType.LAW:
            # 提取法规名称（去掉书名号）
            law_name = ref_text.replace("《", "").replace("》", "")
            metadata["law_name"] = law_name
            # 添加归一化名称
            metadata["normalized_name"] = self.normalize_law_name(ref_text)

        return metadata

    def normalize_law_name(self, name: str) -> str:
        """归一化法规名称

        Args:
            name: 法规名称（可能带书名号）

        Returns:
            归一化后的名称
        """
        normalized = name.replace("《", "").replace("》", "")
        for old, new in self.NAME_NORMALIZATIONS.items():
            normalized = normalized.replace(old, new)
        return normalized.strip()

    def _deduplicate(self, references: List[ExtractedReference]) -> List[ExtractedReference]:
        """去重：基于归一化名称和位置重叠

        Args:
            references: 原始引用列表

        Returns:
            去重后的引用列表
        """
        if not references:
            return references

        result = []
        seen_normalized = set()

        for ref in references:
            # 法规类型：基于归一化名称去重
            if ref.type == ReferenceType.LAW:
                normalized = self.normalize_law_name(ref.text)
                if normalized in seen_normalized:
                    continue
                seen_normalized.add(normalized)

            # 检查位置重叠
            overlapping = False
            for i, existing in enumerate(result):
                if self._overlaps(ref.position, existing.position):
                    # 保留更长的
                    if len(ref.text) > len(existing.text):
                        result[i] = ref
                    overlapping = True
                    break

            if not overlapping:
                result.append(ref)

        return result

    def _overlaps(self, pos1: int, pos2: int) -> bool:
        """检查两个位置是否重叠

        Args:
            pos1: 第一个引用的位置
            pos2: 第二个引用的位置

        Returns:
            是否重叠
        """
        return not (pos1[1] <= pos2[0] or pos2[1] <= pos1[0])

    def _parse_chinese_number(self, text: str) -> int:
        """解析中文数字"""
        # 提取中文数字部分
        chinese_nums = re.findall(r'[一二三四五六七八九十百零〇]+', text)
        if not chinese_nums:
            # 尝试阿拉伯数字
            arabic_nums = re.findall(r'\d+', text)
            return int(arabic_nums[0]) if arabic_nums else 0

        chinese = chinese_nums[0]
        result = 0

        if "百" in chinese:
            parts = chinese.split("百")
            if parts[0]:
                result = self.CHINESE_NUM_MAP.get(parts[0], 0) * 100
            if len(parts) > 1 and parts[1]:
                if "十" in parts[1]:
                    ten_parts = parts[1].split("十")
                    if ten_parts[0]:
                        result += self.CHINESE_NUM_MAP.get(ten_parts[0], 0) * 10
                    if len(ten_parts) > 1 and ten_parts[1]:
                        result += self.CHINESE_NUM_MAP.get(ten_parts[1], 0)
                else:
                    result += self.CHINESE_NUM_MAP.get(parts[1], 0)
        elif "十" in chinese:
            parts = chinese.split("十")
            if parts[0]:
                result = self.CHINESE_NUM_MAP.get(parts[0], 0) * 10
            else:
                result = 10
            if len(parts) > 1 and parts[1]:
                result += self.CHINESE_NUM_MAP.get(parts[1], 0)
        else:
            result = self.CHINESE_NUM_MAP.get(chinese, 0)

        return result

    def get_references_by_type(self, references: List[ExtractedReference],
                                ref_type: ReferenceType) -> List[ExtractedReference]:
        """按类型筛选引用"""
        return [r for r in references if r.type == ref_type]

    def count_references_by_type(self, references: List[ExtractedReference]) -> Dict[ReferenceType, int]:
        """统计各类型引用数量"""
        counts = {rt: 0 for rt in ReferenceType}
        for ref in references:
            counts[ref.type] += 1
        return counts

    def calculate_specificity_score(self, references: List[ExtractedReference]) -> float:
        """
        计算引用特异性评分

        评分规则：
        - 法规引用：1分
        - 条款编号：2分
        - 技术指标：3分
        - 标准编号：2分

        Returns:
            特异性评分（0-100）
        """
        if not references:
            return 0.0

        weights = {
            ReferenceType.LAW: 1.0,
            ReferenceType.CLAUSE: 2.0,
            ReferenceType.INDICATOR: 3.0,
            ReferenceType.STANDARD: 2.0,
            ReferenceType.POLICY: 1.0,
        }

        total_score = sum(weights.get(r.type, 0) for r in references)
        # 归一化到0-100
        return min(total_score * 5, 100.0)


def extract_references_from_report(report_text: str) -> List[ExtractedReference]:
    """
    从报告中提取所有引用（便捷函数）

    Args:
        report_text: 报告文本

    Returns:
        提取的引用列表
    """
    extractor = ReferenceExtractor()
    return extractor.extract_all_references(report_text)


def get_reference_statistics(references: List[ExtractedReference]) -> Dict[str, Any]:
    """
    获取引用统计信息

    Args:
        references: 引用列表

    Returns:
        统计信息字典
    """
    if not references:
        return {
            "total": 0,
            "by_type": {},
            "specificity_score": 0.0,
        }

    extractor = ReferenceExtractor()
    counts = extractor.count_references_by_type(references)
    score = extractor.calculate_specificity_score(references)

    return {
        "total": len(references),
        "by_type": {t.value: c for t, c in counts.items() if c > 0},
        "specificity_score": score,
    }


# 测试代码
if __name__ == "__main__":
    test_text = """
    根据广东省村庄规划编制导则第5.2条规定：村庄建设用地人均指标控制在100-150平方米。
    金田村现状人口500人，规划建设用地规模应控制在5-7.5公顷。

    依据《农村生活污水处理设施水污染物排放标准》（DB44/2209-2019）表1规定：
    出水排入环境水体时，CODcr≤60mg/L，氨氮≤8mg/L。

    根据《广东省地质灾害防治条例》第十八条规定：崩塌隐患点避让距离不少于50米，
    滑坡隐患点避让距离不少于100米。

    应避开地质灾害易发区域，确保居民安全。
    """

    extractor = ReferenceExtractor()
    references = extractor.extract_all_references(test_text)

    print(f"提取到 {len(references)} 个引用：")
    for ref in references:
        print(f"  [{ref.type.value}] {ref.text}")
        if ref.metadata:
            print(f"    元数据: {ref.metadata}")

    print(f"\n特异性评分: {extractor.calculate_specificity_score(references):.1f}")