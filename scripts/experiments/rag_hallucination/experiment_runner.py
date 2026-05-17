"""
Experiment Runner - Orchestrates multi-run RAG experiments

Responsibilities:
1. Run RAG ON/OFF experiments N times (default: 3)
2. Aggregate results across runs
3. Calculate mean and standard deviation
4. Export raw data for analysis

Usage:
    python scripts/experiments/rag_hallucination/experiment_runner.py --mode rag_on --runs 3
    python scripts/experiments/rag_hallucination/experiment_runner.py --mode rag_off --runs 3
    python scripts/experiments/rag_hallucination/experiment_runner.py --mode all --runs 3
"""

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend"))

from scripts.experiments.config import (
    RAG_ENABLED_DIMENSIONS,
    RAG_HALLUCINATION_DIR,
    RAG_ON_DIR,
    RAG_OFF_DIR,
    FIXED_CONTEXT_DIR,
    JINTIAN_VILLAGE_DATA,
    ensure_rag_experiment_dirs,
    check_kb_status,
)
from scripts.experiments.rag_hallucination.reference_extractor import (
    ReferenceExtractor,
    ExtractedReference,
    get_reference_statistics,
)
from scripts.experiments.rag_hallucination.hallucination_validator import (
    HallucinationValidator,
    ValidationResult,
    validate_references_batch,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


DIMENSION_NAMES = {
    "land_use_planning": "土地利用规划",
    "infrastructure_planning": "基础设施规划",
    "ecological": "生态绿地规划",
    "disaster_prevention": "防震减灾规划",
    "heritage": "历史文保规划",
}


@dataclass
class SingleRunResult:
    """单次运行结果"""
    run_id: int
    session_id: str
    mode: str
    dimension_key: str
    dimension_name: str
    report_content: str
    report_length: int
    references: List[Dict[str, Any]]
    validations: List[Dict[str, Any]]
    stats: Dict[str, Any]
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AggregatedDimensionResult:
    """聚合的维度结果"""
    dimension_key: str
    dimension_name: str
    mode: str
    runs: int
    total_refs_list: List[int]
    hallucinations_list: List[int]
    hallucination_rate_list: List[float]
    mean_total_refs: float
    mean_hallucinations: float
    mean_hallucination_rate: float
    std_hallucination_rate: float


@dataclass
class ExperimentResult:
    """实验结果"""
    mode: str
    runs: int
    dimensions: List[AggregatedDimensionResult]
    kb_sources: List[str]
    kb_context: str
    generated_at: str


class ExperimentRunner:
    """实验运行器"""

    def __init__(self, runs: int = 3, timeout: int = 600):
        self.runs = runs
        self.timeout = timeout
        self._extractor = ReferenceExtractor()
        self._validator = HallucinationValidator()
        self._kb_sources: List[str] = []
        self._kb_context: str = ""

    async def run_experiment_set(self, mode: str) -> ExperimentResult:
        logger.info(f"[ExperimentRunner] Starting {mode} experiment with {self.runs} runs")
        ensure_rag_experiment_dirs()
        self._load_kb_info()

        all_results: Dict[str, List[SingleRunResult]] = {}

        for run_id in range(1, self.runs + 1):
            logger.info(f"[ExperimentRunner] Run {run_id}/{self.runs} for {mode}")
            run_results = await self._run_single_experiment(mode, run_id)
            for dim_key, result in run_results.items():
                if dim_key not in all_results:
                    all_results[dim_key] = []
                all_results[dim_key].append(result)
            self._save_single_run_results(mode, run_id, run_results)

        aggregated = self._aggregate_results(mode, all_results)
        self._save_aggregated_results(mode, aggregated)
        return aggregated

    async def _run_single_experiment(self, mode: str, run_id: int) -> Dict[str, SingleRunResult]:
        saved_reports = self._load_saved_reports(mode, run_id)
        if saved_reports:
            logger.info(f"[ExperimentRunner] Using saved reports for {mode} run {run_id}")
            return self._process_saved_reports(mode, run_id, saved_reports)
        logger.warning(f"[ExperimentRunner] No saved reports found for {mode} run {run_id}")
        return {}

    def _load_saved_reports(self, mode: str, run_id: int) -> Optional[Dict[str, str]]:
        output_dir = RAG_ON_DIR if mode == "rag_on" else RAG_OFF_DIR
        reports_file = output_dir / f"run_{run_id}_reports.json"
        if reports_file.exists():
            with open(reports_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("reports", {})
        summary_file = output_dir / "experiment_summary.json"
        if summary_file.exists():
            with open(summary_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("reports", {})
        return None

    def _process_saved_reports(self, mode: str, run_id: int,
                               reports: Dict[str, str]) -> Dict[str, SingleRunResult]:
        results = {}
        for dim_key in RAG_ENABLED_DIMENSIONS:
            report_content = reports.get(dim_key, "")
            if not report_content:
                report_file = (RAG_ON_DIR if mode == "rag_on" else RAG_OFF_DIR) / f"{dim_key}.json"
                if report_file.exists():
                    with open(report_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        report_content = data.get("content", "")
            if report_content:
                references = self._extractor.extract_all_references(report_content)
                validations = validate_references_batch(
                    references, self._kb_context, self._kb_sources
                )
                stats = self._validator.get_validation_statistics(validations)
                results[dim_key] = SingleRunResult(
                    run_id=run_id,
                    session_id=f"{mode}_run_{run_id}",
                    mode=mode,
                    dimension_key=dim_key,
                    dimension_name=DIMENSION_NAMES.get(dim_key, dim_key),
                    report_content=report_content,
                    report_length=len(report_content),
                    references=[r.to_dict() for r in references],
                    validations=[v.to_dict() for v in validations],
                    stats=stats,
                )
        return results

    def _aggregate_results(self, mode: str,
                           all_results: Dict[str, List[SingleRunResult]]) -> ExperimentResult:
        aggregated_dimensions = []
        for dim_key, run_results in all_results.items():
            if not run_results:
                continue
            total_refs_list = [r.stats.get("total", 0) for r in run_results]
            hallucinations_list = [r.stats.get("hallucination", 0) for r in run_results]
            rate_list = [r.stats.get("hallucination_rate", 0) for r in run_results]
            mean_total = sum(total_refs_list) / len(total_refs_list) if total_refs_list else 0
            mean_hallucinations = sum(hallucinations_list) / len(hallucinations_list) if hallucinations_list else 0
            mean_rate = sum(rate_list) / len(rate_list) if rate_list else 0
            if len(rate_list) > 1:
                variance = sum((r - mean_rate) ** 2 for r in rate_list) / len(rate_list)
                std_rate = variance ** 0.5
            else:
                std_rate = 0.0
            aggregated_dimensions.append(AggregatedDimensionResult(
                dimension_key=dim_key,
                dimension_name=DIMENSION_NAMES.get(dim_key, dim_key),
                mode=mode,
                runs=len(run_results),
                total_refs_list=total_refs_list,
                hallucinations_list=hallucinations_list,
                hallucination_rate_list=rate_list,
                mean_total_refs=mean_total,
                mean_hallucinations=mean_hallucinations,
                mean_hallucination_rate=mean_rate,
                std_hallucination_rate=std_rate,
            ))
        return ExperimentResult(
            mode=mode,
            runs=self.runs,
            dimensions=aggregated_dimensions,
            kb_sources=self._kb_sources,
            kb_context=self._kb_context,
            generated_at=datetime.now().isoformat(),
        )

    def _save_single_run_results(self, mode: str, run_id: int, results: Dict[str, SingleRunResult]):
        output_dir = RAG_ON_DIR if mode == "rag_on" else RAG_OFF_DIR
        output_file = output_dir / f"run_{run_id}_results.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in results.items()}, f, indent=2, ensure_ascii=False)
        logger.info(f"[ExperimentRunner] Saved {output_file}")

    def _save_aggregated_results(self, mode: str, result: ExperimentResult):
        output_dir = RAG_ON_DIR if mode == "rag_on" else RAG_OFF_DIR
        output_file = output_dir / "aggregated_results.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(asdict(result), f, indent=2, ensure_ascii=False)
        logger.info(f"[ExperimentRunner] Saved aggregated results to {output_file}")

    def _load_kb_info(self):
        try:
            from app.services.modules.rag.service import RagService
            rag_service = RagService()
            stats = rag_service.get_stats()
            self._kb_sources = [d.get("source", "") for d in stats.get("documents", [])]
            logger.info(f"[ExperimentRunner] KB loaded: {len(self._kb_sources)} documents")
        except Exception as e:
            logger.warning(f"[ExperimentRunner] Failed to load KB: {e}")
            self._kb_sources = []
            self._kb_context = ""

    def get_kb_sources(self) -> List[str]:
        return self._kb_sources


def compare_rag_on_off(rag_on_result: ExperimentResult,
                       rag_off_result: ExperimentResult) -> Dict[str, Any]:
    comparison = {"dimensions": [], "overall": {"rag_on_mean_rate": 0.0, "rag_off_mean_rate": 0.0, "rate_reduction": 0.0}}
    for on_dim in rag_on_result.dimensions:
        off_dim = None
        for d in rag_off_result.dimensions:
            if d.dimension_key == on_dim.dimension_key:
                off_dim = d
                break
        if off_dim:
            rate_reduction = off_dim.mean_hallucination_rate - on_dim.mean_hallucination_rate
            comparison["dimensions"].append({
                "dimension_key": on_dim.dimension_key,
                "dimension_name": on_dim.dimension_name,
                "rag_on_total_refs": on_dim.mean_total_refs,
                "rag_on_hallucinations": on_dim.mean_hallucinations,
                "rag_on_rate": on_dim.mean_hallucination_rate,
                "rag_off_total_refs": off_dim.mean_total_refs,
                "rag_off_hallucinations": off_dim.mean_hallucinations,
                "rag_off_rate": off_dim.mean_hallucination_rate,
                "rate_reduction": rate_reduction,
            })
    if comparison["dimensions"]:
        comparison["overall"]["rag_on_mean_rate"] = sum(d["rag_on_rate"] for d in comparison["dimensions"]) / len(comparison["dimensions"])
        comparison["overall"]["rag_off_mean_rate"] = sum(d["rag_off_rate"] for d in comparison["dimensions"]) / len(comparison["dimensions"])
        comparison["overall"]["rate_reduction"] = comparison["overall"]["rag_off_mean_rate"] - comparison["overall"]["rag_on_mean_rate"]
    return comparison


async def run_full_experiment(runs: int = 3) -> Dict[str, Any]:
    runner = ExperimentRunner(runs=runs)
    rag_on_result = await runner.run_experiment_set("rag_on")
    rag_off_result = await runner.run_experiment_set("rag_off")
    comparison = compare_rag_on_off(rag_on_result, rag_off_result)
    comparison_file = RAG_HALLUCINATION_DIR / "comparison_results.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)
    logger.info(f"[ExperimentRunner] Saved comparison to {comparison_file}")
    return {"rag_on": asdict(rag_on_result), "rag_off": asdict(rag_off_result), "comparison": comparison}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="RAG Experiment Runner")
    parser.add_argument("--mode", default="all", choices=["rag_on", "rag_off", "all"])
    parser.add_argument("--runs", type=int, default=3, help="Number of runs")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"[ExperimentRunner] Starting - Mode: {args.mode}, Runs: {args.runs}")
    logger.info("=" * 60)

    kb_status = check_kb_status()
    logger.info(f"[ExperimentRunner] KB Status: {kb_status}")

    if args.mode == "all":
        result = asyncio.run(run_full_experiment(args.runs))
    elif args.mode == "rag_on":
        runner = ExperimentRunner(runs=args.runs)
        result = asyncio.run(runner.run_experiment_set("rag_on"))
    else:
        runner = ExperimentRunner(runs=args.runs)
        result = asyncio.run(runner.run_experiment_set("rag_off"))

    logger.info("=" * 60)
    logger.info("[ExperimentRunner] Completed")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()