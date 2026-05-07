"""
向量库 OSS 同步脚本

功能：
1. 上传向量库到阿里云OSS（打包并上传）
2. 从OSS下载向量库（下载并解压）
3. 验证向量库完整性（检索测试）

使用方式：
    python scripts/sync_kb_to_oss.py --upload
    python scripts/sync_kb_to_oss.py --download
    python scripts/sync_kb_to_oss.py --verify
    python scripts/sync_kb_to_oss.py --download --test-dir ./test_kb
"""
import os
import sys
import argparse
import tarfile
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))

from src.rag.config import (
    CHROMA_PERSIST_DIR,
    OSS_ACCESS_KEY_ID,
    OSS_ACCESS_KEY_SECRET,
    OSS_ENDPOINT,
    OSS_BUCKET_NAME,
    OSS_KB_PATH,
)


def check_oss_config():
    """检查OSS配置是否完整"""
    missing = []
    if not OSS_ACCESS_KEY_ID:
        missing.append("OSS_ACCESS_KEY_ID")
    if not OSS_ACCESS_KEY_SECRET:
        missing.append("OSS_ACCESS_KEY_SECRET")
    if not OSS_BUCKET_NAME:
        missing.append("OSS_BUCKET_NAME")

    if missing:
        print(f"❌ OSS配置缺失，请设置环境变量:")
        for key in missing:
            print(f"   {key}=...")
        print("\n示例 (.env 文件):")
        print("   OSS_ACCESS_KEY_ID=your_access_key_id")
        print("   OSS_ACCESS_KEY_SECRET=your_access_key_secret")
        print("   OSS_ENDPOINT=oss-cn-shenzhen.aliyuncs.com")
        print("   OSS_BUCKET_NAME=your-bucket-name")
        return False
    return True


def get_oss_bucket():
    """获取OSS Bucket对象"""
    try:
        import oss2
    except ImportError:
        print("❌ oss2库未安装，请执行: pip install oss2")
        sys.exit(1)

    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
    return bucket


def package_vector_store(source_dir: Path, output_file: Path):
    """打包向量库目录为tar.gz"""
    print(f"\n📦 打包向量库...")
    print(f"   源目录: {source_dir}")
    print(f"   输出文件: {output_file}")

    if not source_dir.exists():
        print(f"❌ 向量库目录不存在: {source_dir}")
        return False

    # 计算目录大小
    total_size = sum(f.stat().st_size for f in source_dir.rglob("*") if f.is_file())
    print(f"   目录大小: {total_size / 1024 / 1024:.2f} MB")

    try:
        with tarfile.open(output_file, "w:gz") as tar:
            tar.add(source_dir, arcname=source_dir.name)
        print(f"✅ 打包完成: {output_file.stat().st_size / 1024 / 1024:.2f} MB")
        return True
    except Exception as e:
        print(f"❌ 打包失败: {e}")
        return False


def upload_to_oss(local_file: Path, oss_path: str):
    """上传文件到OSS"""
    print(f"\n☁️  上传到OSS...")
    print(f"   本地文件: {local_file}")
    print(f"   OSS路径: oss://{OSS_BUCKET_NAME}/{oss_path}")

    bucket = get_oss_bucket()

    try:
        # 使用进度回调
        def progress_callback(consumed_bytes, total_bytes):
            if total_bytes:
                percent = int(100 * float(consumed_bytes) / float(total_bytes))
                print(f"   上传进度: {percent}% ({consumed_bytes / 1024 / 1024:.1f}MB / {total_bytes / 1024 / 1024:.1f}MB)")

        bucket.put_object_from_file(
            oss_path,
            str(local_file),
            progress_callback=progress_callback
        )

        print(f"✅ 上传完成")

        # 获取上传后的文件信息
        info = bucket.head_object(oss_path)
        print(f"   OSS文件大小: {info.content_length / 1024 / 1024:.2f} MB")
        return True

    except oss2.exceptions.OssError as e:
        print(f"❌ OSS上传失败: {e.status} {e.message}")
        return False
    except Exception as e:
        print(f"❌ 上传失败: {e}")
        return False


