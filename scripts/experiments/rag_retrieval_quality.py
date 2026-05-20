#!/usr/bin/env python3
"""
RAG Retrieval Quality Experiment
RAG 检索质量评估实验

评估当前 RAG 检索系统的效果，包括：
- 各维度检索成功率
- 检索延迟分析
- 空结果率统计
- 检索结果相关性评估

使用方法:
    python scripts/experiments/rag_retrieval_quality.py
    python scripts/experiments/rag_retrieval_quality.py --dimensions natural_environment,infrastructure
    python scripts/experiments/rag_retrieval_quality.py --output output/experiments/rag_quality/
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add project paths
script_dir = Path(__file__).parent.resolve()
project_root = script_dir.parent.parent.resolve()
backend_root = (project_root / "backend").resolve()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ============================================
# Data Classes
# ============================================

@dataclass
class RetrievalResult:
    """Single retrieval result"""
    query: str
    result_count: int
    latency_ms: float
    top_score: float
    avg_score: float
    context_length: int
    sources: List[str]
    is_empty: bool


@dataclass
class DimensionStats:
    """Statistics for a single dimension"""
    dimension_key: str
    dimension_name: str
    layer: int
    total_queries: int
    empty_results: int
    empty_rate: float
    avg_latency_ms: float
    avg_result_count: float
    avg_score: float
    total_context_length: int
    queries: List[RetrievalResult]


@dataclass
class ExperimentReport:
    """Full experiment report"""
    experiment_id: str
    started_at: str
    completed_at: str
    total_dimensions: int
    total_queries: int
    total_empty_results: int
    overall_empty_rate: float
    avg_latency_ms: float
    dimensions: List[DimensionStats]
    config: Dict[str, Any]


# ============================================
# Mock Config Class
# ============================================

@dataclass
class MockDimensionConfig:
    """Mock dimension config for testing"""
    key: str
    name: str
    rag_query: str
    depends_on: List[str] = field(default_factory=list)
    layer_depends_on: List[str] = field(default_factory=list)
    phase_depends_on: List[str] = field(default_factory=list)
    phase_id: str = "layer1"


# ============================================
# Dimension Configuration
# ============================================

LAYER1_DIMENSIONS = {
    "villager_wishes": ("村民意愿", "村民意愿调查方法 公众参与技术规范"),
    "superior_planning": ("上位规划衔接", "上位规划衔接要求 国土空间规划"),
    "natural_environment": ("自然环境分析", "村庄自然环境评价 地形地貌分析技术 生态敏感性评价"),
    "location": ("区位分析", "村庄区位分析方法 交通区位评价"),
    "history": ("历史沿革", "村庄历史沿革考证方法"),
    "population": ("人口分析", "村庄人口预测方法 人口规模测算"),
    "land_use_status": ("土地利用现状", "土地利用现状调查 用地分类标准"),
    "infrastructure": ("基础设施现状", "村庄基础设施配置标准 给排水设施规划"),
    "public_facilities": ("公共服务设施", "公共服务设施配置标准 村庄公共服务"),
    "architecture": ("建筑现状", "村庄建筑质量评价 农房建设标准"),
    "traffic": ("交通现状", "村庄道路等级分类 交通可达性分析"),
    "historical_culture": ("历史文化", "历史文化保护规划 传统村落保护要求"),
    "landscape": ("景观风貌", "村庄景观风貌规划 乡土景观设计"),
    "safety": ("安全防灾", "村庄防灾规划 地质灾害防治"),
    "economic": ("经济发展", "村庄产业发展规划 经济发展预测"),
}

LAYER2_DIMENSIONS = {
    "planning_positioning": ("规划定位", "村庄规划定位方法 发展目标确定"),
    "development_scale": ("发展规模", "村庄发展规模预测 人口用地规模"),
    "land_use_layout": ("用地布局", "村庄用地布局规划 功能分区"),
    "project_bank": ("项目库", "村庄项目库编制 项目安排"),
}


# ============================================
# Experiment Functions
# ============================================

async def run_retrieval_experiment(
    dimensions: List[str] = None,
    top_k: int = 5,
    output_dir: Path = None,
) -> ExperimentReport:
    """
    Run RAG retrieval quality experiment.

    Args:
        dimensions: List of dimension keys to test (None = all)
        top_k: Number of results to retrieve
        output_dir: Output directory for results

    Returns:
        Experiment report
    """
    from app.services.modules.rag.service import RagService

    experiment_id = f"rag_quality_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    started_at = datetime.now().isoformat()

    logger.info(f"[Experiment] Starting RAG quality experiment: {experiment_id}")
    logger.info(f"[Experiment] Config: top_k={top_k}")

    # Initialize RAG service
    rag_service = RagService.get_instance()

    # Determine dimensions to test
    if dimensions:
        test_dimensions = {k: v for k, v in {**LAYER1_DIMENSIONS, **LAYER2_DIMENSIONS}.items() if k in dimensions}
    else:
        test_dimensions = {**LAYER1_DIMENSIONS, **LAYER2_DIMENSIONS}

    logger.info(f"[Experiment] Testing {len(test_dimensions)} dimensions")

    dimension_stats_list: List[DimensionStats] = []
    total_queries = 0
    total_empty = 0
    total_latency = 0

    for dim_key, (dim_name, rag_query) in test_dimensions.items():
        # Determine layer
        layer = 1 if dim_key in LAYER1_DIMENSIONS else 2

        logger.info(f"[Experiment] Testing dimension: {dim_key} ({dim_name})")

        # Create mock config
        cfg = MockDimensionConfig(
            key=dim_key,
            name=dim_name,
            rag_query=rag_query,
            phase_id=f"layer{layer}",
        )

        # Mock state
        state = {
            "session_id": f"experiment_{experiment_id}",
            "completed_dimensions": {},
        }

        # Generate queries using LLM
        try:
            queries = await rag_service.generate_queries(cfg, state)
        except Exception as e:
            logger.warning(f"[Experiment] Failed to generate queries for {dim_key}: {e}")
            queries = [rag_query]

        logger.info(f"[Experiment] Generated {len(queries)} queries for {dim_key}: {queries[:2]}...")

        # Run retrieval for each query
        retrieval_results: List[RetrievalResult] = []
        dim_latency_total = 0
        dim_empty_count = 0

        for query in queries:
            start_time = time.time()

            try:
                results = await rag_service.search(query, top_k=top_k)

                latency_ms = (time.time() - start_time) * 1000

                if results:
                    scores = [r.get("score", 0) for r in results]
                    sources = list(set(r.get("metadata", {}).get("source", "") for r in results if r.get("metadata", {}).get("source")))
                    context_length = sum(len(r.get("content", "")) for r in results)

                    result = RetrievalResult(
                        query=query,
                        result_count=len(results),
                        latency_ms=latency_ms,
                        top_score=min(scores) if scores else 0,  # L2 distance, smaller is better
                        avg_score=sum(scores) / len(scores) if scores else 0,
                        context_length=context_length,
                        sources=sources,
                        is_empty=False,
                    )
                else:
                    result = RetrievalResult(
                        query=query,
                        result_count=0,
                        latency_ms=latency_ms,
                        top_score=0,
                        avg_score=0,
                        context_length=0,
                        sources=[],
                        is_empty=True,
                    )
                    dim_empty_count += 1

            except Exception as e:
                logger.warning(f"[Experiment] Retrieval failed for query '{query}': {e}")
                result = RetrievalResult(
                    query=query,
                    result_count=0,
                    latency_ms=0,
                    top_score=0,
                    avg_score=0,
                    context_length=0,
                    sources=[],
                    is_empty=True,
                )
                dim_empty_count += 1

            retrieval_results.append(result)
            dim_latency_total += result.latency_ms

        # Calculate dimension statistics
        dim_avg_latency = dim_latency_total / len(retrieval_results) if retrieval_results else 0
        dim_avg_count = sum(r.result_count for r in retrieval_results) / len(retrieval_results) if retrieval_results else 0
        non_empty_results = [r for r in retrieval_results if not r.is_empty]
        dim_avg_score = sum(r.avg_score for r in non_empty_results) / len(non_empty_results) if non_empty_results else 0
        dim_empty_rate = dim_empty_count / len(retrieval_results) * 100 if retrieval_results else 0
        dim_context_length = sum(r.context_length for r in retrieval_results)

        dim_stats = DimensionStats(
            dimension_key=dim_key,
            dimension_name=dim_name,
            layer=layer,
            total_queries=len(retrieval_results),
            empty_results=dim_empty_count,
            empty_rate=dim_empty_rate,
            avg_latency_ms=dim_avg_latency,
            avg_result_count=dim_avg_count,
            avg_score=dim_avg_score,
            total_context_length=dim_context_length,
            queries=retrieval_results,
        )

        dimension_stats_list.append(dim_stats)
        total_queries += len(retrieval_results)
        total_empty += dim_empty_count
        total_latency += dim_latency_total

        logger.info(f"[Experiment] {dim_key}: {len(retrieval_results)} queries, {dim_empty_count} empty ({dim_empty_rate:.1f}%), avg latency {dim_avg_latency:.0f}ms")

    # Calculate overall statistics
    completed_at = datetime.now().isoformat()
    overall_empty_rate = total_empty / total_queries * 100 if total_queries > 0 else 0
    avg_latency = total_latency / total_queries if total_queries > 0 else 0

    report = ExperimentReport(
        experiment_id=experiment_id,
        started_at=started_at,
        completed_at=completed_at,
        total_dimensions=len(dimension_stats_list),
        total_queries=total_queries,
        total_empty_results=total_empty,
        overall_empty_rate=overall_empty_rate,
        avg_latency_ms=avg_latency,
        dimensions=dimension_stats_list,
        config={
            "top_k": top_k,
        },
    )

    # Save report
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        report_file = output_dir / f"{experiment_id}_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"[Experiment] Report saved to {report_file}")

    # Print summary
    print("\n" + "=" * 70)
    print("RAG Retrieval Quality Experiment Summary")
    print("=" * 70)
    print(f"Experiment ID: {experiment_id}")
    print(f"Total Dimensions: {len(dimension_stats_list)}")
    print(f"Total Queries: {total_queries}")
    print(f"Empty Results: {total_empty} ({overall_empty_rate:.1f}%)")
    print(f"Average Latency: {avg_latency:.0f}ms")
    print("\nPer-Dimension Summary:")
    print("-" * 70)
    print(f"{'Dimension':<25} | {'Queries':>7} | {'Empty':>10} | {'Latency':>8} | {'Context':>8}")
    print("-" * 70)

    for dim in sorted(dimension_stats_list, key=lambda x: -x.empty_rate):
        status = "OK" if dim.empty_rate == 0 else f"{dim.empty_rate:.0f}% EMPTY"
        print(f"{dim.dimension_key:<25} | {dim.total_queries:>7} | {status:>10} | {dim.avg_latency_ms:>6.0f}ms | {dim.total_context_length:>7}c")

    return report


# ============================================
# Main Entry Point
# ============================================

async def main():
    parser = argparse.ArgumentParser(description="RAG Retrieval Quality Experiment")
    parser.add_argument("--dimensions", type=str, help="Comma-separated dimension keys to test")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to retrieve")
    parser.add_argument("--output", type=str, help="Output directory")

    args = parser.parse_args()

    # Parse dimensions
    dimensions = args.dimensions.split(",") if args.dimensions else None

    # Parse output directory
    output_dir = Path(args.output) if args.output else project_root / "output" / "experiments" / "rag_quality"

    await run_retrieval_experiment(
        dimensions=dimensions,
        top_k=args.top_k,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    asyncio.run(main())
