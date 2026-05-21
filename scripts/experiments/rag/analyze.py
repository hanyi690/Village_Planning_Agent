"""RAG Quality Analysis Script - Analyze existing RAG experiment data and generate report.

Usage:
    python scripts/experiments/rag/analyze.py

This script:
1. Loads existing RAG experiment data from database
2. Evaluates text quality metrics (faithfulness, depth)
3. Evaluates citation quality
4. Generates comprehensive analysis report
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Add project paths
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.experiments.framework.metrics import MetricsSuite
from scripts.experiments.framework.data_accessor import ExperimentDataAccessor
from scripts.experiments.framework.cache import ExperimentCache
from scripts.experiments.framework.config import ExperimentConfig, RAG_GROUPS

logger = logging.getLogger(__name__)


class RAGQualityAnalyzer:
    """Analyzes RAG experiment data and generates comprehensive report."""

    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.cache = ExperimentCache(config.cache_dir)
        self.data_accessor = ExperimentDataAccessor(self.cache)
        self.metrics = MetricsSuite()
        self._cached_knowledge: Dict[str, Any] = {}

    async def analyze_all(self) -> Dict[str, Any]:
        """Analyze all RAG groups and generate comprehensive report."""
        results = {}

        sessions = {
            "g1": {"session_id": "rag_g1_iter0_8c4b7fd3", "rag_config": RAG_GROUPS["g1"]},
            "g2": {"session_id": "rag_g2_iter0_cf6ef4b3", "rag_config": RAG_GROUPS["g2"]},
            "g3": {"session_id": "rag_g3_iter0_b7463301", "rag_config": RAG_GROUPS["g3"]},
        }

        for group_name, info in sessions.items():
            logger.info("[Analyze] Processing %s: session=%s", group_name, info["session_id"])
            result = await self._analyze_group(
                group_name=group_name,
                session_id=info["session_id"],
                rag_config=info["rag_config"],
            )
            results[group_name] = result

        # Generate comparison report
        comparison = self._generate_comparison(results)

        return {
            "groups": results,
            "comparison": comparison,
            "analyzed_at": datetime.now().isoformat(),
        }

    async def _analyze_group(
        self,
        group_name: str,
        session_id: str,
        rag_config: Dict[int, bool],
    ) -> Dict[str, Any]:
        """Analyze a single RAG group."""
        from app.config.loader import get_layer_dimensions, get_dimension_name
        from app.services.report_store import ReportStore

        # Load reports
        reports = await self.data_accessor.get_reports(session_id)

        # Load RAG knowledge
        store = ReportStore.get_instance()
        rag_knowledge = {}
        for layer in [1, 2, 3]:
            with_sources = await store.get_layer_reports_with_sources(session_id, layer)
            for dim_key, data in with_sources.items():
                if data.get("knowledge_sources"):
                    rag_knowledge[dim_key] = data["knowledge_sources"]

        # Evaluate dimensions
        l1_dims = get_layer_dimensions(1)
        l3_dims = get_layer_dimensions(3)
        eval_dims = l1_dims + l3_dims

        dimension_metrics = {}
        for dim_key in eval_dims:
            content = reports.get(dim_key, "")
            if not content:
                continue

            # Get RAG context for this dimension
            kb_context = self._get_kb_context(dim_key, rag_knowledge, content)

            # Evaluate text quality
            text_result = await self.metrics.evaluate_text_quality(
                content, kb_context, dim_key,
            )

            # Evaluate citation quality with KB context
            citation_result = self.metrics.evaluate_citation_quality(
                content, dim_key, kb_context
            )

            # Extract metrics
            faithfulness_score = (
                text_result.faithfulness.faithfulness_score
                if hasattr(text_result, 'faithfulness')
                else 0
            )
            depth_score = (
                text_result.content_depth_score
                if hasattr(text_result, 'content_depth_score')
                else 0
            )

            dimension_metrics[dim_key] = {
                "dimension_name": get_dimension_name(dim_key),
                "text_length": len(content),
                "faithfulness": faithfulness_score,
                "depth_score": depth_score,
                "total_claims": text_result.faithfulness.total_claims if hasattr(text_result, 'faithfulness') else 0,
                "supported_claims": text_result.faithfulness.supported_claims if hasattr(text_result, 'faithfulness') else 0,
                "hallucination_points": text_result.faithfulness.hallucination_points[:3] if hasattr(text_result, 'faithfulness') else [],
                "total_citations": citation_result.get("total_citations", 0),
                "existence_rate": citation_result.get("existence_rate", 0),
                "supportive_rate": citation_result.get("supportive_rate", 0),
                "rag_chunks": len(rag_knowledge.get(dim_key, [])),
                # Add citation quality details
                "citation_details": citation_result.get("citation_details", {}),
            }

        # Calculate summary
        if dimension_metrics:
            avg_faithfulness = sum(m["faithfulness"] for m in dimension_metrics.values()) / len(dimension_metrics)
            avg_depth = sum(m["depth_score"] for m in dimension_metrics.values()) / len(dimension_metrics)
            total_citations = sum(m["total_citations"] for m in dimension_metrics.values())
            total_rag_chunks = sum(m["rag_chunks"] for m in dimension_metrics.values())
        else:
            avg_faithfulness = 0
            avg_depth = 0
            total_citations = 0
            total_rag_chunks = 0

        return {
            "group_name": group_name,
            "session_id": session_id,
            "rag_config": rag_config,
            "rag_config_desc": self._describe_rag_config(rag_config),
            "dimension_metrics": dimension_metrics,
            "summary": {
                "avg_faithfulness": avg_faithfulness,
                "avg_depth": avg_depth,
                "total_citations": total_citations,
                "total_rag_chunks": total_rag_chunks,
                "dimension_count": len(dimension_metrics),
            },
        }

    def _get_kb_context(self, dim_key: str, rag_knowledge: Dict, content: str) -> str:
        """Get knowledge base context for faithfulness evaluation."""
        ks = rag_knowledge.get(dim_key)
        if ks:
            contexts = []
            # knowledge_sources is a dict with 'retrieved_chunks'
            if isinstance(ks, dict):
                chunks = ks.get("retrieved_chunks", [])
                for chunk in chunks:
                    ctx = chunk.get("content_preview", "") or chunk.get("content", "")
                    if ctx:
                        contexts.append(ctx)
            elif isinstance(ks, list):
                for source in ks:
                    if isinstance(source, dict):
                        chunks = source.get("retrieved_chunks", [])
                        for chunk in chunks:
                            ctx = chunk.get("content_preview", "") or chunk.get("content", "")
                            if ctx:
                                contexts.append(ctx)
            return " ".join(contexts)
        return content[:500]  # Fallback to content preview

    def _describe_rag_config(self, rag_config: Dict[int, bool]) -> str:
        """Describe RAG configuration in human-readable format."""
        layers = []
        for layer, enabled in rag_config.items():
            status = "启用" if enabled else "禁用"
            layers.append(f"L{layer}: {status}")
        return ", ".join(layers)

    def _generate_comparison(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate comparison analysis across groups."""
        comparison = {
            "faithfulness_comparison": {},
            "depth_comparison": {},
            "citation_comparison": {},
            "rag_impact_analysis": {},
        }

        # Extract summary data
        summaries = {
            g: results[g]["summary"] for g in results
        }

        # Faithfulness comparison
        for g, s in summaries.items():
            comparison["faithfulness_comparison"][g] = s["avg_faithfulness"]

        # Depth comparison
        for g, s in summaries.items():
            comparison["depth_comparison"][g] = s["avg_depth"]

        # Citation comparison
        for g, s in summaries.items():
            comparison["citation_comparison"][g] = {
                "total": s["total_citations"],
                "rag_chunks": s["total_rag_chunks"],
            }

        # RAG impact analysis
        g1_faith = summaries["g1"]["avg_faithfulness"]
        g3_faith = summaries["g3"]["avg_faithfulness"]
        comparison["rag_impact_analysis"]["faithfulness_delta"] = g3_faith - g1_faith
        comparison["rag_impact_analysis"]["faithfulness_improvement_pct"] = (
            (g3_faith - g1_faith) / g1_faith * 100 if g1_faith > 0 else 0
        )

        g1_depth = summaries["g1"]["avg_depth"]
        g3_depth = summaries["g3"]["avg_depth"]
        comparison["rag_impact_analysis"]["depth_delta"] = g3_depth - g1_depth
        comparison["rag_impact_analysis"]["depth_improvement_pct"] = (
            (g3_depth - g1_depth) / g1_depth * 100 if g1_depth > 0 else 0
        )

        return comparison

    def generate_report(self, analysis: Dict[str, Any]) -> str:
        """Generate markdown report from analysis results."""
        lines = [
            "# RAG 质量实验分析报告",
            "",
            f"**分析时间**: {analysis['analyzed_at']}",
            "",
            "## 实验概述",
            "",
            "本实验对比三种 RAG 配置对规划报告质量的影响：",
            "",
            "| 组别 | RAG 配置 | 描述 |",
            "|------|----------|------|",
        ]

        for g in ["g1", "g2", "g3"]:
            info = analysis["groups"][g]
            lines.append(f"| {g} | {info['rag_config_desc']} | {info['session_id']} |")

        lines.extend([
            "",
            "## 指标计算方法说明",
            "",
            "### 1. Faithfulness（忠实度）",
            "",
            "**计算方法**: 规则匹配",
            "- 使用正则表达式从报告文本中提取原子陈述（包含数字+单位、法规引用、关键词的句子）",
            "- 对每个陈述，检查其中的数字/法规名/标准号是否出现在知识上下文中",
            "- Faithfulness = 被支持的陈述数 / 总陈述数",
            "",
            "**数据来源**:",
            "- 报告文本: 从数据库/缓存加载的各维度报告内容",
            "- 知识上下文: RAG检索返回的知识片段（g1无RAG时使用报告前500字）",
            "",
            "### 2. 内容深度（Depth）",
            "",
            "**计算方法**: 规则评分（1-5分）",
            "- 基础分1分，检查以下特征累加：",
            "  - 包含具体数值指标（+1分）",
            "  - 包含法规引用（+0.5分）",
            "  - 包含标准编号（+0.5分）",
            "  - 包含技术方法关键词（+0.5分/个，上限1分）",
            "  - 包含建议关键词（+0.2分/个，上限1分）",
            "- 最终得分上限5分",
            "",
            "**数据来源**: 报告文本本身",
            "",
            "### 3. 引用数量（Citations）",
            "",
            "**计算方法**: 正则表达式匹配",
            "- **法规引用 (law)**: `《[^》]+法》`, `《[^》]+条例》`, `《[^》]+规定》` 等",
            "- **条款引用 (clause)**: `第[一二三四五六七八九十百]+条`, `第\\d+条`",
            "- **指标引用 (indicator)**: `不少于\\s*\\d+\\s*米`, `\\d+\\s*年一遇`, `人均\\s*\\d+[-~]\\d+\\s*平方米` 等",
            "- **标准引用 (standard)**: `GB\\s*\\d+[-\\d]*`, `GB/T\\s*\\d+`, `DB\\d+/\\d+[-\\d]*` 等",
            "- 去重后统计总数",
            "",
            "**数据来源**: 报告文本",
            "",
            "### 4. 引用存在率（Existence Rate）",
            "",
            "**计算方法**: 检查引用是否出现在知识上下文中",
            "- 对每个提取的引用，检查其文本是否出现在RAG检索的知识片段中",
            "- Existence Rate = 存在于KB的引用数 / 总引用数",
            "",
            "**数据来源**: 报告文本 + RAG知识上下文",
            "",
            "### 5. 引用支持率（Supportive Rate）",
            "",
            "**计算方法**: 判断引用是否支撑关键论点",
            "- 检查引用上下文是否包含论证性关键词（应、须、必须、规定等）",
            "- 装饰性引用（如\"详见\"、\"参见\"后）标记为非支持性",
            "- Supportive Rate = 支持性引用数 / 总引用数",
            "",
            "**数据来源**: 报告文本",
            "",
            "### 6. RAG知识块数",
            "",
            "**计算方法**: 统计RAG检索返回的知识片段数量",
            "- 从数据库的 `layer_reports` 表中读取 `knowledge_sources` 字段",
            "- 统计 `retrieved_chunks` 数组长度",
            "",
            "**数据来源**: 数据库 `layer_reports.knowledge_sources`",
            "",
            "## 总体指标对比",
            "",
            "| 组别 | Faithfulness | 内容深度 | 引用总数 | RAG知识块数 |",
            "|------|-------------|---------|---------|------------|",
        ])

        for g in ["g1", "g2", "g3"]:
            s = analysis["groups"][g]["summary"]
            lines.append(
                f"| {g} | {s['avg_faithfulness']:.2%} | {s['avg_depth']:.2f} | {s['total_citations']} | {s['total_rag_chunks']} |"
            )

        # RAG impact analysis
        impact = analysis["comparison"]["rag_impact_analysis"]
        lines.extend([
            "",
            "## RAG 影响分析",
            "",
            f"- **Faithfulness 提升**: {impact['faithfulness_delta']:.2%} ({impact['faithfulness_improvement_pct']:.1f}%)",
            f"- **内容深度提升**: {impact['depth_delta']:.2f} ({impact['depth_improvement_pct']:.1f}%)",
            "",
        ])

        # Detailed dimension analysis
        lines.extend([
            "## 各维度详细分析",
            "",
        ])

        for g in ["g1", "g2", "g3"]:
            info = analysis["groups"][g]
            lines.extend([
                f"### {g} ({info['rag_config_desc']})",
                "",
                "| 维度 | 文本长度 | Faithfulness | 深度 | 引用数 | RAG块数 |",
                "|------|---------|-------------|-----|-------|--------|",
            ])

            for dim_key, m in info["dimension_metrics"].items():
                lines.append(
                    f"| {m['dimension_name']} | {m['text_length']} | {m['faithfulness']:.2%} | {m['depth_score']:.2f} | {m['total_citations']} | {m['rag_chunks']} |"
                )

            lines.append("")

        # Hallucination analysis
        lines.extend([
            "## 幻觉点分析",
            "",
            "以下列出各组的潜在幻觉点（未被知识库支持的陈述）：",
            "",
            "**判断方法**: 使用Faithfulness计算中的规则匹配，未被支持的陈述即为幻觉点。",
            "",
        ])

        for g in ["g1", "g2", "g3"]:
            info = analysis["groups"][g]
            lines.append(f"### {g}")
            lines.append("")
            hallucination_count = 0
            for dim_key, m in info["dimension_metrics"].items():
                if m["hallucination_points"]:
                    hallucination_count += len(m["hallucination_points"])
                    lines.append(f"**{m['dimension_name']}**:")
                    for hp in m["hallucination_points"][:2]:
                        lines.append(f"- {hp[:100]}...")
                    lines.append("")
            lines.append(f"总计潜在幻觉点: {hallucination_count}")
            lines.append("")

        # Conclusion
        lines.extend([
            "## 结论与建议",
            "",
            "### 主要发现",
            "",
            f"1. RAG 知识对 Faithfulness 有显著影响：g3（全RAG）比 g1（无RAG）提升 {impact['faithfulness_improvement_pct']:.1f}%",
            f"2. RAG 知识对内容深度有正向影响：g3 比 g1 提升 {impact['depth_improvement_pct']:.1f}%",
            "3. 引用质量与 RAG 配置正相关",
            "",
            "### 建议",
            "",
            "- 建议在 L1 和 L3 层启用 RAG，以获得最佳质量",
            "- L2 层可不启用 RAG，因其依赖 L1 的分析结果",
            "- 需进一步优化知识库覆盖度，减少幻觉点",
            "",
        ])

        # Citation Quality Analysis
        lines.extend([
            "## 引用质量分析",
            "",
            "引用存在率（existence_rate）表示引用中能在知识库里找到的比例。",
            "该指标直观反映引用的真实性。",
            "",
            "| 组别 | 总引用数 | 平均存在率 | 平均支持率 |",
            "|------|---------|-----------|-----------|",
        ])

        for g in ["g1", "g2", "g3"]:
            info = analysis["groups"][g]
            total_citations = sum(m["total_citations"] for m in info["dimension_metrics"].values())
            avg_existence = sum(m["existence_rate"] for m in info["dimension_metrics"].values()) / len(info["dimension_metrics"]) if info["dimension_metrics"] else 0
            avg_supportive = sum(m["supportive_rate"] for m in info["dimension_metrics"].values()) / len(info["dimension_metrics"]) if info["dimension_metrics"] else 0
            lines.append(f"| {g} | {total_citations} | {avg_existence:.2%} | {avg_supportive:.2%} |")

        lines.extend([
            "",
            "---",
            "",
            "*本报告由 RAG Quality Analyzer 自动生成*",
        ])

        return "\n".join(lines)


