"""
运行基线实验并保存报告到 docs

使用方法:
    python scripts/experiments/run_baseline_to_docs.py

输出:
    - docs/layer1_法规式报告.md
    - docs/layer2_法规式报告.md
    - docs/layer3_法规式报告.md
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.experiments.config import (
    BASELINE_DIR,
    JINTIAN_VILLAGE_DATA,
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    ensure_output_dirs,
)
from scripts.experiments.run_baseline import run_baseline

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


DOCS_DIR = Path(__file__).parent.parent.parent / "docs"


def save_reports_to_docs(state: dict):
    """
    Save layer reports to docs directory.

    Args:
        state: Session state with reports
    """
    session_id = state.get("session_id", "unknown")
    reports = state.get("reports", {})

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for layer in [1, 2, 3]:
        layer_key = f"layer{layer}"
        layer_reports = reports.get(layer_key, {})

        if not layer_reports:
            logger.warning(f"No reports for {layer_key}")
            continue

        # Combine all dimension reports into one file
        combined_content = []

        # Add chapter header
        village_name = state.get("project_name", "金田村")
        chapter_titles = {
            1: f"第一章 {village_name} 村庄现状",
            2: f"第二章 {village_name} 规划思路",
            3: f"第三章 {village_name} 规划细化",
        }

        combined_content.append(chapter_titles[layer])
        combined_content.append("")

        # Add each dimension report
        for dim_key, dim_content in layer_reports.items():
            if dim_content:
                combined_content.append(dim_content)
                combined_content.append("")

        # Save to docs
        output_file = DOCS_DIR / f"layer{layer}_法规式报告_{timestamp}.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(combined_content))

        logger.info(f"Saved {output_file}: {len(combined_content)} lines")

    # Save metadata
    meta_file = DOCS_DIR / f"baseline_meta_{timestamp}.json"
    meta = {
        "session_id": session_id,
        "timestamp": timestamp,
        "task_description": DEFAULT_TASK_DESCRIPTION,
        "constraints": DEFAULT_CONSTRAINTS,
        "layers": list(reports.keys()),
        "generated_at": datetime.now().isoformat(),
    }
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved metadata: {meta_file}")


async def main():
    """Run baseline and save to docs."""
    ensure_output_dirs()

    logger.info("=" * 60)
    logger.info("[Baseline] Starting experiment with legal format")
    logger.info("=" * 60)
    logger.info(f"Task: {DEFAULT_TASK_DESCRIPTION}")
    logger.info(f"Constraints: {DEFAULT_CONSTRAINTS[:100]}...")

    try:
        # Run baseline experiment
        state = await run_baseline(
            timeout=1800,
            use_mock=False,
            capture_layer_checkpoints=True,
            use_sse=True,
        )

        # Save to docs
        save_reports_to_docs(state)

        logger.info("=" * 60)
        logger.info("[Baseline] Completed successfully")
        logger.info(f"Session ID: {state.get('session_id')}")
        logger.info("=" * 60)

        return state

    except Exception as e:
        logger.error(f"[Baseline] Failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())