def download_from_oss(oss_path: str, local_file: Path):
    """从OSS下载文件"""
    print(f"\n☁️  从OSS下载...")
    print(f"   OSS路径: oss://{OSS_BUCKET_NAME}/{oss_path}")
    print(f"   本地文件: {local_file}")

    bucket = get_oss_bucket()

    try:
        # 检查文件是否存在
        if not bucket.object_exists(oss_path):
            print(f"❌ OSS文件不存在: {oss_path}")
            return False

        # 获取文件信息
        info = bucket.head_object(oss_path)
        print(f"   OSS文件大小: {info.content_length / 1024 / 1024:.2f} MB")

        # 下载文件
        def progress_callback(consumed_bytes, total_bytes):
            if total_bytes:
                percent = int(100 * float(consumed_bytes) / float(total_bytes))
                print(f"   下载进度: {percent}% ({consumed_bytes / 1024 / 1024:.1f}MB / {total_bytes / 1024 / 1024:.1f}MB)")

        bucket.get_object_to_file(
            oss_path,
            str(local_file),
            progress_callback=progress_callback
        )

        print(f"✅ 下载完成: {local_file.stat().st_size / 1024 / 1024:.2f} MB")
        return True

    except oss2.exceptions.OssError as e:
        print(f"❌ OSS下载失败: {e.status} {e.message}")
        return False
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return False


def extract_package(package_file: Path, target_dir: Path):
    """解压向量库包"""
    print(f"\n📦 解压向量库...")
    print(f"   包文件: {package_file}")
    print(f"   目标目录: {target_dir}")

    try:
        with tarfile.open(package_file, "r:gz") as tar:
            # 解压到临时目录
            temp_extract = target_dir.parent / "temp_extract"
            tar.extractall(temp_extract)

            # 移动解压后的内容到目标目录
            extracted_dir = temp_extract / package_file.stem.replace(".tar.gz", "")
            if extracted_dir.exists():
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.move(str(extracted_dir), str(target_dir))

            # 清理临时目录
            shutil.rmtree(temp_extract)

        # 计算解压后大小
        total_size = sum(f.stat().st_size for f in target_dir.rglob("*") if f.is_file())
        print(f"✅ 解压完成: {total_size / 1024 / 1024:.2f} MB")
        return True

    except Exception as e:
        print(f"❌ 解压失败: {e}")
        return False


