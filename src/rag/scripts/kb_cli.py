"""
知识库管理 CLI 工具

使用方法:
    # 添加文档
    python -m src.rag.scripts.kb_cli add data/policies/新文件.docx
    
    # 删除文档
    python -m src.rag.scripts.kb_cli delete 新文件.docx
    
    # 列出所有文档
    python -m src.rag.scripts.kb_cli list
    
    # 查看统计信息
    python -m src.rag.scripts.kb_cli stats
    
    # 重建文档索引
    python -m src.rag.scripts.kb_cli rebuild-index
"""

import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.rag.core.kb_manager import get_kb_manager


def cmd_add(args):
    """添加文档到知识库"""
    manager = get_kb_manager()
    
    file_path = args.file
    category = args.category
    
    if not Path(file_path).exists():
        print(f"❌ 文件不存在: {file_path}")
        return 1
    
    result = manager.add_document(file_path, category=category)
    
    if result["status"] == "success":
        print(f"\n✅ {result['message']}")
        print(f"   切片数: {result['chunks_added']}")
        return 0
    else:
        print(f"\n❌ {result['message']}")
        return 1


def cmd_delete(args):
    """从知识库删除文档"""
    manager = get_kb_manager()
    
    source_name = args.source
    
    result = manager.delete_document(source_name)
    
    if result["status"] == "success":
        print(f"\n✅ {result['message']}")
        return 0
    elif result["status"] == "warning":
        print(f"\n⚠️  {result['message']}")
        return 0
    else:
        print(f"\n❌ {result['message']}")
        return 1


def cmd_list(args):
    """列出知识库中的文档"""
    manager = get_kb_manager()
    
    docs = manager.list_documents()
    
    if not docs:
        print("\n📚 知识库为空")
        return 0
    
    print(f"\n📚 知识库文档列表 ({len(docs)} 个文档):\n")
    print(f"{'序号':<4} {'文档名称':<40} {'切片数':<8} {'类型':<10}")
    print("-" * 70)
    
    for idx, doc in enumerate(docs, 1):
        print(f"{idx:<4} {doc['source']:<40} {doc['chunk_count']:<8} {doc['doc_type']:<10}")
    
    total_chunks = sum(d["chunk_count"] for d in docs)
    print(f"\n   总计: {len(docs)} 个文档, {total_chunks} 个切片")
    
    return 0


def cmd_stats(args):
    """显示知识库统计信息"""
    manager = get_kb_manager()
    
    stats = manager.get_stats()
    
    print("\n" + "=" * 50)
    print("📊 知识库统计信息")
    print("=" * 50)
    
    print(f"\n📁 基本信息:")
    print(f"   文档数量: {stats.get('total_documents', 0)}")
    print(f"   切片数量: {stats.get('total_chunks', 0)}")
    print(f"   源文件目录: {stats.get('source_dir', 'N/A')}")
    print(f"   向量库路径: {stats.get('vector_db_path', 'N/A')}")
    
    cache = stats.get("cache", {})
    if cache:
        print(f"\n💾 缓存信息:")
        print(f"   内存缓存数: {cache.get('memory_cache_count', 0)}")
        print(f"   持久化缓存数: {cache.get('persistent_cache_count', 0)}")
        print(f"   缓存大小: {cache.get('persistent_cache_size_mb', 0)} MB")
    
    return 0


def cmd_rebuild_index(args):
    """重建文档索引"""
    manager = get_kb_manager()
    
    print("\n⚠️  注意：这将重建文档索引，但不会修改向量数据")
    confirm = input("确认继续？(y/n): ").strip().lower()
    
    if confirm not in ['y', 'yes', '是']:
        print("已取消")
        return 0
    
    result = manager.rebuild_index()
    
    if result["status"] == "success":
        print(f"\n✅ {result['message']}")
        print(f"   文档数: {result.get('documents', 0)}")
        print(f"   切片数: {result.get('splits', 0)}")
        return 0
    else:
        print(f"\n❌ {result['message']}")
        return 1


def cmd_sync(args):
    """同步源文件目录到知识库"""
    manager = get_kb_manager()
    
    from src.rag.config import DATA_DIR
    from src.rag.utils.loaders import SUPPORTED_EXTENSIONS
    
    print(f"\n🔄 同步源文件目录: {DATA_DIR}")
    
    # 扫描源文件目录
    source_files = []
    for ext in SUPPORTED_EXTENSIONS.keys():
        source_files.extend(DATA_DIR.rglob(f"*{ext}"))
    
    # 获取知识库中已有的文档
    existing_docs = {d["source"] for d in manager.list_documents()}
    
    # 找出需要添加的文件
    to_add = []
    for f in source_files:
        if f.name not in existing_docs:
            to_add.append(f)
    
    if not to_add:
        print("   ✅ 知识库已是最新，无需同步")
        return 0
    
    print(f"   发现 {len(to_add)} 个新文件需要添加:\n")
    for f in to_add:
        print(f"   - {f}")
    
    if not args.yes:
        confirm = input("\n确认添加这些文件？(y/n): ").strip().lower()
        if confirm not in ['y', 'yes', '是']:
            print("已取消")
            return 0
    
    # 添加文件
    success_count = 0
    for f in to_add:
        result = manager.add_document(str(f))
        if result["status"] == "success":
            success_count += 1
            print(f"   ✅ {f.name}")
        else:
            print(f"   ❌ {f.name}: {result['message']}")
    
    print(f"\n✅ 同步完成: 添加了 {success_count}/{len(to_add)} 个文件")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="知识库管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.rag.scripts.kb_cli add data/policies/新政策.docx
  python -m src.rag.scripts.kb_cli delete 新政策.docx
  python -m src.rag.scripts.kb_cli list
  python -m src.rag.scripts.kb_cli stats
  python -m src.rag.scripts.kb_cli sync
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # add 命令
    add_parser = subparsers.add_parser("add", help="添加文档到知识库")
    add_parser.add_argument("file", help="文档文件路径")
    add_parser.add_argument("-c", "--category", default=None, help="文档类别 (policies/cases)")
    add_parser.set_defaults(func=cmd_add)
    
    # delete 命令
    delete_parser = subparsers.add_parser("delete", help="从知识库删除文档")
    delete_parser.add_argument("source", help="文档名称（文件名）")
    delete_parser.set_defaults(func=cmd_delete)
    
    # list 命令
    list_parser = subparsers.add_parser("list", help="列出知识库中的文档")
    list_parser.set_defaults(func=cmd_list)
    
    # stats 命令
    stats_parser = subparsers.add_parser("stats", help="显示知识库统计信息")
    stats_parser.set_defaults(func=cmd_stats)
    
    # rebuild-index 命令
    rebuild_parser = subparsers.add_parser("rebuild-index", help="重建文档索引")
    rebuild_parser.set_defaults(func=cmd_rebuild_index)
    
    # sync 命令
    sync_parser = subparsers.add_parser("sync", help="同步源文件目录到知识库")
    sync_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认")
    sync_parser.set_defaults(func=cmd_sync)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
