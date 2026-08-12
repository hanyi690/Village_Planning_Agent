"""NLI-based Faithfulness and Coverage Evaluation Script.

Uses the configured LLM to perform NLI judgment on cached reports,
evaluating both faithfulness and information coverage.

IMPORTANT: 双维度评估框架
- **忠实度(Faithfulness)**: 报告内容是否基于事实（Ground Truth → 报告）
- **信息覆盖率(Coverage)**: 报告是否覆盖了关键信息（Ground Truth 关键点 → 报告）

RAG 优化效果体现在：
- Faithfulness: 各组应相近（都基于相同事实）
- Coverage: G3 > G2 > G1（RAG 提供更多上下文，覆盖更多信息）

Usage:
    python scripts/experiments/rag/nli_faithfulness.py

This script:
1. Loads cached reports from output/experiments/rag/
2. Loads Ground Truth from output/experiments/rag/ground_truth/
3. Extracts key facts from Ground Truth
4. Checks if reports cover these key facts (Coverage)
5. Checks if report claims are supported by Ground Truth (Faithfulness)
6. Generates comparison report showing RAG optimization effect
"""

import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project paths
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

logger = logging.getLogger(__name__)


async def _invoke_configured_llm(prompt: str) -> str:
    """Invoke the shared provider-aware LLM with the evaluation defaults."""
    from app.core.llm import create_llm

    llm = create_llm(
        temperature=0.1,
        max_tokens=2000,
        streaming=False,
    )
    response = await asyncio.to_thread(llm.invoke, prompt)
    return getattr(response, "content", "") or str(response)


# ============================================
# Data Classes
# ============================================

@dataclass
class AtomicClaim:
    """Atomic claim extracted from text."""
    text: str
    source_sentence: str
    position: int
    is_supported: bool = False
    support_evidence: str = ""


@dataclass
class NLIResult:
    """NLI judgment result."""
    claim_id: int
    verdict: str  # "支持" or "不支持"
    reason: str


@dataclass
class DimensionNLIResult:
    """NLI result for a dimension."""
    dimension_key: str
    dimension_name: str
    group: str
    total_claims: int
    supported_claims: int
    faithfulness_nli: float
    faithfulness_rule: float
    nli_results: List[NLIResult]
    knowledge_snippets: str
    claims: List[AtomicClaim]
    # Coverage metrics
    total_key_facts: int = 0
    covered_facts: int = 0
    coverage_nli: float = 0.0


@dataclass
class KeyFact:
    """Key fact extracted from Ground Truth."""
    text: str
    fact_id: int
    is_covered: bool = False
    cover_evidence: str = ""


# ============================================
# Claim Extraction (reuse from text_quality_metrics)
# ============================================

