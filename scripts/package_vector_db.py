"""
向量库打包脚本

功能：
1. 打包 ChromaDB 向量库为压缩文件
2. 可选清理缓存文件
3. 显示打包统计信息

使用方式：
    python scripts/package_vector_db.py [--clean-cache]
"""
import os
import json
import shutil
import tarfile
from pathlib import Path
from datetime import datetime

# 添加 backend 到路径
backend_path = Path(__file__).parent.parent / "backend"
import sys
sys.path.insert(0, str(backend_path))

from app.core.settings import CHROMA_PERSIST_DIR, DATA_DIR


def get_vector_db_size(vector_dir: Path) -> int:
    """计算目录大小"""
    return sum(f.stat().st_size for f in vector_dir.rglob("*") if f.is_file())


def clean_cache_files(vector_dir: Path):
    """清理缓存文件"""
    cache_patterns = ["*.cache", "*.tmp", "__pycache__"]
    cleaned_size = 0
    cleaned_count = 0

    for pattern in cache_patterns:
        for f in vector_dir.rglob(pattern):
            if f.is_file():
                cleaned_size += f.stat().st_size
                f.unlink()
                cleaned_count += 1
            elif f.is_dir():
                dir_size = sum(x.stat().st_size for x in f.rglob("*") if x.is_file())
                cleaned_size += dir_size
                shutil.rmtree(f)
                cleaned_count += 1

    if cleaned_count > 0:
        print(f"✅ 清理缓存: {cleaned_count} 个文件/目录, {cleaned_size / 1024:.1f} KB")
    else:
        print("ℹ️  无需清理缓存")


def package_vector_db(output_name: str = None, include_outline_index: bool = True):
    """打包向量库为压缩文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    if output_name is None:
        output_name = f"chroma_db_{timestamp}.tar.gz"

    output_path = DATA_DIR.parent / "backups" / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n📦 打包向量库...")
    print(f"   源目录: {CHROMA_PERSIST_DIR}")
    print(f"   输出文件: {output_path}")

    if not CHROMA_PERSIST_DIR.exists():
        print(f"❌ 向量库目录不存在: {CHROMA_PERSIST_DIR}")
        return None

    total_size = get_vector_db_size(CHROMA_PERSIST_DIR)
    print(f"   目录大小: {total_size / 1024 / 1024:.2f} MB")

    try:
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(CHROMA_PERSIST_DIR, arcname=CHROMA_PERSIST_DIR.name)

            outline_index_dir = DATA_DIR / "RAG_doc" / "_cache" / "outline_index"
            if include_outline_index and outline_index_dir.exists():
                tar.add(outline_index_dir, arcname="outline_index")

        compressed_size = output_path.stat().st_size
        compression_ratio = (1 - compressed_size / total_size) * 100 if total_size > 0 else 0

        print(f"\n✅ 打包完成!")
        print(f"   原始大小: {total_size / 1024 / 1024:.2f} MB")
        print(f"   压缩大小: {compressed_size / 1024 / 1024:.2f} MB")
        print(f"   压缩率: {compression_ratio:.1f}%")
        print(f"   输出路径: {output_path}")

        return output_path

    except Exception as e:
        print(f"❌ 打包失败: {e}")
        return None


def verify_package(package_path: Path):
    """验证打包文件完整性"""
    print(f"\n🔍 验证打包文件...")
    print(f"   文件: {package_path}")

    if not package_path.exists():
        print(f"❌ 文件不存在")
        return False

    try:
        with tarfile.open(package_path, "r:gz") as tar:
            members = tar.getmembers()
            print(f"   ✅ 文件数量: {len(members)}")

            has_sqlite = any("chroma.sqlite3" in m.name for m in members)
            if has_sqlite:
                print(f"   ✅ 包含 chroma.sqlite3")
            else:
                print(f"   ⚠️  缺少 chroma.sqlite3")

        return True

    except Exception as e:
        print(f"❌ 验证失败: {e}")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="向量库打包工具")
    parser.add_argument("--clean-cache", action="store_true", help="打包前清理缓存文件")
    parser.add_argument("--output", type=str, help="输出文件名")
    parser.add_argument("--verify", type=str, help="验证指定的打包文件")
    args = parser.parse_args()

    print("=" * 60)
    print("📦 向量库打包工具")
    print("=" * 60)

    if args.verify:
        verify_package(Path(args.verify))
        return

    if not CHROMA_PERSIST_DIR.exists():
        print(f"❌ 向量库目录不存在: {CHROMA_PERSIST_DIR}")
        return

    total_size = get_vector_db_size(CHROMA_PERSIST_DIR)
    print(f"\n📊 当前状态:")
    print(f"   目录: {CHROMA_PERSIST_DIR}")
    print(f"   总大小: {total_size / 1024 / 1024:.2f} MB")

    if args.clean_cache:
        print(f"\n🧹 清理缓存...")
        clean_cache_files(CHROMA_PERSIST_DIR)

    output_path = package_vector_db(args.output)

    if output_path:
        verify_package(output_path)

    print("\n" + "=" * 60)
    print("✅ 操作完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
