"""
Export L1, L2, L3 DOCX reports using ExportService.
使用导出服务导出分层 DOCX 报告。
"""

import asyncio
import sys
import os
from pathlib import Path

# Setup paths - 必须在 import 之前
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent  # Village_Planning_Agent/
backend_root = project_root / "backend"

# 切换工作目录到 backend
os.chdir(str(backend_root))
sys.path.insert(0, str(backend_root))

from app.services.modules.planning_text.export_service import (
    ExportService,
    ExportFormat,
    ExportLayer,
)


async def export_layer_docx(session_id: str, output_dir: str):
    """Export L1, L2, L3 and planning text as DOCX."""
    service = ExportService(session_id, output_dir)

    # Export each layer as DOCX + planning text
    # include_rag_details=True to inject legal basis from RAG knowledge
    result = await service.export(
        formats=[ExportFormat.DOCX, ExportFormat.PLANNING_TEXT],
        layers=[ExportLayer.L1, ExportLayer.L2, ExportLayer.L3],
        include_rag_details=True,
        include_summaries=False,
    )

    print(f"\n导出完成: {result.project_name}")
    print(f"会话 ID: {result.session_id}")
    print(f"生成时间: {result.generated_at}")
    print(f"\n导出文件:")
    for f in result.files:
        size_kb = f.size_bytes / 1024 if f.size_bytes else 0
        if f.format == ExportFormat.PLANNING_TEXT:
            print(f"  [规划文本] {f.filename} ({size_kb:.1f} KB)")
        else:
            layer_name = {1: "L1-现状分析", 2: "L2-规划思路", 3: "L3-详细规划"}.get(f.layer, f"Layer{f.layer}")
            print(f"  [{layer_name}] {f.filename} ({size_kb:.1f} KB)")

    if result.errors:
        print(f"\n错误:")
        for e in result.errors:
            print(f"  - {e}")

    return result


if __name__ == "__main__":
    # 使用最新的基线实验会话
    session_id = "baseline_0db636bc"
    output_dir = "output/export"  # 统一到项目根目录

    asyncio.run(export_layer_docx(session_id, output_dir))
