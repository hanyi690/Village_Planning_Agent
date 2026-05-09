"""
切片可视化检查 CLI 工具

迁移来源：src/rag/visualize/inspector.py

用于检查知识文件被切片后的具体内容，
发现冗余和垃圾信息，优化切片策略。

Usage:
    python scripts/inspect_slices.py --input knowledge_base/chroma --limit 20
    python scripts/inspect_slices.py --export slices_report.json
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.documents import Document
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rPrint

from backend.app.core.settings import CHROMA_PERSIST_DIR
from backend.app.utils.logger import get_logger

logger = get_logger(__name__)
console = Console()


class SliceInspector:
    """切片检查器"""

    def __init__(self, documents: list[Document]):
        self.documents = documents
        self.stats = self._calculate_stats()

    def _calculate_stats(self) -> dict:
        """计算切片统计信息"""
        total_chunks = len(self.documents)
        total_chars = sum(len(doc.page_content) for doc in self.documents)
        avg_chars = total_chars / total_chunks if total_chunks > 0 else 0

        sources = {}
        types = {}
        for doc in self.documents:
            source = doc.metadata.get("source", "unknown")
            doc_type = doc.metadata.get("type", "unknown")
            sources[source] = sources.get(source, 0) + 1
            types[doc_type] = types.get(doc_type, 0) + 1

        return {
            "total_chunks": total_chunks,
            "total_chars": total_chars,
            "avg_chars": avg_chars,
            "sources": sources,
            "types": types,
        }

    def print_summary(self) -> None:
        """打印统计摘要"""
        console.print("\n[bold cyan]📊 切片统计摘要[/bold cyan]\n")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("指标", style="cyan")
        table.add_column("数值", justify="right")
        table.add_column("说明", style="dim")

        table.add_row("总切片数", f"{self.stats['total_chunks']:,}", "文档被切分成的片段总数")
        table.add_row("总字符数", f"{self.stats['total_chars']:,}", "所有切片的字符总数")
        table.add_row("平均字符数", f"{self.stats['avg_chars']:.0f}", "每个切片的平均字符数")

        console.print(table)

        if self.stats['sources']:
            console.print("\n[bold yellow]📁 按文档来源分布:[/bold yellow]")
            for source, count in sorted(self.stats['sources'].items(), key=lambda x: x[1], reverse=True):
                console.print(f"  • {source}: {count} 个切片")

        if self.stats['types']:
            console.print("\n[bold green]📋 按文档类型分布:[/bold green]")
            for doc_type, count in sorted(self.stats['types'].items(), key=lambda x: x[1], reverse=True):
                console.print(f"  • {doc_type}: {count} 个切片")

    def print_slice_details(self, start_idx: int = 0, end_idx: int = None, show_content: bool = True) -> None:
        """打印切片详细信息"""
        if end_idx is None:
            end_idx = min(start_idx + 5, len(self.documents))

        console.print(f"\n[bold cyan]📄 切片详情 (索引 {start_idx}-{end_idx-1})[/bold cyan]\n")

        for idx in range(start_idx, min(end_idx, len(self.documents))):
            doc = self.documents[idx]
            console.print(f"[bold yellow]切片 #{idx}[/bold yellow]")

            meta_table = Table(show_header=False, box=None, padding=0)
            meta_table.add_column("Key", style="cyan")
            meta_table.add_column("Value", style="green")

            for key, value in doc.metadata.items():
                meta_table.add_row(f"  {key}:", str(value))

            console.print(meta_table)
            console.print(f"  [dim]字符数: {len(doc.page_content)}[/dim]")

            if show_content:
                preview = doc.page_content if len(doc.page_content) <= 500 else doc.page_content[:500] + "..."
                console.print(Panel(preview, title="[bold]内容预览[/bold]", border_style="blue", expand=False))

            console.print()

    def find_potential_issues(self) -> list[dict]:
        """查找潜在的切片问题"""
        issues = []

        for idx, doc in enumerate(self.documents):
            content = doc.page_content

            if len(content.strip()) < 50:
                issues.append({
                    "type": "过短切片",
                    "index": idx,
                    "description": f"切片内容过短（{len(content)} 字符）",
                    "content": content,
                })

            words = content.split()
            if len(words) > 10:
                unique_ratio = len(set(words)) / len(words)
                if unique_ratio < 0.3:
                    issues.append({
                        "type": "重复内容",
                        "index": idx,
                        "description": f"内容重复率过高（唯一率: {unique_ratio:.1%}）",
                        "content": content,
                    })

            special_char_ratio = sum(1 for c in content if not c.isalnum() and not c.isspace()) / max(len(content), 1)
            if special_char_ratio > 0.3:
                issues.append({
                    "type": "特殊字符过多",
                    "index": idx,
                    "description": f"特殊字符比例过高（{special_char_ratio:.1%}）",
                    "content": content,
                })

        return issues

    def print_issues(self, max_issues: int = 20) -> None:
        """打印发现的问题"""
        issues = self.find_potential_issues()

        if not issues:
            console.print("\n✅ [bold green]未发现明显问题！[/bold green]\n")
            return

        console.print(f"\n⚠️  [bold yellow]发现 {len(issues)} 个潜在问题[/bold yellow]\n")

        for issue in issues[:max_issues]:
            console.print(f"[bold red]问题 #{issue['index']}[/bold red]: {issue['type']}")
            console.print(f"  [dim]{issue['description']}[/dim]")
            console.print(f"  [cyan]内容:[/cyan] {issue['content'][:100]}...")
            console.print()

    def export_to_json(self, output_path: Path) -> None:
        """导出切片数据到 JSON 文件"""
        import json

        export_data = {
            "statistics": self.stats,
            "issues": self.find_potential_issues(),
            "slices": [
                {
                    "index": idx,
                    "metadata": doc.metadata,
                    "content": doc.page_content,
                    "char_count": len(doc.page_content),
                }
                for idx, doc in enumerate(self.documents)
            ],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        console.print(f"\n✅ [bold green]切片数据已导出到: {output_path}[/bold green]\n")


def load_slices_from_chroma(persist_dir: Path = None) -> list[Document]:
    """从 Chroma 加载切片数据"""
    from langchain_chroma import Chroma
    from backend.app.core.settings import CHROMA_COLLECTION_NAME

    persist_dir = persist_dir or CHROMA_PERSIST_DIR

    if not persist_dir.exists():
        console.print(f"[red]❌ 向量库不存在: {persist_dir}[/red]")
        return []

    try:
        from backend.app.services.rag_service import RagService
        rag_service = RagService.get_instance()
        vectorstore = rag_service.vectorstore
    except ImportError:
        vectorstore = Chroma(
            persist_directory=str(persist_dir),
            collection_name=CHROMA_COLLECTION_NAME,
        )

    collection = vectorstore._collection
    results = collection.get(include=["documents", "metadatas"])

    documents = []
    for idx, (doc_text, metadata) in enumerate(zip(results["documents"], results["metadatas"])):
        documents.append(Document(page_content=doc_text, metadata=metadata))

    console.print(f"[green]✅ 从 {persist_dir} 加载 {len(documents)} 个切片[/green]")
    return documents


def main(
    input_path: Path = None,
    limit: int = 10,
    show_content: bool = True,
    export_path: Path = None,
    show_issues: bool = True,
):
    """主函数"""
    print("=" * 60)
    print("🔍 切片可视化检查工具")
    print("=" * 60)

    documents = load_slices_from_chroma(input_path)

    if not documents:
        console.print("[red]❌ 没有切片数据可供分析[/red]")
        return

    inspector = SliceInspector(documents)
    inspector.print_summary()
    inspector.print_slice_details(start_idx=0, end_idx=min(limit, len(documents)), show_content=show_content)

    if show_issues:
        inspector.print_issues(max_issues=20)

    if export_path:
        inspector.export_to_json(export_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="切片可视化检查工具")
    parser.add_argument("--input", type=Path, default=None, help="向量库路径")
    parser.add_argument("--limit", type=int, default=10, help="显示切片数量")
    parser.add_argument("--no-content", action="store_true", help="不显示切片内容")
    parser.add_argument("--export", type=Path, default=None, help="导出报告到 JSON 文件")
    parser.add_argument("--no-issues", action="store_true", help="不显示问题分析")
    args = parser.parse_args()

    main(
        input_path=args.input,
        limit=args.limit,
        show_content=not args.no_content,
        export_path=args.export,
        show_issues=not args.no_issues,
    )