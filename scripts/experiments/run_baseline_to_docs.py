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

# 维度名称映射
DIMENSION_NAMES = {
    # Layer 1: 现状分析
    "location": "区位与对外交通分析",
    "socio_economic": "社会经济分析",
    "villager_wishes": "村民意愿与诉求分析",
    "superior_planning": "上位规划与政策导向分析",
    "natural_environment": "自然环境分析",
    "land_use": "土地利用分析",
    "traffic": "道路交通分析",
    "public_services": "公共服务设施分析",
    "infrastructure": "基础设施分析",
    "ecological_green": "生态绿地分析",
    "architecture": "建筑分析",
    "historical_culture": "历史文化与乡愁保护分析",
    # Layer 2: 规划思路
    "resource_endowment": "资源禀赋分析",
    "planning_positioning": "规划定位分析",
    "development_goals": "发展目标分析",
    "planning_strategies": "规划策略分析",
    # Layer 3: 详细规划
    "industry": "产业规划",
    "spatial_structure": "空间结构规划",
    "land_use_planning": "土地利用规划",
    "settlement_planning": "居民点规划",
    "traffic_planning": "道路交通规划",
    "public_service": "公共服务设施规划",
    "infrastructure_planning": "基础设施规划",
    "ecological": "生态绿地规划",
    "disaster_prevention": "防震减灾规划",
    "heritage": "历史文保规划",
    "landscape": "村庄风貌指引",
    "project_bank": "建设项目库",
}

LAYER_NAMES = {
    1: "现状分析",
    2: "规划思路",
    3: "详细规划",
}


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
    格式化 RAG 参考内容为 Markdown（表格 + 引用块格式）.

    Args:
        rag_refs: RAG 检索结果

    Returns:
        Markdown 格式的 RAG 参考部分
    """
    if not rag_refs:
        return "\n### 参考依据\n\n> 该维度未检索到相关参考文档。\n"

    section = "\n### 参考依据\n\n"
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


def format_dimension_report(dim_key: str, dim_content: str) -> str:
    """
    格式化单个维度的报告（参考 docs/planning_export 格式）.

    Args:
        dim_key: 维度标识
        dim_content: 维度内容

    Returns:
        Markdown 格式的维度报告
    """
    dim_name = DIMENSION_NAMES.get(dim_key, dim_key)

    lines = [
        f"## {dim_name}",
        "",
        f"**维度标识**: `{dim_key}`",
        "",
        "---",
        "",
        "### 规划内容",
        "",
        dim_content,
        "",
    ]

    return "\n".join(lines)


async def save_reports_to_docs(state: dict):
    """
    Save layer reports to docs directory.

    Args:
        state: Session state with reports
    """
    session_id = state.get("session_id", "unknown")
    reports = state.get("reports", {})

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    village_name = state.get("project_name", "金田村")

    for layer in [1, 2, 3]:
        layer_key = f"layer{layer}"
        layer_reports = reports.get(layer_key, {})

        if not layer_reports:
            logger.warning(f"No reports for {layer_key}")
            continue

        # Combine all dimension reports into one file
        combined_content = []

        # Add document header (参考 docs/planning_export 格式)
        layer_name = LAYER_NAMES.get(layer, f"Layer {layer}")
        combined_content.extend([
            f"# {layer_name}",
            "",
            f"**项目名称**: {village_name}",
            "",
            f"**会话ID**: `{session_id[:24]}...`",
            "",
            f"**导出时间**: {export_time}",
            "",
            "---",
            "",
        ])

        # Add each dimension report with RAG references
        for dim_key, dim_content in layer_reports.items():
            if dim_content:
                # 格式化维度报告（参考 docs/planning_export 格式）
                combined_content.append(format_dimension_report(dim_key, dim_content))

                # Add RAG references for this dimension
                cfg = get_dimension_config(dim_key)
                if cfg and cfg.rag_query:
                    rag_refs = await get_rag_references(cfg.rag_query)
                    combined_content.append(format_rag_section(rag_refs))
                else:
                    combined_content.append("\n### 参考依据\n\n> 该维度未检索到相关参考文档。\n")

                combined_content.append("---\n")

        # Save to docs/planning_export (与 export_planning_to_docs.py 一致)
        output_dir = DOCS_DIR / "planning_export"
        output_dir.mkdir(parents=True, exist_ok=True)
        layer_name = LAYER_NAMES.get(layer, f"Layer {layer}")
        output_file = output_dir / f"layer{layer}_{layer_name}.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(combined_content))

        logger.info(f"Saved {output_file}: {len(combined_content)} lines")

    # Save metadata to docs/planning_export
    meta_file = output_dir / f"baseline_meta_{timestamp}.json"
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