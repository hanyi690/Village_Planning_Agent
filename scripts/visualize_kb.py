"""
知识库可视化脚本

功能:
1. 概览模式 (--overview): 显示总切片数、类别分布、来源统计
2. 切片浏览模式 (--browse): 分页显示切片列表
3. 切片详情模式 (--detail): 显示完整切片内容
4. 检索测试模式 (--search): 语义相似度检索
5. 交互模式 (--interactive): 提供菜单选择

使用方法:
    python scripts/visualize_kb.py --overview
    python scripts/visualize_kb.py --browse --category policies
    python scripts/visualize_kb.py --detail <chunk_id>
    python scripts/visualize_kb.py --search "村庄交通规划"
    python scripts/visualize_kb.py --interactive
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from collections import Counter

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich import print as rprint

# 导入 RAG 配置
from src.rag.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    DATA_DIR,
)


console = Console()


def get_chroma_collection():
    """获取 ChromaDB collection"""
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    collection = client.get_collection(name=CHROMA_COLLECTION_NAME)
    return collection


def get_all_chunks(collection) -> Dict[str, Any]:
    """获取所有切片数据"""
    results = collection.get(include=["documents", "metadatas", "embeddings"])
    return results


def show_overview():
    """显示知识库概览"""
    try:
        collection = get_chroma_collection()
        results = get_all_chunks(collection)

        if not results or not results.get("ids"):
            console.print("\n[yellow]知识库为空[/yellow]\n")
            return

        total_chunks = len(results["ids"])
        total_chars = sum(len(doc) for doc in results.get("documents", []))
        avg_chars = total_chars / total_chunks if total_chunks > 0 else 0

        # 统计类别分布
        categories = Counter()
        sources = Counter()
        doc_types = Counter()
        dimension_tags = Counter()
        terrains = Counter()

        for metadata in results.get("metadatas", []):
            categories[metadata.get("category", "unknown")] += 1
            sources[metadata.get("source", "unknown")] += 1
            doc_types[metadata.get("document_type", metadata.get("type", "unknown"))] += 1

            # 维度标签 (逗号分隔字符串)
            dim_str = metadata.get("dimension_tags", "")
            if dim_str:
                for tag in dim_str.split(","):
                    if tag:
                        dimension_tags[tag] += 1

            # 地形
            terrain = metadata.get("terrain")
            if terrain:
                terrains[terrain] += 1

        # 打印标题
        console.print("\n[bold cyan]===== 知识库概览 =====[/bold cyan]\n")

        # 基本统计表格
        basic_table = Table(show_header=True, header_style="bold magenta")
        basic_table.add_column("指标", style="cyan")
        basic_table.add_column("数值", justify="right")
        basic_table.add_column("说明", style="dim")

        basic_table.add_row("总切片数", f"{total_chunks:,}", "所有文档被切分的片段总数")
        basic_table.add_row("总字符数", f"{total_chars:,}", "所有切片的字符总数")
        basic_table.add_row("平均字符数", f"{avg_chars:.0f}", "每个切片的平均字符数")
        basic_table.add_row("来源文档数", f"{len(sources)}", "原始文档数量")

        console.print(basic_table)

        # 类别分布
        console.print("\n[bold yellow]按类别分布:[/bold yellow]")
        cat_table = Table(show_header=False, box=None)
        for cat, count in categories.most_common():
            pct = count / total_chunks * 100
            cat_table.add_row(f"  {cat}", f"{count} ({pct:.1f}%)")
        console.print(cat_table)

        # 来源文档分布
        console.print("\n[bold green]按来源文档分布 (前10个):[/bold green]")
        src_table = Table(show_header=True, header_style="bold")
        src_table.add_column("文档名称", style="cyan")
        src_table.add_column("切片数", justify="right")
        src_table.add_column("占比", justify="right")

        for source, count in sources.most_common(10):
            pct = count / total_chunks * 100
            src_table.add_row(source, str(count), f"{pct:.1f}%")

        console.print(src_table)

        # 文档类型分布
        if doc_types:
            console.print("\n[bold blue]按文档类型分布:[/bold blue]")
            type_table = Table(show_header=False, box=None)
            for dtype, count in doc_types.most_common():
                pct = count / total_chunks * 100
                type_table.add_row(f"  {dtype}", f"{count} ({pct:.1f}%)")
            console.print(type_table)

        # 维度标签分布
        if dimension_tags:
            console.print("\n[bold magenta]按维度标签分布:[/bold magenta]")
            dim_table = Table(show_header=False, box=None)
            for dim, count in dimension_tags.most_common(15):
                dim_table.add_row(f"  {dim}", str(count))
            console.print(dim_table)

        # 地形分布
        if terrains:
            console.print("\n[bold orange1]按地形分布:[/bold orange1]")
            terrain_table = Table(show_header=False, box=None)
            for terrain, count in terrains.most_common():
                terrain_table.add_row(f"  {terrain}", str(count))
            console.print(terrain_table)

        # 元数据字段统计
        console.print("\n[bold white]元数据字段统计:[/bold white]")
        all_fields = set()
        for metadata in results.get("metadatas", []):
            all_fields.update(metadata.keys())

        console.print(f"  可用字段: {sorted(all_fields)}")

        console.print(f"\n[dim]向量数据库路径: {CHROMA_PERSIST_DIR}[/dim]")
        console.print(f"[dim]Collection 名称: {CHROMA_COLLECTION_NAME}[/dim]")

    except Exception as e:
        console.print(f"\n[red]获取概览失败: {e}[/red]\n")


def show_browse(
    category: Optional[str] = None,
    source: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    """分页浏览切片列表"""
    try:
        collection = get_chroma_collection()

        # 构建过滤条件
        where_filter = None
        if category or source:
            conditions = []
            if category:
                conditions.append({"category": category})
            if source:
                conditions.append({"source": source})
            if len(conditions) == 1:
                where_filter = conditions[0]
            else:
                where_filter = {"$and": conditions}

        # 获取数据
        if where_filter:
            results = collection.get(
                where=where_filter,
                include=["documents", "metadatas"]
            )
        else:
            results = get_all_chunks(collection)

        if not results or not results.get("ids"):
            console.print("\n[yellow]没有找到切片[/yellow]\n")
            return

        total = len(results["ids"])
        total_pages = (total + page_size - 1) // page_size

        # 计算分页
        start_idx = (page - 1) * page_size
        end_idx = min(start_idx + page_size, total)

        # 显示切片列表
        console.print(f"\n[bold cyan]切片列表[/bold cyan]")

        if category:
            console.print(f"[dim]类别过滤: {category}[/dim]")
        if source:
            console.print(f"[dim]来源过滤: {source}[/dim]")

        console.print(f"[dim]第 {page}/{total_pages} 页，共 {total} 个切片[/dim]\n")

        # 创建表格
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("序号", justify="right", style="cyan")
        table.add_column("切片ID", style="green")
        table.add_column("来源", style="yellow")
        table.add_column("类别", style="blue")
        table.add_column("字符数", justify="right")
        table.add_column("预览", style="dim")

        for idx in range(start_idx, end_idx):
            chunk_id = results["ids"][idx]
            doc = results["documents"][idx] if results.get("documents") else ""
            metadata = results["metadatas"][idx] if results.get("metadatas") else {}

            source_name = metadata.get("source", "unknown")
            cat = metadata.get("category", "unknown")
            char_count = len(doc)
            preview = doc[:50] + "..." if len(doc) > 50 else doc

            table.add_row(
                str(idx + 1),
                chunk_id[:16] + "...",
                source_name[:30],
                cat,
                str(char_count),
                preview.replace("\n", " ")
            )

        console.print(table)

        # 分页提示
        if total_pages > 1:
            console.print(f"\n[dim]使用 --page {page+1} 查看下一页[/dim]")

    except Exception as e:
        console.print(f"\n[red]浏览失败: {e}[/red]\n")


def show_detail(chunk_id: str):
    """显示切片详情"""
    try:
        collection = get_chroma_collection()

        # 获取单个切片
        results = collection.get(
            ids=[chunk_id],
            include=["documents", "metadatas"]
        )

        if not results or not results.get("ids"):
            console.print(f"\n[yellow]未找到切片: {chunk_id}[/yellow]\n")
            return

        doc = results["documents"][0] if results.get("documents") else ""
        metadata = results["metadatas"][0] if results.get("metadatas") else {}

        console.print(f"\n[bold cyan]切片详情[/bold cyan]\n")
        console.print(f"[bold]ID:[/bold] {chunk_id}\n")

        # 元数据表格
        console.print("[bold yellow]元数据:[/bold yellow]")
        meta_table = Table(show_header=False, box=None)
        for key, value in sorted(metadata.items()):
            if isinstance(value, str) and len(value) > 50:
                value_display = value[:50] + "..."
            else:
                value_display = str(value)
            meta_table.add_row(f"  {key}", value_display)
        console.print(meta_table)

        # 内容显示
        console.print(f"\n[bold green]文本内容 ({len(doc)} 字符):[/bold green]")

        # 使用 Panel 显示内容
        console.print(Panel(
            doc,
            title="[bold]完整内容[/bold]",
            border_style="green",
            expand=False,
        ))

    except Exception as e:
        console.print(f"\n[red]获取详情失败: {e}[/red]\n")


def show_search(
    query: str,
    top_k: int = 5,
    dimension: Optional[str] = None,
    terrain: Optional[str] = None
):
    """检索测试"""
    try:
        from src.rag.core.cache import get_vector_cache

        cache = get_vector_cache()
        vectorstore = cache.get_vectorstore()

        # 构建过滤条件
        filter_dict = {}
        if dimension:
            # ChromaDB 存储维度标签为逗号分隔字符串，需要使用 $in 操作
            filter_dict["dimension_tags"] = {"$in": [dimension]}
        if terrain:
            filter_dict["terrain"] = {"$eq": terrain}

        console.print(f"\n[bold cyan]检索测试[/bold cyan]")
        console.print(f"[dim]查询: {query}[/dim]")
        console.print(f"[dim]top_k: {top_k}[/dim]")
        if dimension:
            console.print(f"[dim]维度过滤: {dimension}[/dim]")
        if terrain:
            console.print(f"[dim]地形过滤: {terrain}[/dim]\n")
        else:
            console.print()

        # 执行检索
        if filter_dict:
            results = vectorstore.similarity_search(
                query,
                k=top_k,
                filter=filter_dict
            )
        else:
            results = vectorstore.similarity_search(query, k=top_k)

        if not results:
            console.print("[yellow]没有找到相关结果[/yellow]\n")
            return

        console.print(f"[bold green]找到 {len(results)} 个相关结果[/bold green]\n")

        # 显示结果
        for idx, doc in enumerate(results, 1):
            source = doc.metadata.get("source", "unknown")
            category = doc.metadata.get("category", "unknown")
            dim_tags = doc.metadata.get("dimension_tags", "")
            terrain_tag = doc.metadata.get("terrain", "")

            console.print(f"[bold yellow]结果 {idx}[/bold yellow]")
            console.print(f"  来源: {source}")
            console.print(f"  类别: {category}")
            if dim_tags:
                console.print(f"  维度: {dim_tags}")
            if terrain_tag:
                console.print(f"  地形: {terrain_tag}")
            console.print(f"  字符数: {len(doc.page_content)}")

            # 内容预览
            preview = doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
            console.print(Panel(
                preview.replace("\n", " "),
                title="[bold]内容预览[/bold]",
                border_style="blue",
                expand=False,
            ))
            console.print()

    except Exception as e:
        console.print(f"\n[red]检索失败: {e}[/red]\n")
        import traceback
        traceback.print_exc()


def interactive_mode():
    """交互模式"""
    console.print("\n[bold cyan]===== 知识库可视化工具 =====[/bold cyan]\n")

    while True:
        console.print("[bold]请选择操作:[/bold]")
        console.print("  1. 显示概览")
        console.print("  2. 浏览切片列表")
        console.print("  3. 查看切片详情")
        console.print("  4. 检索测试")
        console.print("  5. 退出")

        choice = IntPrompt.ask("\n请输入选项", default=1)

        if choice == 1:
            show_overview()

        elif choice == 2:
            category = Prompt.ask("输入类别过滤 (留空跳过)", default="")
            source = Prompt.ask("输入来源过滤 (留空跳过)", default="")
            page = IntPrompt.ask("输入页码", default=1)

            show_browse(
                category=category if category else None,
                source=source if source else None,
                page=page
            )

        elif choice == 3:
            # 先显示一些切片ID供选择
            collection = get_chroma_collection()
            results = collection.get(limit=5, include=["metadatas"])

            console.print("\n[bold]最近的切片ID示例:[/bold]")
            for i, id_ in enumerate(results["ids"], 1):
                source = results["metadatas"][i-1].get("source", "unknown")
                console.print(f"  {i}. {id_[:24]}... (来源: {source})")

            chunk_id = Prompt.ask("\n输入切片ID")
            show_detail(chunk_id)

        elif choice == 4:
            query = Prompt.ask("输入查询文本")
            top_k = IntPrompt.ask("返回数量", default=5)

            dimension = Prompt.ask("维度过滤 (留空跳过)", default="")
            terrain = Prompt.ask("地形过滤 (留空跳过)", default="")

            show_search(
                query=query,
                top_k=top_k,
                dimension=dimension if dimension else None,
                terrain=terrain if terrain else None
            )

        elif choice == 5:
            console.print("\n[bold green]退出[/bold green]\n")
            break

        else:
            console.print("[red]无效选项[/red]")


def list_chunk_ids(pattern: Optional[str] = None):
    """列出所有切片ID"""
    try:
        collection = get_chroma_collection()

        if pattern:
            # 使用正则匹配 source
            import re
            results = collection.get(include=["metadatas"])
            matched_ids = []
            for idx, id_ in enumerate(results["ids"]):
                source = results["metadatas"][idx].get("source", "")
                if re.search(pattern, source, re.IGNORECASE):
                    matched_ids.append(id_)

            console.print(f"\n[bold cyan]匹配 '{pattern}' 的切片ID ({len(matched_ids)} 个):[/bold cyan]\n")
            for id_ in matched_ids[:50]:
                console.print(f"  {id_}")

            if len(matched_ids) > 50:
                console.print(f"\n[dim]... 共 {len(matched_ids)} 个，仅显示前 50 个[/dim]")
        else:
            results = collection.get(limit=100)
            console.print(f"\n[bold cyan]切片ID列表 (前100个):[/bold cyan]\n")
            for id_ in results["ids"]:
                console.print(f"  {id_}")

    except Exception as e:
        console.print(f"\n[red]列出ID失败: {e}[/red]\n")


def main():
    parser = argparse.ArgumentParser(
        description="知识库可视化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/visualize_kb.py --overview
  python scripts/visualize_kb.py --browse --category policies
  python scripts/visualize_kb.py --browse --source "土地管理" --page 2
  python scripts/visualize_kb.py --detail <chunk_id>
  python scripts/visualize_kb.py --search "村庄交通规划"
  python scripts/visualize_kb.py --search "宅基地面积" --dimension land_use --terrain mountain
  python scripts/visualize_kb.py --list-ids --pattern "土地"
  python scripts/visualize_kb.py --interactive
        """
    )

    # 模式参数
    parser.add_argument("--overview", action="store_true", help="显示知识库概览")
    parser.add_argument("--browse", action="store_true", help="浏览切片列表")
    parser.add_argument("--detail", type=str, help="查看切片详情 (需要切片ID)")
    parser.add_argument("--search", type=str, help="检索测试 (需要查询文本)")
    parser.add_argument("--list-ids", action="store_true", help="列出切片ID")
    parser.add_argument("--interactive", action="store_true", help="交互模式")

    # 过滤参数
    parser.add_argument("--category", type=str, help="类别过滤 (policies/cases)")
    parser.add_argument("--source", type=str, help="来源文档过滤")
    parser.add_argument("--dimension", type=str, help="维度过滤 (land_use/traffic)")
    parser.add_argument("--terrain", type=str, help="地形过滤 (mountain/plain)")
    parser.add_argument("--pattern", type=str, help="ID匹配模式 (正则)")

    # 分页参数
    parser.add_argument("--page", type=int, default=1, help="页码")
    parser.add_argument("--page-size", type=int, default=20, help="每页数量")
    parser.add_argument("--top-k", type=int, default=5, help="检索返回数量")

    args = parser.parse_args()

    # 执行对应操作
    if args.overview:
        show_overview()
    elif args.browse:
        show_browse(
            category=args.category,
            source=args.source,
            page=args.page,
            page_size=args.page_size
        )
    elif args.detail:
        show_detail(args.detail)
    elif args.search:
        show_search(
            query=args.search,
            top_k=args.top_k,
            dimension=args.dimension,
            terrain=args.terrain
        )
    elif args.list_ids:
        list_chunk_ids(args.pattern)
    elif args.interactive:
        interactive_mode()
    else:
        # 默认显示概览
        show_overview()


if __name__ == "__main__":
    main()