def extract_atomic_claims(text: str) -> List[AtomicClaim]:
    """Extract atomic claims from text."""
    claims = []

    # Split by sentence
    sentences = re.split(r'[。！？\n]', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    for i, sentence in enumerate(sentences):
        # Skip short sentences
        if len(sentence) < 10:
            continue

        # Pattern 1: Contains numbers with units
        number_pattern = r'\d+\.?\d*[%米年公顷平方米公里人户]'
        if re.search(number_pattern, sentence):
            claims.append(AtomicClaim(
                text=sentence,
                source_sentence=sentence,
                position=i,
            ))

        # Pattern 2: Contains law references
        law_pattern = r'《[^》]+》|第[一二三四五六七八九十]+条|GB\s*\d+'
        if re.search(law_pattern, sentence):
            claims.append(AtomicClaim(
                text=sentence,
                source_sentence=sentence,
                position=i,
            ))

        # Pattern 3: Contains requirement keywords
        keywords = ['应', '须', '必须', '不得', '禁止', '规定', '要求', '标准']
        if any(kw in sentence for kw in keywords):
            claims.append(AtomicClaim(
                text=sentence,
                source_sentence=sentence,
                position=i,
            ))

    return claims


def extract_key_facts(ground_truth: str) -> List[KeyFact]:
    """Extract key facts from Ground Truth for coverage evaluation.

    关键事实是 Ground Truth 中的重要信息点，用于评估报告是否覆盖了必要信息。
    """
    facts = []

    # Split by sentence
    sentences = re.split(r'[。！？\n]', ground_truth)
    sentences = [s.strip() for s in sentences if s.strip()]

    for i, sentence in enumerate(sentences):
        # Skip short sentences
        if len(sentence) < 15:
            continue

        # Key fact patterns (more selective than claims)
        is_key_fact = False

        # Pattern 1: Numbers with units (quantitative facts)
        if re.search(r'\d+\.?\d*[%米年公顷平方米公里人户]', sentence):
            is_key_fact = True

        # Pattern 2: Location/direction facts
        if re.search(r'(位于|连接|毗邻|接壤|距离|东|西|南|北)', sentence):
            is_key_fact = True

        # Pattern 3: Entity names (villages, roads, facilities)
        if re.search(r'(村|镇|县|市|路|道|桥|学校|医院|祠堂|广场)', sentence):
            is_key_fact = True

        if is_key_fact:
            facts.append(KeyFact(
                text=sentence,
                fact_id=len(facts) + 1,
            ))

    return facts


# ============================================
# Coverage Evaluation
# ============================================

async def evaluate_coverage_nli(
    key_facts: List[KeyFact],
    report_content: str,
    dimension_name: str,
) -> Tuple[int, int, float]:
    """Evaluate how many key facts from Ground Truth are covered in report.

    Returns:
        (total_facts, covered_facts, coverage_ratio)
    """
    if not key_facts:
        return 0, 0, 1.0

    try:
        # Build prompt
        facts_text = "\n".join(f"{f.fact_id}. {f.text}" for f in key_facts)

        prompt = f"""以下是来自权威文档的关键事实，以及一份村庄规划报告的内容。判断每个关键事实是否在报告中被提及或覆盖。

判断标准：
- 如果报告明确提及该事实的关键信息（数字、地点、名称等），输出"覆盖"
- 如果报告隐含该事实（如用"该村"指代具体村名），输出"覆盖"
- 如果报告完全未提及，输出"未覆盖"

关键事实列表：
{facts_text}

报告内容：
{report_content[:3000]}

请返回 JSON 格式：
{{"results": [{{"id": 1, "verdict": "覆盖"或"未覆盖", "reason": "简要说明"}}, ...]}}"""

        content = await _invoke_configured_llm(prompt)
        json_match = re.search(r'\{[^{}]*"results"[^{}]*\[[^\]]*\][^{}]*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            covered = 0
            for r in data.get("results", []):
                if r.get("verdict") == "覆盖":
                    covered += 1
            total = len(key_facts)
            coverage = min(covered / total, 1.0) if total > 0 else 1.0
            return total, covered, coverage

        logger.warning("[Coverage] API call failed, using rule-based")
        return _evaluate_coverage_rule(key_facts, report_content)

    except Exception as e:
        logger.error("[Coverage] Error: %s", e)
        return _evaluate_coverage_rule(key_facts, report_content)


def _evaluate_coverage_rule(
    key_facts: List[KeyFact],
    report_content: str,
) -> Tuple[int, int, float]:
    """Rule-based coverage evaluation as fallback."""
    covered = 0
    for fact in key_facts:
        # Check if key numbers/entities from fact appear in report
        numbers = re.findall(r'\d+\.?\d*', fact.text)
        entities = re.findall(r'[一-鿿]{2,}(村|镇|县|路|道)', fact.text)

        if any(num in report_content for num in numbers if len(num) > 1):
            covered += 1
        elif any(ent in report_content for ent in entities):
            covered += 1

    total = len(key_facts)
    coverage = min(covered / total, 1.0) if total > 0 else 1.0
    return total, covered, coverage


# ============================================
# Rule-based Faithfulness (for comparison)
# ============================================

def calculate_rule_faithfulness(claims: List[AtomicClaim], context: str) -> float:
    """Calculate rule-based faithfulness for comparison."""
    if not claims:
        return 1.0

    supported = 0
    for claim in claims:
        claim_text = claim.text

        # Check number match
        numbers = re.findall(r'\d+\.?\d*', claim_text)
        for num in numbers:
            if num in context:
                pattern = f'.{{0,50}}{re.escape(num)}.{{0,50}}'
                if re.findall(pattern, context):
                    supported += 1
                    break
        else:
            # Check law match
            laws = re.findall(r'《[^》]+》', claim_text)
            for law in laws:
                if law in context:
                    supported += 1
                    break
            else:
                # Check standard match
                standards = re.findall(r'GB\s*\d+|DB\s*\d+/\d+', claim_text)
                for std in standards:
                    if std in context:
                        supported += 1
                        break

    return supported / len(claims)


# ============================================
# NLI Judgment via the configured LLM
# ============================================

async def call_configured_llm_nli(
    claims: List[str],
    knowledge_snippets: str,
    dimension_name: str,
) -> List[NLIResult]:
    """Call the configured LLM for batch NLI judgment."""
    try:
        # Build prompt
        claims_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))

        prompt = f"""以下是来自一份村庄规划报告的若干声明，以及相关的知识依据。对每条声明，判断其是否完全被知识依据所支持。

判断标准：
- 如果依据中明确包含该声明的关键事实（数字、法规名称、标准编号等），输出"支持"
- 如果依据未提及、或内容矛盾、或只部分相关，输出"不支持"
- 对于常识性陈述（如"应加强管理"），如果依据中有类似表述，可视为支持

知识依据：
{knowledge_snippets}

声明列表（编号）：
{claims_text}

请返回 JSON 格式：
{{"results": [{{"id": 1, "verdict": "支持"或"不支持", "reason": "简要说明"}}, ...]}}"""

        content = await _invoke_configured_llm(prompt)

        # Parse JSON from response
        json_match = re.search(r'\{[^{}]*"results"[^{}]*\[[^\]]*\][^{}]*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            results = []
            for r in data.get("results", []):
                results.append(NLIResult(
                    claim_id=r.get("id", 0),
                    verdict=r.get("verdict", "不支持"),
                    reason=r.get("reason", ""),
                ))
            return results

        logger.warning("[NLI] Configured LLM returned no parseable result")
        return []

    except Exception as e:
        logger.error("[NLI] Error: %s", e)
        return []


# ============================================
# Ground Truth Loading
# ============================================

def load_ground_truth(base_dir: Path) -> Dict[str, str]:
    """Load Ground Truth knowledge files for all dimensions.

    Ground Truth 来自权威规划文档，是所有组共用的评估基准。
    - L1 维度：知识依据来自现状报告
    - L3 维度：知识依据来自现状报告（按 phases.yaml 依赖传递）
    """
    ground_truth_dir = base_dir / "ground_truth"
    if not ground_truth_dir.exists():
        logger.warning("[GroundTruth] Directory not found: %s", ground_truth_dir)
        return {}

    knowledge = {}
    for file_path in ground_truth_dir.glob("*_knowledge.md"):
        # Extract dimension key from filename (e.g., "location_knowledge.md" -> "location")
        dim_key = file_path.stem.replace("_knowledge", "")
        content = file_path.read_text(encoding="utf-8")
        knowledge[dim_key] = content
        logger.debug("[GroundTruth] Loaded %s: %d chars", dim_key, len(content))

    logger.info("[GroundTruth] Loaded %d dimensions", len(knowledge))
    return knowledge


def load_experiment_data(base_dir: Path) -> Dict[str, Any]:
    """Load all experiment data from output directory."""
    data = {}

    for group in ["g1", "g2", "g3"]:
        group_dir = base_dir / group / "iter0"
        if not group_dir.exists():
            logger.warning("[Load] Missing group dir: %s", group_dir)
            continue

        data[group] = {
            "reports": {},
            "knowledge": {},
        }

        # Load layer reports and knowledge
        for layer in [1, 2, 3]:
            reports_path = group_dir / f"layer{layer}_reports.json"
            knowledge_path = group_dir / f"layer{layer}_rag_knowledge.json"

            if reports_path.exists():
                reports_data = json.loads(reports_path.read_text(encoding="utf-8"))
                data[group]["reports"].update(reports_data.get("reports", {}))

            if knowledge_path.exists():
                knowledge_data = json.loads(knowledge_path.read_text(encoding="utf-8"))
                for dim_key, dim_data in knowledge_data.get("knowledge", {}).items():
                    data[group]["knowledge"][dim_key] = dim_data

    return data


def get_knowledge_snippets(knowledge_data: Dict) -> str:
    """Extract knowledge snippets from RAG knowledge data."""
    snippets = []

    ks = knowledge_data.get("knowledge_sources", {})

    # Handle both dict and list formats
    if isinstance(ks, dict):
        chunks = ks.get("retrieved_chunks", [])
    elif isinstance(ks, list):
        chunks = ks
    else:
        chunks = []

    for chunk in chunks:
        preview = chunk.get("content_preview", "")
        if preview:
            # Clean up LaTeX artifacts
            preview = re.sub(r'\$[^\$]+\$', '', preview)
            preview = re.sub(r'\\[a-zA-Z]+', '', preview)
            snippets.append(preview[:500])  # Limit length

    return "\n\n".join(snippets[:5])  # Use top 5 chunks


# ============================================
# Main Analysis
# ============================================

class NLIFaithfulnessAnalyzer:
    """Analyzer using NLI-based faithfulness calculation.

    使用 Ground Truth 作为统一评估基准，确保所有组公平对比。
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.data = load_experiment_data(base_dir)
        self.ground_truth = load_ground_truth(base_dir)
        self.results: Dict[str, List[DimensionNLIResult]] = {}

    async def analyze_all(self) -> Dict[str, Any]:
        """Analyze all groups and dimensions with concurrent API calls."""
        from app.config.loader import get_layer_dimensions, get_dimension_name

        # Get evaluation dimensions (L1 + L3)
        l1_dims = get_layer_dimensions(1)
        l3_dims = get_layer_dimensions(3)
        eval_dims = l1_dims + l3_dims

        all_results = {}

        # 并发处理所有组和维度
        tasks = []
        task_keys = []  # (group, dim_key) for result mapping

        for group in ["g1", "g2", "g3"]:
            for dim_key in eval_dims:
                tasks.append(self._analyze_dimension(group, dim_key))
                task_keys.append((group, dim_key))

        # 并发执行所有任务
        logger.info("[NLI] Starting concurrent analysis of %d tasks", len(tasks))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 按组整理结果
        for (group, dim_key), result in zip(task_keys, results):
            if isinstance(result, Exception):
                logger.error("[NLI] Error in %s/%s: %s", group, dim_key, result)
                continue
            if result:
                all_results.setdefault(group, []).append(result)

        return all_results

    async def _analyze_dimension(
        self,
        group: str,
        dim_key: str,
    ) -> Optional[DimensionNLIResult]:
        """Analyze a single dimension using Ground Truth.

        双维度评估：
        - Faithfulness: 报告声明是否被 Ground Truth 支持
        - Coverage: 报告是否覆盖了 Ground Truth 中的关键事实
        """
        from app.config.loader import get_dimension_name

        reports = self.data.get(group, {}).get("reports", {})

        content = reports.get(dim_key, "")
        if not content:
            return None

        dim_name = get_dimension_name(dim_key)

        # 使用 Ground Truth 作为知识依据
        ground_truth = self.ground_truth.get(dim_key, "")

        if not ground_truth:
            logger.warning("[NLI] No Ground Truth for %s, skipping", dim_key)
            return None

        # === Faithfulness 评估 ===
        # 从报告提取声明，判断是否被 Ground Truth 支持
        claims = extract_atomic_claims(content)

        if claims:
            faithfulness_rule = calculate_rule_faithfulness(claims, ground_truth)
            claim_texts = [c.text for c in claims]
            nli_results = await call_configured_llm_nli(claim_texts, ground_truth, dim_name)
            supported_nli = sum(1 for r in nli_results if r.verdict == "支持")
            faithfulness_nli = supported_nli / len(claims)

            for i, claim in enumerate(claims):
                if i < len(nli_results):
                    claim.is_supported = nli_results[i].verdict == "支持"
                    claim.support_evidence = nli_results[i].reason
        else:
            faithfulness_rule = 1.0
            faithfulness_nli = 1.0
            nli_results = []

        # === Coverage 评估 ===
        # 从 Ground Truth 提取关键事实，判断是否被报告覆盖
        key_facts = extract_key_facts(ground_truth)

        if key_facts:
            total_facts, covered_facts, coverage_nli = await evaluate_coverage_nli(
                key_facts, content, dim_name
            )
        else:
            total_facts, covered_facts, coverage_nli = 0, 0, 1.0

        logger.info(
            "[NLI] %s/%s: faith=%.2f, coverage=%.2f (%d/%d facts)",
            group, dim_key, faithfulness_nli, coverage_nli, covered_facts, total_facts
        )

        return DimensionNLIResult(
            dimension_key=dim_key,
            dimension_name=dim_name,
            group=group,
            total_claims=len(claims),
            supported_claims=supported_nli if claims else 0,
            faithfulness_nli=faithfulness_nli,
            faithfulness_rule=faithfulness_rule,
            nli_results=nli_results,
            knowledge_snippets=ground_truth[:200] + "..." if len(ground_truth) > 200 else ground_truth,
            claims=claims,
            # Coverage metrics
            total_key_facts=total_facts,
            covered_facts=covered_facts,
            coverage_nli=coverage_nli,
        )

    def generate_report(self, results: Dict[str, Any]) -> str:
        """Generate markdown comparison report with Coverage metrics."""
        lines = [
            "# RAG 优化效果评估报告",
            "",
            f"**分析时间**: {datetime.now().isoformat()}",
            "",
            "## 评估框架",
            "",
            "### 双维度评估",
            "",
            "| 指标 | 评估方向 | 说明 |",
            "|------|----------|------|",
            "| **Faithfulness** | Ground Truth → 报告 | 报告声明是否基于事实 |",
            "| **Coverage** | Ground Truth → 报告 | 报告是否覆盖关键信息 |",
            "",
            "### RAG 优化效果体现",
            "",
            "- **Faithfulness**: 各组应相近（都基于相同 Ground Truth）",
            "- **Coverage**: G3 > G2 > G1（RAG 提供更多上下文，覆盖更多信息）",
            "",
            "### Ground Truth 来源",
            "",
            "- **知识依据(knowledge)**: 来自现状报告，是忠实度评估的核心依据",
            "- 所有组使用相同的 Ground Truth，确保公平对比",
            "",
            "## 总体对比",
            "",
            "| 组别 | RAG配置 | Faithfulness | Coverage | 综合得分 |",
            "|------|---------|-------------|----------|----------|",
        ]

        # Calculate group summaries
        summaries = {}
        for group in ["g1", "g2", "g3"]:
            group_results = results.get(group, [])
            if group_results:
                avg_faith = sum(r.faithfulness_nli for r in group_results) / len(group_results)
                avg_coverage = sum(r.coverage_nli for r in group_results) / len(group_results)
                # 综合得分 = Faithfulness * Coverage (两者都很重要)
                combined = avg_faith * avg_coverage
                summaries[group] = {
                    "avg_faith": avg_faith,
                    "avg_coverage": avg_coverage,
                    "combined": combined,
                }

        rag_configs = {
            "g1": "无RAG",
            "g2": "L3 RAG",
            "g3": "L1+L3 RAG",
        }

        for group in ["g1", "g2", "g3"]:
            s = summaries.get(group, {})
            lines.append(
                f"| {group} | {rag_configs[group]} | "
                f"{s.get('avg_faith', 0):.2%} | {s.get('avg_coverage', 0):.2%} | "
                f"{s.get('combined', 0):.2%} |"
            )

        # RAG 效果分析
        g1_cov = summaries.get("g1", {}).get("avg_coverage", 0)
        g2_cov = summaries.get("g2", {}).get("avg_coverage", 0)
        g3_cov = summaries.get("g3", {}).get("avg_coverage", 0)

        lines.extend([
            "",
            "## RAG 优化效果分析",
            "",
            "### Coverage 提升（关键指标）",
            "",
            f"- G2 vs G1: {g2_cov - g1_cov:+.2%}（L3 RAG 效果）",
            f"- G3 vs G1: {g3_cov - g1_cov:+.2%}（L1+L3 RAG 效果）",
            f"- G3 vs G2: {g3_cov - g2_cov:+.2%}（L1 RAG 增量效果）",
            "",
            "### 结论",
            "",
        ])

        if g3_cov > g2_cov and g2_cov > g1_cov:
            lines.append("✅ **RAG 优化有效**: Coverage 随 RAG 配置增强而提升（G3 > G2 > G1）")
        elif g3_cov > g1_cov:
            lines.append("⚠️ **部分有效**: L1+L3 RAG 提升了 Coverage，但 L3 RAG 效果不明显")
        else:
            lines.append("❌ **效果不明显**: Coverage 没有随 RAG 配置提升")

        lines.extend([
            "",
            "## 各维度详细对比",
            "",
        ])

        for group in ["g1", "g2", "g3"]:
            group_results = results.get(group, [])
            lines.extend([
                f"### {group} ({rag_configs[group]})",
                "",
                "| 维度 | Faithfulness | Coverage | 关键事实覆盖 |",
                "|------|-------------|----------|-------------|",
            ])

            for r in group_results:
                lines.append(
                    f"| {r.dimension_name} | {r.faithfulness_nli:.2%} | {r.coverage_nli:.2%} | "
                    f"{r.covered_facts}/{r.total_key_facts} |"
                )

            lines.append("")

        # Coverage examples
        lines.extend([
            "## Coverage 示例",
            "",
            "以下展示 G3 在部分维度如何覆盖 Ground Truth 中的关键事实：",
            "",
        ])

        # Show coverage examples
        g3_results = results.get("g3", [])
        for r in g3_results[:2]:
            if r.total_key_facts > 0:
                lines.append(f"### {r.dimension_name}")
                lines.append("")
                lines.append(f"- 关键事实总数: {r.total_key_facts}")
                lines.append(f"- 覆盖数量: {r.covered_facts}")
                lines.append(f"- Coverage: {r.coverage_nli:.2%}")
                lines.append("")

        # Conclusion
        lines.extend([
            "## 评估方法说明",
            "",
            "1. **Faithfulness**: 使用已配置的 LLM 判断报告声明是否被 Ground Truth 支持",
            "2. **Coverage**: 使用已配置的 LLM 判断 Ground Truth 关键事实是否被报告覆盖",
            "3. **综合得分**: Faithfulness × Coverage，反映报告的整体质量",
            "",
            "---",
            "",
            "*本报告由 RAG Quality Analyzer 自动生成*",
        ])

        return "\n".join(lines)


# ============================================
# Main Entry
# ============================================

async def main():
    """Run NLI faithfulness analysis."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    base_dir = _PROJECT_ROOT / "output" / "experiments" / "rag"

    logger.info("[NLI] Starting NLI faithfulness analysis...")
    logger.info("[NLI] Base directory: %s", base_dir)

    analyzer = NLIFaithfulnessAnalyzer(base_dir)

    # Run analysis
    results = await analyzer.analyze_all()

    # Save JSON results
    output_dir = base_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert to serializable format
    json_results = {}
    for group, group_results in results.items():
        json_results[group] = [
            {
                "dimension_key": r.dimension_key,
                "dimension_name": r.dimension_name,
                "total_claims": r.total_claims,
                "supported_claims": r.supported_claims,
                "faithfulness_nli": r.faithfulness_nli,
                "faithfulness_rule": r.faithfulness_rule,
                "total_key_facts": r.total_key_facts,
                "covered_facts": r.covered_facts,
                "coverage_nli": r.coverage_nli,
                "claims": [c.text for c in r.claims],
                "nli_results": [
                    {"id": nr.claim_id, "verdict": nr.verdict, "reason": nr.reason}
                    for nr in r.nli_results
                ],
            }
            for r in group_results
        ]

    json_path = output_dir / "nli_analysis.json"
    json_path.write_text(
        json.dumps(json_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[NLI] JSON saved: %s", json_path)

    # Generate markdown report
    report = analyzer.generate_report(results)
    md_path = output_dir / "RAG优化效果评估报告.md"
    md_path.write_text(report, encoding="utf-8")
    logger.info("[NLI] Report saved: %s", md_path)

    # Print summary
    print("\n" + "=" * 60)
    print("RAG 优化效果评估完成")
    print("=" * 60)
    print(f"\n报告已保存至: {md_path}")
    print(f"详细数据已保存至: {json_path}")

    print("\n关键发现:")
    print("-" * 40)
    print(f"{'组别':<8} {'RAG配置':<12} {'Faithfulness':<12} {'Coverage':<10}")
    print("-" * 40)

    rag_configs = {"g1": "无RAG", "g2": "L3 RAG", "g3": "L1+L3 RAG"}
    for group in ["g1", "g2", "g3"]:
        group_results = results.get(group, [])
        if group_results:
            avg_faith = sum(r.faithfulness_nli for r in group_results) / len(group_results)
            avg_cov = sum(r.coverage_nli for r in group_results) / len(group_results)
            print(f"{group:<8} {rag_configs[group]:<12} {avg_faith:.2%}        {avg_cov:.2%}")

    # RAG effect summary
    g1_cov = sum(r.coverage_nli for r in results.get("g1", [])) / max(1, len(results.get("g1", [])))
    g3_cov = sum(r.coverage_nli for r in results.get("g3", [])) / max(1, len(results.get("g3", [])))
    print("-" * 40)
    print(f"\nRAG 优化效果: G3 vs G1 Coverage 提升 = {g3_cov - g1_cov:+.2%}")


if __name__ == "__main__":
    asyncio.run(main())
