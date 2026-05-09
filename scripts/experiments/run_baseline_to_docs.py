"""
运行基线实验并保存报告到 docs（带 RAG 参考内容）

使用方法:
    python scripts/experiments/run_baseline_to_docs.py

输出:
    - docs/layer1_法规式报告_{timestamp}.md (含 RAG 参考)
    - docs/layer2_法规式报告_{timestamp}.md (含 RAG 参考)
    - docs/layer3_法规式报告_{timestamp}.md (含 RAG 参考)
    - docs/baseline_meta_{timestamp}.json

每个维度报告后嵌入 RAG 参考来源：
    - 参考文件名称、文档类型、相关度分数
    - 参考内容摘要（前 200 字）
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend" / "app"))

from scripts.experiments.config import (
    BASELINE_DIR,
    JINTIAN_VILLAGE_DATA,
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    ensure_output_dirs,
)
from scripts.experiments.run_baseline import run_baseline
from backend.app.config.loader import get_dimension_config

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


DOCS_DIR = Path(__file__).parent.parent.parent / "docs"


async def get_rag_references(rag_query: str, top_k: int = 3) -> list:
    """
    检索 RAG 参考文档.

    Args:
        rag_query: 搜索查询 (如 "区位 交通")
        top_k: 返回数量

    Returns:
        List of {content, metadata, score}
    """
    from backend.app.services.modules.rag.service import RagService
    rag_service = RagService.get_instance()
    results = await rag_service.search(rag_query, top_k=top_k)
    return results


def format_rag_section(rag_refs: list) -> str:
    """
    格式化 RAG 参考内容为 Markdown.

    Args:
        rag_refs: RAG 检索结果

    Returns:
        Markdown 格式的 RAG 参考部分
    """
    if not rag_refs:
        return "\n#### RAG 参考来源\n\n无相关法规或技术标准。\n"

    section = "\n#### RAG 参考来源\n\n"
    section += "| 序号 | 来源文件 | 文档类型 | 相关度 |\n"
    section += "|------|----------|----------|--------|\n"

    for i, ref in enumerate(rag_refs, 1):
        source = ref.get("metadata", {}).get("source", "未知")
        doc_type = ref.get("metadata", {}).get("doc_type", "法规")
        score = ref.get("score", 0)
        section += f"| {i} | {source} | {doc_type} | {score:.2f} |\n"

    section += "\n**参考内容摘要**:\n\n"
    for ref in rag_refs:
        source = ref.get("metadata", {}).get("source", "未知")
        content = ref.get("content", "")[:200]
        section += f"> **{source}**\n"
        section += f"> {content}...\n\n"

    return section


async def save_reports_to_docs(state: dict):
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

        # Add each dimension report with RAG references
        for dim_key, dim_content in layer_reports.items():
            if dim_content:
                combined_content.append(dim_content)
                combined_content.append("")

                # Add RAG references for this dimension
                cfg = get_dimension_config(dim_key)
                if cfg and cfg.rag_query:
                    rag_refs = await get_rag_references(cfg.rag_query)
                    combined_content.append(format_rag_section(rag_refs))
                    combined_content.append("---\n")

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

        # Save to docs with RAG references
        await save_reports_to_docs(state)

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