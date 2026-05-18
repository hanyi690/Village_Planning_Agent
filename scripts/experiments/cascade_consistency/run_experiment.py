"""
Cascade Consistency Experiment
级联一致性实验

实验目标：
验证驳回操作后，下游维度的修订是否保持语义一致性。

实验设计：
1. 基线运行：生成完整的28维度规划报告
2. 驳回操作：对目标维度提交反馈
3. 级联修订：观察下游维度的自动修订
4. 一致性检验：对比修订前后，检验语义一致性

参考 run_4group_experiment.py 的进程内直接执行 + SSE 事件驱动 + 缓存模式。

Usage:
    python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario1
    python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario2 --no-cache
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

script_dir = Path(__file__).parent.resolve()
project_root = script_dir.parent.parent.parent.resolve()
backend_root = (project_root / "backend").resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

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

# 报告缓存目录
CACHE_DIR = CASCADE_DIR / "cached_reports"


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
    consistency_scores: Dict[str, ConsistencyResult]
    overall_consistency: float
    from_cache: bool = False
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class CascadeExperimentRunner:
    """级联一致性实验运行器"""

    def __init__(self, scenario_name: str, use_cache: bool = True, run_number: int = 0):
        self.scenario_name = scenario_name
        self.config = get_scenario_config(scenario_name)
        self.checker = ConsistencyChecker()
        self.use_cache = use_cache
        self.run_number = run_number
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def run_experiment(self) -> ExperimentResult:
        """运行完整实验"""
        logger.info(f"[Experiment] Starting {self.scenario_name}: {self.config['name']}")

        # 1. 计算影响树
        impact_tree = self._calculate_impact_tree()
        logger.info(f"[Experiment] Impact tree: {len(impact_tree)} waves")

        # 2. 获取基线报告
        baseline_reports = await self._get_baseline_reports()
        if not baseline_reports:
            logger.error("[Experiment] No baseline reports, aborting")
            return ExperimentResult(
                scenario_name=self.scenario_name, session_id="",
                target_dimension=self.config["target_dimension"],
                impact_tree=impact_tree, revision_diffs=[],
                consistency_scores={}, overall_consistency=0.0,
            )

        # 3. 检查缓存
        from_cache = False
        revision_reports = {}
        if self.use_cache:
            revision_reports = self._load_cached_revision()
            from_cache = bool(revision_reports)

        # 4. 执行修订（无缓存或缓存未命中）
        if not revision_reports:
            revision_reports = await self._execute_revision()
            if revision_reports:
                self._save_cached_revision(revision_reports)

        # 5. 计算修订差异
        revision_diffs = self._calculate_diffs(baseline_reports, revision_reports)

        # 6. 检验一致性
        consistency_scores = self._check_consistency(revision_diffs)

        # 7. 计算总体一致性
        overall = sum(s.score for s in consistency_scores.values()) / len(consistency_scores) if consistency_scores else 0.0

        return ExperimentResult(
            scenario_name=self.scenario_name,
            session_id=self.scenario_name,
            target_dimension=self.config["target_dimension"],
            impact_tree=impact_tree,
            revision_diffs=revision_diffs,
            consistency_scores=consistency_scores,
            overall_consistency=overall,
            from_cache=from_cache,
        )

    def _get_cache_path(self) -> Path:
        return CACHE_DIR / f"{self.scenario_name}_run{self.run_number}_revision_reports.json"

    def _load_cached_revision(self) -> Dict[str, str]:
        cache_path = self._get_cache_path()
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(f"[Experiment] Run {self.run_number}: loaded cached revision from {cache_path}")
                return data.get("reports", {})
            except Exception as e:
                logger.warning(f"[Experiment] Failed to load cache: {e}")
        return {}

    def _save_cached_revision(self, reports: Dict[str, str]):
        cache_path = self._get_cache_path()
        data = {
            "scenario": self.scenario_name,
            "run": self.run_number,
            "target_dimension": self.config["target_dimension"],
            "impact_tree": self._calculate_impact_tree(),
            "reports": reports,
            "cached_at": datetime.now().isoformat(),
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"[Experiment] Run {self.run_number}: saved revision cache to {cache_path}")

    def _calculate_impact_tree(self) -> Dict[int, List[str]]:
        from app.config.dependency import get_impact_tree_compat

        target_dim = self.config["target_dimension"]
        tree = get_impact_tree_compat(target_dim)

        full_tree = {0: [target_dim]}
        for wave, dims in tree.items():
            full_tree[wave] = dims

        return full_tree

    async def _get_baseline_reports(self) -> Dict[str, str]:
        baseline_file = BASELINE_DIR / "baseline_reports.json"
        if baseline_file.exists():
            with open(baseline_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            reports = data.get("reports", data)
            logger.info(f"[Experiment] Loaded baseline: {len(reports)} dimensions")
            return reports

        logger.warning("[Experiment] No baseline found, run run_baseline.py first")
        return {}

    async def _execute_revision(self) -> Dict[str, str]:
        """从基线最终检查点分叉（fork），注入修订触发器，执行级联修订

        不复用 session_id 新建会话——基线已生成 28 维度完整报告。
        从基线最终检查点分叉，跳过重复生成，直接触发级联。
        """
        from app.services.runtime import PlanningRuntimeService
        from app.services.sse import sse_manager
        from app.services.report_store import ReportStore
        from scripts.experiments.sse_listener import InProcessEventListener
        from langchain_core.messages import AIMessage

        target_dim = self.config["target_dimension"]
        feedback = self.config["feedback"]

        await PlanningRuntimeService.ensure_initialized()

        # 1. 获取基线 session_id 和最终检查点
        baseline_file = BASELINE_DIR / "baseline_reports.json"
        with open(baseline_file, "r", encoding="utf-8") as f:
            baseline_data = json.load(f)
        baseline_session_id = baseline_data["session_id"]
        baseline_checkpoint_id = baseline_data.get("checkpoint_id", "")

        # 使用精确 checkpoint_id 避免读到修订后的最新 checkpoint
        if baseline_checkpoint_id:
            config = PlanningRuntimeService.get_thread_config(baseline_session_id, baseline_checkpoint_id)
            graph = PlanningRuntimeService.get_graph()
            baseline = await graph.aget_state(config)
        else:
            baseline = await PlanningRuntimeService.aget_state(baseline_session_id)

        if not baseline or not baseline.values:
            raise RuntimeError("Baseline checkpoint state not found")

        fork_cfg = baseline.config  # {thread_id, checkpoint_id}
        fork_cfg.setdefault("configurable", {})["checkpoint_ns"] = ""
        logger.info(
            f"[Experiment] Forking from baseline: session={baseline_session_id}, "
            f"checkpoint={fork_cfg['configurable'].get('checkpoint_id', '?')}"
        )

        # 2. Fork: 注入修订触发器
        graph = PlanningRuntimeService.get_graph()
        fork_cfg = await graph.aupdate_state(fork_cfg, {
            "need_revision": True,
            "revision_target_dimensions": [target_dim],
            "human_feedback": feedback,
            "revision_feedback": feedback,
            "is_revision": True,
        }, as_node="conversation")

        # 3. Fork: 注入合成 AIMessage 触发 after_conversation 路由
        msg = AIMessage(content="", tool_calls=[{
            "name": "AdvancePlanningIntent",
            "id": f"call_{baseline_session_id[:8]}",
            "args": {},
        }])
        fork_cfg = await graph.aupdate_state(
            fork_cfg, {"messages": [msg]}, as_node="conversation"
        )

        # 4. SSE 监听器（复用基线 session_id）
        sse_manager.init_session(baseline_session_id, {
            "session_id": baseline_session_id,
            "project_name": f"金田村级联实验_{self.scenario_name}",
        })
        sse_manager.set_execution_active(baseline_session_id, True)

        listener = InProcessEventListener(baseline_session_id)
        await listener.connect()

        # 5. 从 fork 执行级联修订
        task = asyncio.create_task(self._consume_fork_stream(
            baseline_session_id, fork_cfg, listener
        ))

        try:
            # 等待修订完成 — checkpoint_saved 事件带 is_revision=True
            await listener.wait_for_any_event(
                event_types=["checkpoint_saved", "error"],
                timeout=900,
                filter_func=lambda e: (
                    e.get("type") == "error"
                    or e.get("data", {}).get("is_revision") == True
                ),
            )
            logger.info("[Experiment] Revision checkpoint_saved received")
        except asyncio.TimeoutError as e:
            logger.error(f"[Experiment] Timeout waiting for revision: {e}")
        except Exception as e:
            logger.error(f"[Experiment] Error: {e}")

        await task
        await listener.disconnect()

        # 6. 从 ReportStore 获取修订后报告
        store = ReportStore.get_instance()
        reports = {}
        for layer in [1, 2, 3]:
            layer_reports = await store.get_layer_reports(baseline_session_id, layer)
            reports.update(layer_reports)

        logger.info(f"[Experiment] Retrieved {len(reports)} revised reports")
        return reports

    async def _consume_fork_stream(self, session_id: str, fork_cfg: dict, listener):
        """消费 fork 执行流，推送 SSE 事件到 listener"""
        from app.services.runtime import PlanningRuntimeService

        graph = PlanningRuntimeService.get_graph()
        try:
            async for event in graph.astream(
                None, fork_cfg, stream_mode=['values', 'checkpoints']
            ):
                if isinstance(event, tuple) and len(event) == 2:
                    mode, data = event
                    if mode == 'checkpoints':
                        checkpoint_id = None
                        if hasattr(data, 'config'):
                            checkpoint_id = data.config.get('configurable', {}).get('checkpoint_id', '')
                        elif isinstance(data, dict):
                            checkpoint_id = data.get('config', {}).get('configurable', {}).get('checkpoint_id', '')

                        from app.services.sse import sse_manager as sse_mgr
                        from app.utils.event_factory import create_checkpoint_saved_event

                        if checkpoint_id:
                            checkpoint_event = create_checkpoint_saved_event(
                                checkpoint_id=checkpoint_id,
                                layer=0,
                                phase="",
                                session_id=session_id,
                                is_revision=True,
                            )
                            sse_mgr.append_event(session_id, checkpoint_event)
                            sse_mgr.publish_sync(session_id, checkpoint_event)
        except Exception as e:
            logger.error(f"[Experiment] Fork stream error: {e}")
            from app.services.sse import sse_manager as sse_mgr
            sse_mgr.append_event(session_id, {"type": "error", "data": {"message": str(e)}})

    def _calculate_diffs(
        self,
        baseline: Dict[str, str],
        revised: Dict[str, str]
    ) -> List[RevisionDiff]:
        diffs = []
        impact_tree = self._calculate_impact_tree()

        for wave, dims in impact_tree.items():
            for dim in dims:
                old_content = baseline.get(dim, "")
                new_content = revised.get(dim, "")

                if not new_content:
                    continue

                keywords = self.config.get("keywords", {})
                positive_kw = keywords.get("positive", [])
                negative_kw = keywords.get("negative", [])

                keywords_added = [kw for kw in positive_kw if kw in new_content and kw not in old_content]
                keywords_removed = [kw for kw in negative_kw if kw in old_content and kw not in new_content]

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

    def _check_consistency(self, diffs: List[RevisionDiff]) -> Dict[str, ConsistencyResult]:
        scores = {}

        for diff in diffs:
            if diff.is_target:
                fb_score = self.checker.check_feedback_response(
                    diff.old_content, diff.new_content,
                    self.config.get("feedback", ""),
                    self.config.get("keywords", {}),
                )
                result = ConsistencyResult(
                    dimension_key=diff.dimension_key,
                    score=fb_score,
                )
            else:
                target_diff = next((d for d in diffs if d.is_target), None)
                if target_diff:
                    result = self.checker.check_semantic_alignment(
                        target_diff.new_content,
                        diff.new_content,
                        diff.dimension_key,
                    )
                else:
                    result = ConsistencyResult(dimension_key=diff.dimension_key, score=0.0)

            scores[diff.dimension_key] = result

        return scores

    def save_results(self, result: ExperimentResult):
        output_dir = get_output_dir(self.scenario_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        run_tag = f"_run{self.run_number}" if self.run_number > 0 else ""
        result_file = output_dir / f"experiment_result{run_tag}.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(asdict(result), f, indent=2, ensure_ascii=False)

        scores_file = output_dir / f"consistency_scores{run_tag}.json"
        with open(scores_file, "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in result.consistency_scores.items()}, f, indent=2, ensure_ascii=False)

        logger.info(f"[Experiment] Run {self.run_number}: saved results to {output_dir}")


async def run_cascade_experiment(
    scenario_name: str, use_cache: bool = True, runs: int = 1
) -> List[ExperimentResult]:
    ensure_cascade_dirs()

    results = []
    overall_scores = []

    for run_num in range(runs):
        runner = CascadeExperimentRunner(scenario_name, use_cache=use_cache, run_number=run_num + 1)
        result = await runner.run_experiment()
        runner.save_results(result)
        results.append(result)
        overall_scores.append(result.overall_consistency)

    # 打印汇总
    print("\n" + "=" * 60)
    print(f"实验结果摘要: {scenario_name}" + (f" ({runs} 轮)" if runs > 1 else ""))
    print("=" * 60)
    if results:
        r = results[0]
        print(f"目标维度: {r.target_dimension}")
        print(f"影响范围: {len(r.impact_tree)} 波次, {sum(len(d) for d in r.impact_tree.values())} 维度")
        print(f"修订维度: {len(r.revision_diffs)}")

    if runs > 1:
        import numpy as np
        mean_score = float(np.mean(overall_scores))
        std_score = float(np.std(overall_scores, ddof=1))
        print(f"\n各轮一致性: {[f'{s:.2%}' for s in overall_scores]}")
        print(f"均值: {mean_score:.2%} ± {std_score:.2%}")
        # 聚合各维度评分
        all_dim_scores: Dict[str, list] = {}
        for result in results:
            for dim, cs in result.consistency_scores.items():
                all_dim_scores.setdefault(dim, []).append(cs.score)
        print("\n各维度聚合评分:")
        for dim in sorted(all_dim_scores):
            scores = all_dim_scores[dim]
            print(f"  {dim}: {np.mean(scores):.2%} ± {np.std(scores, ddof=1):.2%}")
    else:
        r = results[0]
        print(f"来自缓存: {r.from_cache}")
        print(f"总体一致性: {r.overall_consistency:.2%}")
        print("\n各维度一致性评分:")
        for dim, cs in sorted(r.consistency_scores.items(), key=lambda x: -x[1].score):
            print(f"  {dim}: {cs.score:.2%}")

    print("=" * 60)
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run cascade consistency experiment")
    parser.add_argument("--scenario", required=True, choices=["scenario1", "scenario2"])
    parser.add_argument("--runs", type=int, default=1, help="Number of runs (default: 1)")
    parser.add_argument("--no-cache", action="store_true", help="Disable cached reports, regenerate all")
    args = parser.parse_args()

    asyncio.run(run_cascade_experiment(
        args.scenario, use_cache=not args.no_cache, runs=args.runs
    ))


if __name__ == "__main__":
    main()
