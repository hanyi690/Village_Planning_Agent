"""
Export latest planning session to documents with RAG references.

导出数据库中最新的规划数据，包含三层分维度和RAG检索结果。

输出文件：
- docs/planning_export/layer1_现状分析.md
- docs/planning_export/layer2_规划思路.md
- docs/planning_export/layer3_详细规划.md
"""

import sqlite3
import msgpack
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

# 项目路径 - 使用绝对路径避免Windows路径问题
PROJECT_ROOT = Path("F:/project/Village_Planning_Agent").resolve()
DB_PATH = Path("F:/project/Village_Planning_Agent/data/database/village_planning.db").resolve()
OUTPUT_DIR = Path("F:/project/Village_Planning_Agent/docs/planning_export").resolve()

# 维度名称映射
LAYER_NAMES = {
    1: "现状分析",
    2: "规划思路",
    3: "详细规划",
}

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

# RAG查询关键词（从phases.yaml提取）
RAG_QUERIES = {
    # Layer 1
    "location": "区位 交通",
    "socio_economic": "人口 预测 经济",
    "villager_wishes": "村民 意愿 诉求",
    "superior_planning": "上位规划 政策",
    "natural_environment": "自然环境 地形",
    "land_use": "土地利用 标准",
    "traffic": "道路 交通",
    "public_services": "公共服务 设施",
    "infrastructure": "基础设施",
    "ecological_green": "生态 绿地",
    "architecture": "建筑",
    "historical_culture": "历史 文化 乡愁",
    # Layer 2
    "resource_endowment": "资源禀赋 分析",
    "planning_positioning": "规划定位",
    "development_goals": "发展目标",
    "planning_strategies": "规划策略",
    # Layer 3
    "industry": "产业规划 农村",
    "spatial_structure": "空间结构",
    "land_use_planning": "土地利用规划",
    "settlement_planning": "居民点",
    "traffic_planning": "道路交通规划",
    "public_service": "公共服务设施规划",
    "infrastructure_planning": "基础设施规划",
    "ecological": "生态绿地规划",
    "disaster_prevention": "防震减灾",
    "heritage": "历史文保",
    "landscape": "村庄风貌",
    "project_bank": "建设项目 项目库",
}


