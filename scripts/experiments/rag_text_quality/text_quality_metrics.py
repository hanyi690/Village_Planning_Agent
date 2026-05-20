"""
Text Quality Metrics Module
文本质量指标计算模块

实现自动化的文本质量评估指标：
- Faithfulness：生成文本中可被检索上下文支持的原子陈述比例
- 幻觉点计数：人工标注的幻觉内容点数量
- 内容深度评分：LLM 评估分析深度

使用方法:
    metrics = TextQualityMetrics()
    result = await metrics.evaluate(text, context)
"""

import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

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
class AtomicClaim:
    """原子陈述"""
    text: str                    # 陈述文本
    source_sentence: str         # 来源句子
    position: int               # 在原文中的位置
    is_supported: bool = False  # 是否被上下文支持
    support_evidence: str = ""  # 支持证据


@dataclass
class FaithfulnessResult:
    """Faithfulness 评估结果"""
    total_claims: int
    supported_claims: int
    unsupported_claims: int
    faithfulness_score: float
    claims: List[AtomicClaim]
    hallucination_points: List[str]  # 幻觉点列表


@dataclass
class TextQualityResult:
    """文本质量评估结果"""
    dimension_key: str
    text_length: int
    faithfulness: FaithfulnessResult
    content_depth_score: float
    content_depth_reasoning: str
    evaluated_at: str


# ============================================
# Faithfulness 计算器
# ============================================