def verify_vector_store(vector_dir: Path):
    """验证向量库完整性"""
    print(f"\n🔍 验证向量库...")
    print(f"   目录: {vector_dir}")

    # 检查必要文件
    required_files = [
        "chroma.sqlite3",
        "slices_analysis.json",
    ]

    missing_files = []
    for f in required_files:
        file_path = vector_dir / f
        if not file_path.exists():
            missing_files.append(f)

    if missing_files:
        print(f"❌ 缺少必要文件: {missing_files}")
        return False

    print(f"✅ 必要文件检查通过")

    # 检查Collection数据
    collection_dirs = [d for d in vector_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if not collection_dirs:
        print(f"❌ 没有找到Collection数据目录")
        return False

    print(f"   Collection数量: {len(collection_dirs)}")

    # 尝试加载向量库进行检索测试
    print(f"\n   进行检索测试...")
    try:
        from langchain_chroma import Chroma
        from src.rag.core.cache import get_vector_cache

        embedding_model = get_vector_cache().get_embedding_model()
        vectorstore = Chroma(
            persist_directory=str(vector_dir),
            embedding_function=embedding_model,
            collection_name="rural_planning",
        )

        # 测试检索
        test_query = "用地规划"
        results = vectorstore.similarity_search(test_query, k=3)

        if results:
            print(f"   ✅ 检索测试成功: 返回 {len(results)} 条结果")
            for i, doc in enumerate(results[:2]):
                print(f"      [{i+1}] {doc.metadata.get('source', 'unknown')[:50]}...")
            return True
        else:
            print(f"   ⚠️  检索返回空结果，可能数据有问题")
            return False

    except Exception as e:
        print(f"   ❌ 检索测试失败: {e}")
        return False


def list_oss_kb_versions():
    """列出OSS上的向量库版本"""
    print(f"\n📋 列出OSS上的向量库文件...")

    bucket = get_oss_bucket()

    try:
        objects = oss2.ObjectIterator(bucket, prefix=OSS_KB_PATH)

        versions = []
        for obj in objects:
            if obj.key.endswith(".tar.gz"):
                # 提取版本信息（从文件名）
                filename = Path(obj.key).name
                size_mb = obj.size / 1024 / 1024
                last_modified = datetime.fromtimestamp(obj.last_modified)
                versions.append({
                    "filename": filename,
                    "oss_path": obj.key,
                    "size_mb": size_mb,
                    "last_modified": last_modified,
                })

        if versions:
            print(f"   找到 {len(versions)} 个版本:")
            for v in versions:
                print(f"   - {v['filename']}: {v['size_mb']:.2f}MB, 更新时间: {v['last_modified']}")
        else:
            print(f"   没有找到向量库文件")

        return versions

    except oss2.exceptions.OssError as e:
        print(f"❌ 列出OSS文件失败: {e.status} {e.message}")
        return []


def do_upload():
    """执行上传操作"""
    if not check_oss_config():
        return False

    # 生成带时间戳的文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tar_filename = f"chroma_db_{timestamp}.tar.gz"
    local_tar = Path(tempfile.gettempdir()) / tar_filename
    oss_path = f"{OSS_KB_PATH}/{tar_filename}"

    # 打包
    if not package_vector_store(CHROMA_PERSIST_DIR, local_tar):
        return False

    # 上传
    if not upload_to_oss(local_tar, oss_path):
        return False

    # 清理临时文件
    local_tar.unlink()

    print(f"\n✅ 向量库已上传到: oss://{OSS_BUCKET_NAME}/{oss_path}")
    return True


def do_download(test_dir: Path = None):
    """执行下载操作"""
    if not check_oss_config():
        return False

    # 列出可用版本
    versions = list_oss_kb_versions()
    if not versions:
        print("❌ OSS上没有可用的向量库")
        return False

    # 选择最新版本
    latest = versions[0]
    oss_path = latest["oss_path"]
    print(f"\n将下载最新版本: {latest['filename']}")

    # 准备下载路径
    local_tar = Path(tempfile.gettempdir()) / latest["filename"]
    target_dir = test_dir or CHROMA_PERSIST_DIR

    # 下载
    if not download_from_oss(oss_path, local_tar):
        return False

    # 解压
    if not extract_package(local_tar, target_dir):
        return False

    # 清理临时文件
    local_tar.unlink()

    print(f"\n✅ 向量库已下载到: {target_dir}")
    return True


def do_verify(vector_dir: Path = None):
    """执行验证操作"""
    vector_dir = vector_dir or CHROMA_PERSIST_DIR

    if not vector_dir.exists():
        print(f"❌ 向量库目录不存在: {vector_dir}")
        return False

    return verify_vector_store(vector_dir)


def main():
    parser = argparse.ArgumentParser(description="向量库OSS同步工具")
    parser.add_argument("--upload", action="store_true", help="打包并上传向量库到OSS")
    parser.add_argument("--download", action="store_true", help="从OSS下载向量库")
    parser.add_argument("--verify", action="store_true", help="验证向量库完整性")
    parser.add_argument("--list", action="store_true", help="列出OSS上的向量库版本")
    parser.add_argument("--test-dir", type=str, help="下载测试目录（用于--download）")

    args = parser.parse_args()

    print("=" * 60)
    print("📦 向量库 OSS 同步工具")
    print("=" * 60)

    if args.upload:
        success = do_upload()
    elif args.download:
        test_dir = Path(args.test_dir) if args.test_dir else None
        success = do_download(test_dir)
    elif args.verify:
        success = do_verify()
    elif args.list:
        if not check_oss_config():
            success = False
        else:
            versions = list_oss_kb_versions()
            success = len(versions) > 0
    else:
        parser.print_help()
        success = True

    print("\n" + "=" * 60)
    if success:
        print("✅ 操作完成")
    else:
        print("❌ 操作失败")
    print("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())