def get_latest_session() -> Optional[Dict[str, Any]]:
    """获取最新的规划会话"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT session_id, project_name, created_at, completed_at
        FROM planning_sessions
        ORDER BY created_at DESC
        LIMIT 1
    ''')
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "session_id": row["session_id"],
            "project_name": row["project_name"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }
    return None


def get_latest_checkpoint(session_id: str) -> Optional[Dict[str, Any]]:
    """获取会话的最新checkpoint"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute('''
        SELECT checkpoint_id, checkpoint
        FROM checkpoints
        WHERE thread_id = ?
        ORDER BY checkpoint_id DESC
        LIMIT 1
    ''', (session_id,))

    row = cursor.fetchone()
    conn.close()

    if row:
        try:
            data = msgpack.unpackb(row[1], raw=False)
            return {
                "checkpoint_id": row[0],
                "state": data.get("channel_values", {}),
            }
        except Exception as e:
            print(f"Error parsing checkpoint: {e}")
    return None


def search_knowledge(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """执行RAG检索"""
    try:
        # 添加项目路径到sys.path
        import sys
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        if str(PROJECT_ROOT / "backend") not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT / "backend"))

        from app.services.modules.rag.service import RagService
        from app.services.modules.rag.context import get_context_manager

        rag = RagService.get_instance()
        vectorstore = rag.vectorstore

        if vectorstore is None:
            print(f"[RAG] Vector store not available")
            return []

        # 使用同步的similarity_search
        results = vectorstore.similarity_search(query, k=top_k)

        formatted_results = []
        for doc in results:
            formatted_results.append({
                "source": doc.metadata.get("source", "未知来源"),
                "doc_type": doc.metadata.get("doc_type", doc.metadata.get("type", "法规")),
                "content": doc.page_content,
            })

        return formatted_results

    except Exception as e:
        print(f"[RAG] Search failed for '{query}': {e}")
        import traceback
        traceback.print_exc()
        return []


def format_dimension_report(
    dim_key: str,
    content: str,
    rag_results: List[Dict[str, Any]]
) -> str:
    """格式化单个维度的报告"""
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
        content,
        "",
    ]

    # 添加RAG检索结果（表格 + 引用块格式）
    if rag_results:
        lines.extend([
            "---",
            "",
            "### 参考依据",
            "",
            "| 序号 | 来源文件 | 文档类型 |",
            "|------|----------|----------|",
        ])
        for i, result in enumerate(rag_results, 1):
            source = result.get("source", "未知来源")
            doc_type = result.get("doc_type", "法规")
            lines.append(f"| {i} | {source} | {doc_type} |")

        lines.extend([
            "",
            "**参考内容摘要**:",
            "",
        ])
        for result in rag_results:
            source = result.get("source", "未知来源")
            result_content = result.get("content", "")
            lines.extend([
                f"> **{source}**",
                f"> {result_content[:200]}...",
                "",
            ])
    else:
        lines.extend([
            "---",
            "",
            "### 参考依据",
            "",
            "> 该维度未检索到相关参考文档。",
            "",
        ])

    return "\n".join(lines)


def export_layer_document(
    layer: int,
    reports: Dict[str, str],
    project_name: str,
    session_id: str,
    export_time: str
) -> None:
    """导出单个层级的文档"""
    layer_name = LAYER_NAMES.get(layer, f"Layer {layer}")
    filename = f"layer{layer}_{layer_name}.md"
    output_path = OUTPUT_DIR / filename

    # 文档头部
    lines = [
        f"# {layer_name}",
        "",
        f"**项目名称**: {project_name}",
        "",
        f"**会话ID**: `{session_id[:24]}...`",
        "",
        f"**导出时间**: {export_time}",
        "",
        "---",
        "",
    ]

    # 按顺序添加各维度
    dimension_order = list(DIMENSION_NAMES.keys())
    layer_start = {1: 0, 2: 12, 3: 16}.get(layer, 0)
    layer_end = {1: 12, 2: 16, 3: 28}.get(layer, len(dimension_order))
    layer_dimensions = dimension_order[layer_start:layer_end]

    for dim_key in layer_dimensions:
        if dim_key in reports:
            content = reports[dim_key]
            # 获取RAG检索结果（使用预定义的查询）
            rag_query = RAG_QUERIES.get(dim_key, "")
            rag_results = search_knowledge(rag_query) if rag_query else []

            dim_report = format_dimension_report(dim_key, content, rag_results)
            lines.append(dim_report)
            lines.append("")

    # 写入文件
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[Export] Saved: {output_path}")
    print(f"  - Dimensions: {len([d for d in layer_dimensions if d in reports])}")


def export_summary_document(
    project_name: str,
    session_id: str,
    export_time: str,
    reports: Dict[str, Dict[str, str]]
) -> None:
    """导出总览文档"""
    output_path = OUTPUT_DIR / "README.md"

    lines = [
        "# 村庄规划导出文档",
        "",
        f"**项目名称**: {project_name}",
        "",
        f"**会话ID**: `{session_id}`",
        "",
        f"**导出时间**: {export_time}",
        "",
        "---",
        "",
        "## 文档结构",
        "",
        "| 层级 | 文档名称 | 维度数量 |",
        "|------|----------|----------|",
    ]

    for layer in [1, 2, 3]:
        layer_name = LAYER_NAMES.get(layer, f"Layer {layer}")
        layer_reports = reports.get(f"layer{layer}", {})
        dim_count = len(layer_reports)
        filename = f"layer{layer}_{layer_name}.md"
        lines.append(f"| Layer {layer} | [{layer_name}]({filename}) | {dim_count} |")

    lines.extend([
        "",
        "---",
        "",
        "## 数据来源",
        "",
        "- **数据库**: `data/database/village_planning.db`",
        "- **Checkpoint表**: `checkpoints`",
        "- **导出脚本**: `scripts/export_planning_to_docs.py`",
        "",
        "---",
        "",
        "## 维度说明",
        "",
        "### Layer 1: 现状分析（12维度）",
        "",
    ])

    # Layer 1 维度列表
    for dim_key in list(DIMENSION_NAMES.keys())[:12]:
        dim_name = DIMENSION_NAMES[dim_key]
        lines.append(f"- `{dim_key}`: {dim_name}")

    lines.extend([
        "",
        "### Layer 2: 规划思路（4维度）",
        "",
    ])

    for dim_key in list(DIMENSION_NAMES.keys())[12:16]:
        dim_name = DIMENSION_NAMES[dim_key]
        lines.append(f"- `{dim_key}`: {dim_name}")

    lines.extend([
        "",
        "### Layer 3: 详细规划（12维度）",
        "",
    ])

    for dim_key in list(DIMENSION_NAMES.keys())[16:28]:
        dim_name = DIMENSION_NAMES[dim_key]
        lines.append(f"- `{dim_key}`: {dim_name}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[Export] Saved: {output_path}")


def main():
    """主函数"""
    print("=" * 60)
    print("[Export] Starting planning export")
    print("=" * 60)

    # 获取最新会话
    session = get_latest_session()
    if not session:
        print("[Export] No sessions found in database!")
        return

    session_id = session["session_id"]
    project_name = session["project_name"]
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[Export] Session: {session_id}")
    print(f"[Export] Project: {project_name}")
    print(f"[Export] Time: {export_time}")

    # 获取最新checkpoint
    checkpoint = get_latest_checkpoint(session_id)
    if not checkpoint:
        print("[Export] No checkpoint found!")
        return

    state = checkpoint["state"]
    reports = state.get("reports", {})

    print(f"[Export] Found reports:")
    for layer_key in ["layer1", "layer2", "layer3"]:
        layer_reports = reports.get(layer_key, {})
        print(f"  {layer_key}: {len(layer_reports)} dimensions")

    # 导出各层级文档
    for layer in [1, 2, 3]:
        layer_key = f"layer{layer}"
        layer_reports = reports.get(layer_key, {})
        if layer_reports:
            export_layer_document(
                layer=layer,
                reports=layer_reports,
                project_name=project_name,
                session_id=session_id,
                export_time=export_time
            )

    # 导出总览文档
    export_summary_document(
        project_name=project_name,
        session_id=session_id,
        export_time=export_time,
        reports=reports
    )

    print("=" * 60)
    print("[Export] Export completed successfully")
    print(f"[Export] Output directory: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
