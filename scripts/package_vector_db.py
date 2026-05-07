"""
向量库优化打包脚本

功能：
1. 清理临时缓存文件
2. 压缩JSON文件（移除冗余数据）
3. 打包为可共享的压缩文件
"""
import os
import json
import shutil
import zipfile
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
CHROMA_DIR = PROJECT_ROOT / "knowledge_base" / "chroma_db"


def clean_cache():
    """清理查询缓存"""
    cache_dir = CHROMA_DIR / "cache"
    if cache_dir.exists():
        cache_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
        shutil.rmtree(cache_dir)
        print(f"✅ 清理缓存: {cache_size / 1024:.1f} KB")
    else:
        print("ℹ️  缓存目录不存在")


def optimize_document_index():
    """优化文档索引JSON - 移除冗余字段"""
    index_file = CHROMA_DIR / "document_index.json"
    if not index_file.exists():
        print("ℹ️  document_index.json 不存在")
        return

    # 读取原文件
    with open(index_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    original_size = index_file.stat().st_size

    # 优化：移除空字段、压缩章节摘要
    optimized = {}
    for source, info in data.items():
        optimized[source] = {
            "total_chunks": info.get("total_chunks", 0),
            "category": info.get("category", "unknown"),
            # 保留必要的元数据，移除大量内容
        }

    # 写入优化后的文件
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(optimized, f, ensure_ascii=False, indent=2)

    new_size = index_file.stat().st_size
    print(f"✅ 优化 document_index.json: {original_size / 1024 / 1024:.1f}MB -> {new_size / 1024:.1f}KB")


def remove_analysis_report():
    """移除切片分析报告（可选，不影响检索）"""
    analysis_file = CHROMA_DIR / "slices_analysis.json"
    if analysis_file.exists():
        size = analysis_file.stat().st_size
        # 移动到备份目录而非删除
        backup_dir = PROJECT_ROOT / "knowledge_base" / "backup"
        backup_dir.mkdir(exist_ok=True)
        shutil.move(str(analysis_file), str(backup_dir / "slices_analysis.json.bak"))
        print(f"✅ 移动 slices_analysis.json 到备份目录: {size / 1024 / 1024:.1f}MB")
    else:
        print("ℹ️  slices_analysis.json 不存在")


def package_vector_db(output_name: str = None):
    """打包向量库为压缩文件"""
    if output_name is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_name = f"chroma_db_{timestamp}.zip"

    output_path = PROJECT_ROOT / "knowledge_base" / output_name

    # 计算打包前大小
    total_size = sum(f.stat().st_size for f in CHROMA_DIR.rglob("*") if f.is_file())

    print(f"\n📦 打包向量库...")
    print(f"   源目录: {CHROMA_DIR}")
    print(f"   输出文件: {output_path}")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in CHROMA_DIR.rglob("*"):
            if file_path.is_file():
                # 保持相对路径结构
                arcname = file_path.relative_to(CHROMA_DIR)
                zf.write(file_path, arcname)
                print(f"   添加: {arcname} ({file_path.stat().st_size / 1024:.1f}KB)")

    compressed_size = output_path.stat().st_size
    compression_ratio = (1 - compressed_size / total_size) * 100

    print(f"\n✅ 打包完成!")
    print(f"   原始大小: {total_size / 1024 / 1024:.1f}MB")
    print(f"   压缩大小: {compressed_size / 1024 / 1024:.1f}MB")
    print(f"   压缩率: {compression_ratio:.1f}%")
    print(f"   输出路径: {output_path}")

    return output_path


def main():
    """执行优化和打包"""
    print("=" * 60)
    print("🔧 向量库优化打包")
    print("=" * 60)

    # 检查向量库状态
    if not CHROMA_DIR.exists():
        print(f"❌ 向量库目录不存在: {CHROMA_DIR}")
        return

    # 统计当前状态
    total_size = sum(f.stat().st_size for f in CHROMA_DIR.rglob("*") if f.is_file())
    print(f"\n📊 当前状态:")
    print(f"   目录: {CHROMA_DIR}")
    print(f"   总大小: {total_size / 1024 / 1024:.1f}MB")

    # 1. 清理缓存
    print(f"\n🧹 步骤1: 清理缓存")
    clean_cache()

    # 2. 优化文档索引
    print(f"\n📝 步骤2: 优化文档索引")
    optimize_document_index()

    # 3. 移除分析报告
    print(f"\n📊 步骤3: 移除分析报告")
    remove_analysis_report()

    # 4. 打包
    output_path = package_vector_db()

    # 最终统计
    final_size = sum(f.stat().st_size for f in CHROMA_DIR.rglob("*") if f.is_file())
    print(f"\n" + "=" * 60)
    print(f"📋 优化结果:")
    print(f"   原始大小: {total_size / 1024 / 1024:.1f}MB")
    print(f"   优化后大小: {final_size / 1024 / 1024:.1f}MB")
    print(f"   压缩包大小: {output_path.stat().st_size / 1024 / 1024:.1f}MB")
    print(f"=" * 60)


if __name__ == "__main__":
    main()