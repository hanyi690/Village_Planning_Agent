"""
Baseline Runner - Generate baseline reports for cascade experiment
基线运行器 - 为级联实验生成基线报告

运行完整的规划流程，生成28维度报告作为实验基线。

Usage:
    python scripts/experiments/cascade_consistency/run_baseline.py
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend"))

from scripts.experiments.config import (
    BASELINE_DIR,
    JINTIAN_VILLAGE_DATA,
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    ensure_cascade_dirs,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


async def run_baseline() -> Dict[str, str]:
    """
    运行基线规划流程

    Returns:
        各维度报告内容 {dimension_key: content}
    """
    from app.services.runtime import PlanningRuntimeService
    from app.services.checkpoint import checkpoint_service
    from starlette.background import BackgroundTasks

    ensure_cascade_dirs()

    logger.info("[Baseline] Starting baseline planning flow")

    background_tasks = BackgroundTasks()

    result = await PlanningRuntimeService.start_session(
        project_name="金田村基线实验",
        village_data=JINTIAN_VILLAGE_DATA.get("status_report", ""),
        village_name=JINTIAN_VILLAGE_DATA.get("village_name", "金田村"),
        task_description=DEFAULT_TASK_DESCRIPTION,
        constraints=DEFAULT_CONSTRAINTS,
        step_mode=False,
        background_tasks=background_tasks,
    )

    session_id = result.get("task_id")
    logger.info(f"[Baseline] Session started: {session_id}")

    # 等待完成
    await background_tasks()

    # 获取最终状态
    state = await checkpoint_service.get_state(session_id, wait_for_write=True)

    # 提取各维度报告
    reports = {}
    if state:
        for layer_key in ["layer1", "layer2", "layer3"]:
            layer_reports = state.get("reports", {}).get(layer_key, {})
            reports.update(layer_reports)

    logger.info(f"[Baseline] Generated {len(reports)} dimension reports")

    # 保存基线
    save_baseline(reports, session_id)

    return reports


def save_baseline(reports: Dict[str, str], session_id: str):
    """保存基线报告"""
    baseline_file = BASELINE_DIR / "baseline_reports.json"
    baseline_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "session_id": session_id,
        "generated_at": datetime.now().isoformat(),
        "dimension_count": len(reports),
        "reports": reports,
    }

    with open(baseline_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"[Baseline] Saved to {baseline_file}")


def main():
    """CLI入口"""
    logger.info("=" * 60)
    logger.info("[Baseline] Running baseline experiment")
    logger.info("=" * 60)

    reports = asyncio.run(run_baseline())

    print("\n" + "=" * 60)
    print(f"基线报告生成完成: {len(reports)} 维度")
    print("=" * 60)

    # 打印各维度长度
    for dim, content in sorted(reports.items()):
        print(f"  {dim}: {len(content)} 字符")


if __name__ == "__main__":
    main()