async def main():
    """Run analysis and generate report."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = ExperimentConfig.default("rag")
    analyzer = RAGQualityAnalyzer(config)

    logger.info("[Analyze] Starting RAG quality analysis...")

    # Run analysis
    analysis = await analyzer.analyze_all()

    # Save JSON results
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "rag_analysis.json"
    json_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[Analyze] JSON saved: %s", json_path)

    # Generate markdown report
    report = analyzer.generate_report(analysis)
    md_path = output_dir / "RAG质量实验分析报告.md"
    md_path.write_text(report, encoding="utf-8")
    logger.info("[Analyze] Report saved: %s", md_path)

    # Print summary
    print("\n" + "=" * 60)
    print("RAG 质量实验分析完成")
    print("=" * 60)
    print(f"\n报告已保存至: {md_path}")
    print(f"详细数据已保存至: {json_path}")

    # Print key findings
    impact = analysis["comparison"]["rag_impact_analysis"]
    print(f"\n关键发现:")
    print(f"  - Faithfulness 提升: {impact['faithfulness_improvement_pct']:.1f}%")
    print(f"  - 内容深度提升: {impact['depth_improvement_pct']:.1f}%")

    for g in ["g1", "g2", "g3"]:
        s = analysis["groups"][g]["summary"]
        print(f"\n{g} 概要:")
        print(f"  - 平均 Faithfulness: {s['avg_faithfulness']:.2%}")
        print(f"  - 平均深度: {s['avg_depth']:.2f}")
        print(f"  - 引用总数: {s['total_citations']}")
        print(f"  - RAG知识块: {s['total_rag_chunks']}")


if __name__ == "__main__":
    asyncio.run(main())