"""
Cascade Consistency Experiment - Simplified and Clear
级联一致性实验 - 简化版

实验目标：
验证驳回操作后，下游维度的修订是否保持语义一致性。

实验设计：
1. 基线运行：生成完整的28维度规划报告
2. 驳回操作：对目标维度提交反馈
3. 级联修订：观察下游维度的自动修订
4. 一致性检验：对比修订前后，检验语义一致性

一致性定义：
- 目标维度：修订内容应响应反馈（关键词覆盖率）
- 下游维度：修订内容应与目标维度修订方向一致（语义对齐）

输出：
- baseline_reports.json: 基线报告
- revision_diffs.json: 修订前后对比
- consistency_scores.json: 一致性评分

Usage:
    python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario1
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend"))

from scripts.experiments.config import (
    CASCADE_DIR,
    BASELINE_DIR,
    SCENARIO1_DIR,
    SCENARIO2_DIR,
    SCENARIOS,
    JINTIAN_VILLAGE_DATA,
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    ensure_cascade_dirs,
    get_scenario_config,
    get_output_dir,
)
from scripts.experiments.cascade_consistency.consistency_checker import (
    ConsistencyChecker,
    ConsistencyResult,
    check_semantic_alignment,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


@dataclass
class RevisionDiff:
    """修订差异"""
    dimension_key: str
    dimension_name: str
    layer: int
    wave: int
    is_target: bool
    old_content: str
    new_content: str
    content_length_diff: int
    keywords_added: List[str]
    keywords_removed: List[str]


@dataclass
class ExperimentResult:
    """实验结果"""
    scenario_name: str
    session_id: str
    target_dimension: str
    impact_tree: Dict[int, List[str]]
    revision_diffs: List[RevisionDiff]
    consistency_scores: Dict[str, float]
    overall_consistency: float
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class CascadeExperimentRunner:
    """级联一致性实验运行器"""

    def __init__(self, scenario_name: str):
        self.scenario_name = scenario_name
        self.config = get_scenario_config(scenario_name)
        self.checker = ConsistencyChecker()

    async def run_experiment(self) -> ExperimentResult:
        """运行完整实验"""
        logger.info(f"[Experiment] Starting {self.scenario_name}: {self.config['name']}")

        # 1. 计算影响树
        impact_tree = self._calculate_impact_tree()
        logger.info(f"[Experiment] Impact tree: {len(impact_tree)} waves")

        # 2. 获取基线报告（从现有文件或运行新基线）
        baseline_reports = await self._get_baseline_reports()

        # 3. 执行驳回和修订（需要运行时服务）
        revision_reports = await self._execute_revision(baseline_reports)

        # 4. 计算修订差异
        revision_diffs = self._calculate_diffs(baseline_reports, revision_reports)

        # 5. 检验一致性
        consistency_scores = self._check_consistency(revision_diffs)

        # 6. 计算总体一致性
        overall = sum(consistency_scores.values()) / len(consistency_scores) if consistency_scores else 0.0

        return ExperimentResult(
            scenario_name=self.scenario_name,
            session_id=f"{self.scenario_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            target_dimension=self.config["target_dimension"],
            impact_tree=impact_tree,
            revision_diffs=revision_diffs,
            consistency_scores=consistency_scores,
            overall_consistency=overall,
        )

    def _calculate_impact_tree(self) -> Dict[int, List[str]]:
        """计算影响树"""
        from app.config.dependency import get_impact_tree_compat

        target_dim = self.config["target_dimension"]
        tree = get_impact_tree_compat(target_dim)

        # 添加目标维度作为wave 0
        full_tree = {0: [target_dim]}
        for wave, dims in tree.items():
            full_tree[wave] = dims

        return full_tree

    async def _get_baseline_reports(self) -> Dict[str, str]:
        """获取基线报告"""
        # 尝试加载现有基线
        baseline_file = BASELINE_DIR / "baseline_reports.json"
        if baseline_file.exists():
            with open(baseline_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"[Experiment] Loaded existing baseline: {len(data)} dimensions")
            return data

        # 需要运行基线
        logger.warning("[Experiment] No baseline found, please run baseline first")
        logger.info("[Experiment] Use: python scripts/experiments/cascade_consistency/run_baseline.py")
        return {}

    async def _execute_revision(self, baseline_reports: Dict[str, str]) -> Dict[str, str]:
        """执行驳回和修订"""
        from app.services.runtime import PlanningRuntimeService
        from app.services.review import review_service
        from app.services.checkpoint import checkpoint_service
        from starlette.background import BackgroundTasks

        target_dim = self.config["target_dimension"]
        feedback = self.config["feedback"]

        logger.info(f"[Experiment] Executing reject on {target_dim}")

        # 启动新会话（使用基线状态）
        background_tasks = BackgroundTasks()

        result = await PlanningRuntimeService.start_session(
            project_name=f"级联实验_{self.scenario_name}",
            village_data=JINTIAN_VILLAGE_DATA.get("status_report", ""),
            village_name=JINTIAN_VILLAGE_DATA.get("village_name", "金田村"),
            task_description=DEFAULT_TASK_DESCRIPTION,
            constraints=DEFAULT_CONSTRAINTS,
            step_mode=False,
            background_tasks=background_tasks,
        )

        session_id = result.get("task_id")
        logger.info(f"[Experiment] Session started: {session_id}")

        # 等待完成
        await background_tasks()

        # 执行驳回
        await review_service.reject(
            session_id=session_id,
            feedback=feedback,
            dimensions=[target_dim],
        )

        # 触发修订
        await PlanningRuntimeService.resume_execution(session_id)

        # 等待修订完成
        await self._wait_for_revision(session_id, timeout=600)

        # 获取修订后的报告
        state = await checkpoint_service.get_state(session_id, wait_for_write=True)
        reports = {}
        if state:
            for layer_key in ["layer1", "layer2", "layer3"]:
                layer_reports = state.get("reports", {}).get(layer_key, {})
                reports.update(layer_reports)

        return reports

    async def _wait_for_revision(self, session_id: str, timeout: int = 600):
        """等待修订完成"""
        from app.services.checkpoint import checkpoint_service

        start_time = datetime.now()
        check_interval = 10

        while True:
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                logger.warning(f"[Experiment] Revision timeout after {elapsed}s")
                break

            state = await checkpoint_service.get_state(session_id, wait_for_write=True)
            if state:
                need_revision = state.get("need_revision", False)
                revision_history = state.get("revision_history", [])

                if not need_revision and len(revision_history) > 0:
                    logger.info(f"[Experiment] Revision completed: {len(revision_history)} dims")
                    return

            await asyncio.sleep(check_interval)

    def _calculate_diffs(
        self,
        baseline: Dict[str, str],
        revised: Dict[str, str]
    ) -> List[RevisionDiff]:
        """计算修订差异"""
        diffs = []
        impact_tree = self._calculate_impact_tree()

        for wave, dims in impact_tree.items():
            for dim in dims:
                old_content = baseline.get(dim, "")
                new_content = revised.get(dim, "")

                if not new_content:
                    continue

                # 计算关键词变化
                keywords = self.config.get("keywords", {})
                positive_kw = keywords.get("positive", [])
                negative_kw = keywords.get("negative", [])

                keywords_added = [kw for kw in positive_kw if kw in new_content and kw not in old_content]
                keywords_removed = [kw for kw in negative_kw if kw in old_content and kw not in new_content]

                # 获取维度元数据
                from app.config import get_dimension_config, get_dimension_layer
                dim_config = get_dimension_config(dim)
                layer = get_dimension_layer(dim)

                diffs.append(RevisionDiff(
                    dimension_key=dim,
                    dimension_name=dim_config.name if dim_config else dim,
                    layer=layer or 0,
                    wave=wave,
                    is_target=(dim == self.config["target_dimension"]),
                    old_content=old_content[:500] if old_content else "",
                    new_content=new_content[:500] if new_content else "",
                    content_length_diff=len(new_content) - len(old_content),
                    keywords_added=keywords_added,
                    keywords_removed=keywords_removed,
                ))

        return diffs

    def _check_consistency(self, diffs: List[RevisionDiff]) -> Dict[str, float]:
        """检验一致性"""
        scores = {}

        for diff in diffs:
            if diff.is_target:
                # 目标维度：检验反馈响应度
                score = self.checker.check_feedback_response(
                    diff.old_content,
                    diff.new_content,
                    self.config.get("feedback", ""),
                    self.config.get("keywords", {}),
                )
            else:
                # 下游维度：检验语义对齐
                target_diff = next((d for d in diffs if d.is_target), None)
                if target_diff:
                    score = self.checker.check_semantic_alignment(
                        target_diff.new_content,
                        diff.new_content,
                        diff.dimension_key,
                    )
                else:
                    score = 0.0

            scores[diff.dimension_key] = score

        return scores

    def save_results(self, result: ExperimentResult):
        """保存实验结果"""
        output_dir = get_output_dir(self.scenario_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 保存完整结果
        result_file = output_dir / "experiment_result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(asdict(result), f, indent=2, ensure_ascii=False)

        # 保存差异对比
        diffs_file = output_dir / "revision_diffs.json"
        with open(diffs_file, "w", encoding="utf-8") as f:
            json.dump([asdict(d) for d in result.revision_diffs], f, indent=2, ensure_ascii=False)

        # 保存一致性评分
        scores_file = output_dir / "consistency_scores.json"
        with open(scores_file, "w", encoding="utf-8") as f:
            json.dump(result.consistency_scores, f, indent=2, ensure_ascii=False)

        logger.info(f"[Experiment] Saved results to {output_dir}")


async def run_cascade_experiment(scenario_name: str) -> ExperimentResult:
    """运行级联一致性实验"""
    ensure_cascade_dirs()

    runner = CascadeExperimentRunner(scenario_name)
    result = await runner.run_experiment()
    runner.save_results(result)

    # 打印摘要
    print("\n" + "=" * 60)
    print(f"实验结果摘要: {scenario_name}")
    print("=" * 60)
    print(f"目标维度: {result.target_dimension}")
    print(f"影响范围: {len(result.impact_tree)} 波次, {sum(len(d) for d in result.impact_tree.values())} 维度")
    print(f"修订维度: {len(result.revision_diffs)}")
    print(f"总体一致性: {result.overall_consistency:.2%}")
    print("\n各维度一致性评分:")
    for dim, score in sorted(result.consistency_scores.items(), key=lambda x: -x[1]):
        print(f"  {dim}: {score:.2%}")
    print("=" * 60)

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run cascade consistency experiment")
    parser.add_argument("--scenario", required=True, choices=["scenario1", "scenario2"])
    args = parser.parse_args()

    asyncio.run(run_cascade_experiment(args.scenario))


if __name__ == "__main__":
    main()