class FaithfulnessCalculator:
    """
    Faithfulness 计算器
    
    计算生成文本中可被检索上下文支持的原子陈述比例。
    使用 NLI（自然语言推理）判断陈述是否被上下文蕴含。
    """

    def __init__(self, llm_client=None):
        """
        初始化计算器
        
        Args:
            llm_client: LLM 客户端（用于 NLI 判断）
        """
        self.llm_client = llm_client

    def extract_atomic_claims(self, text: str) -> List[AtomicClaim]:
        """
        从文本中提取原子陈述
        
        原子陈述是不可再分的事实性陈述。
        
        Args:
            text: 输入文本
            
        Returns:
            原子陈述列表
        """
        claims = []
        
        # 按句子分割
        sentences = re.split(r'[。！？\n]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        for i, sentence in enumerate(sentences):
            # 跳过太短的句子
            if len(sentence) < 10:
                continue
            
            # 提取事实性陈述（包含数字、法规引用、技术指标等）
            # 模式1：包含数字的陈述
            number_pattern = r'\d+\.?\d*[%米年公顷平方米]'
            if re.search(number_pattern, sentence):
                claims.append(AtomicClaim(
                    text=sentence,
                    source_sentence=sentence,
                    position=i,
                ))
            
            # 模式2：包含法规引用的陈述
            law_pattern = r'《[^》]+》|第[一二三四五六七八九十]+条|GB\s*\d+'
            if re.search(law_pattern, sentence):
                claims.append(AtomicClaim(
                    text=sentence,
                    source_sentence=sentence,
                    position=i,
                ))
            
            # 模式3：包含关键词的陈述
            keywords = ['应', '须', '必须', '不得', '禁止', '规定', '要求', '标准']
            if any(kw in sentence for kw in keywords):
                claims.append(AtomicClaim(
                    text=sentence,
                    source_sentence=sentence,
                    position=i,
                ))
        
        return claims

    async def check_claim_support(
        self,
        claim: AtomicClaim,
        context: str
    ) -> Tuple[bool, str]:
        """
        检查陈述是否被上下文支持
        
        Args:
            claim: 原子陈述
            context: 检索上下文
            
        Returns:
            (是否支持, 支持证据)
        """
        # 简单规则匹配（无需 LLM）
        # 检查陈述中的关键信息是否在上下文中出现
        
        # 提取陈述中的关键信息
        claim_text = claim.text
        
        # 检查数字匹配
        numbers_in_claim = re.findall(r'\d+\.?\d*', claim_text)
        for num in numbers_in_claim:
            if num in context:
                # 找到匹配的数字，检查上下文
                # 提取包含该数字的上下文片段
                pattern = f'.{{0,50}}{re.escape(num)}.{{0,50}}'
                matches = re.findall(pattern, context)
                if matches:
                    return True, matches[0]
        
        # 检查法规名称匹配
        laws_in_claim = re.findall(r'《[^》]+》', claim_text)
        for law in laws_in_claim:
            if law in context:
                return True, f"法规 {law} 在上下文中出现"
        
        # 检查标准编号匹配
        standards_in_claim = re.findall(r'GB\s*\d+|DB\s*\d+/\d+', claim_text)
        for std in standards_in_claim:
            if std in context:
                return True, f"标准 {std} 在上下文中出现"
        
        # 如果有 LLM 客户端，使用 NLI 判断
        if self.llm_client:
            return await self._nli_check(claim_text, context)
        
        return False, ""

    async def _nli_check(
        self,
        claim: str,
        context: str
    ) -> Tuple[bool, str]:
        """
        使用 LLM 进行 NLI 判断
        
        Args:
            claim: 陈述文本
            context: 上下文文本
            
        Returns:
            (是否蕴含, 证据)
        """
        # TODO: 实现 LLM NLI 判断
        # 当前使用简单规则匹配
        return False, ""

    async def calculate_faithfulness(
        self,
        text: str,
        context: str
    ) -> FaithfulnessResult:
        """
        计算 Faithfulness 分数
        
        Args:
            text: 生成文本
            context: 检索上下文
            
        Returns:
            Faithfulness 结果
        """
        # 提取原子陈述
        claims = self.extract_atomic_claims(text)
        
        if not claims:
            return FaithfulnessResult(
                total_claims=0,
                supported_claims=0,
                unsupported_claims=0,
                faithfulness_score=1.0,  # 无陈述时默认为 1
                claims=[],
                hallucination_points=[],
            )
        
        # 检查每个陈述是否被支持
        hallucination_points = []
        for claim in claims:
            is_supported, evidence = await self.check_claim_support(claim, context)
            claim.is_supported = is_supported
            claim.support_evidence = evidence
            
            if not is_supported:
                hallucination_points.append(claim.text)
        
        # 计算分数
        supported_count = sum(1 for c in claims if c.is_supported)
        unsupported_count = len(claims) - supported_count
        faithfulness_score = supported_count / len(claims) if claims else 1.0
        
        return FaithfulnessResult(
            total_claims=len(claims),
            supported_claims=supported_count,
            unsupported_claims=unsupported_count,
            faithfulness_score=faithfulness_score,
            claims=claims,
            hallucination_points=hallucination_points,
        )


# ============================================
# 内容深度评估器
# ============================================

class ContentDepthEvaluator:
    """
    内容深度评估器
    
    使用 LLM 评估分析内容的深度。
    """

    # 行为锚定量表
    RUBRIC = {
        1: "全是常识性描述，无具体指标或方法",
        3: "部分提及方法但未展开，指标不全",
        5: "给出清晰的技术路线、计算公式、标准阈值",
    }

    def __init__(self, llm_client=None):
        """
        初始化评估器
        
        Args:
            llm_client: LLM 客户端
        """
        self.llm_client = llm_client

    async def evaluate_depth(
        self,
        text: str,
        dimension_name: str
    ) -> Tuple[float, str]:
        """
        评估内容深度
        
        Args:
            text: 生成文本
            dimension_name: 维度名称
            
        Returns:
            (评分, 评分理由)
        """
        # 简单规则评分（无需 LLM）
        score = self._rule_based_score(text)
        reasoning = self._generate_reasoning(text, score)
        
        return score, reasoning

    def _rule_based_score(self, text: str) -> float:
        """
        基于规则的内容深度评分
        
        Args:
            text: 文本内容
            
        Returns:
            评分（1-5）
        """
        score = 1.0
        
        # 检查是否包含具体指标
        has_numbers = bool(re.search(r'\d+\.?\d*\s*[%米年公顷平方米]', text))
        if has_numbers:
            score += 1.0
        
        # 检查是否包含法规引用
        has_laws = bool(re.search(r'《[^》]+》', text))
        if has_laws:
            score += 0.5
        
        # 检查是否包含标准编号
        has_standards = bool(re.search(r'GB\s*\d+|DB\s*\d+/\d+', text))
        if has_standards:
            score += 0.5
        
        # 检查是否包含技术方法描述
        method_keywords = ['方法', '步骤', '流程', '计算', '分析', '评估', '指标']
        method_count = sum(1 for kw in method_keywords if kw in text)
        score += min(method_count * 0.5, 1.0)
        
        # 检查是否包含具体建议
        suggestion_keywords = ['应', '建议', '可', '宜', '需']
        suggestion_count = sum(1 for kw in suggestion_keywords if kw in text)
        score += min(suggestion_count * 0.2, 1.0)
        
        return min(score, 5.0)

    def _generate_reasoning(self, text: str, score: float) -> str:
        """
        生成评分理由
        
        Args:
            text: 文本内容
            score: 评分
            
        Returns:
            评分理由
        """
        reasons = []
        
        if re.search(r'\d+\.?\d*\s*[%米年公顷平方米]', text):
            reasons.append("包含具体数值指标")
        
        if re.search(r'《[^》]+》', text):
            reasons.append("引用法规文件")
        
        if re.search(r'GB\s*\d+|DB\s*\d+/\d+', text):
            reasons.append("引用技术标准")
        
        method_keywords = ['方法', '步骤', '流程', '计算', '分析', '评估']
        if any(kw in text for kw in method_keywords):
            reasons.append("包含技术方法描述")
        
        if not reasons:
            reasons.append("缺乏具体技术内容")
        
        return f"评分 {score:.1f} 分：{', '.join(reasons)}"


# ============================================
# 文本质量指标计算器
# ============================================

class TextQualityMetrics:
    """
    文本质量指标计算器
    
    整合所有自动指标计算。
    """

    def __init__(self, llm_client=None):
        """
        初始化计算器
        
        Args:
            llm_client: LLM 客户端
        """
        self.faithfulness_calc = FaithfulnessCalculator(llm_client)
        self.depth_evaluator = ContentDepthEvaluator(llm_client)

    async def evaluate(
        self,
        text: str,
        context: str,
        dimension_key: str,
        dimension_name: str = ""
    ) -> TextQualityResult:
        """
        评估文本质量
        
        Args:
            text: 生成文本
            context: 检索上下文
            dimension_key: 维度键
            dimension_name: 维度名称
            
        Returns:
            文本质量评估结果
        """
        from datetime import datetime
        
        # 计算 Faithfulness
        faithfulness = await self.faithfulness_calc.calculate_faithfulness(text, context)
        
        # 计算内容深度
        depth_score, depth_reasoning = await self.depth_evaluator.evaluate_depth(
            text, dimension_name or dimension_key
        )
        
        return TextQualityResult(
            dimension_key=dimension_key,
            text_length=len(text),
            faithfulness=faithfulness,
            content_depth_score=depth_score,
            content_depth_reasoning=depth_reasoning,
            evaluated_at=datetime.now().isoformat(),
        )


# ============================================
# 便捷函数
# ============================================

async def calculate_faithfulness(text: str, context: str) -> FaithfulnessResult:
    """
    计算 Faithfulness（便捷函数）
    
    Args:
        text: 生成文本
        context: 检索上下文
        
    Returns:
        Faithfulness 结果
    """
    calc = FaithfulnessCalculator()
    return await calc.calculate_faithfulness(text, context)


async def evaluate_text_quality(
    text: str,
    context: str,
    dimension_key: str
) -> TextQualityResult:
    """
    评估文本质量（便捷函数）
    
    Args:
        text: 生成文本
        context: 检索上下文
        dimension_key: 维度键
        
    Returns:
        文本质量评估结果
    """
    metrics = TextQualityMetrics()
    return await metrics.evaluate(text, context, dimension_key)


if __name__ == "__main__":
    # 测试
    import asyncio
    
    test_text = """
    根据GB 50188-2007《镇规划标准》，村庄道路密度应不低于8km/km²。
    金田村现状道路总长约15公里，道路密度为6.4km/km²，低于标准要求。
    建议新增道路约3公里，使道路密度达到8km/km²以上。
    """
    
    test_context = """
    《镇规划标准》（GB 50188-2007）规定：
    村庄道路密度应不低于8km/km²。
    主干路红线宽度16-24米，干路10-14米，支路6-8米。
    """
    
    async def test():
        result = await calculate_faithfulness(test_text, test_context)
        print(f"总陈述数: {result.total_claims}")
        print(f"支持陈述数: {result.supported_claims}")
        print(f"Faithfulness: {result.faithfulness_score:.2%}")
        print(f"幻觉点: {result.hallucination_points}")
    
    asyncio.run(test())