#!/usr/bin/env python3
"""
批量使用 MinerU 解析扫描版文档

扫描 docs/RAG 知识库 目录（排除教材），使用 MinerU API 解析，
结果保存到 data/RAG_doc/_doc_md/

使用方法：
    python scripts/batch_mineru_parse.py [--limit N] [--dry-run]
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List, Tuple

# 添加 backend 到路径
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from app.utils.mineru_loader import MinerULoader
from app.utils.document_loader import FileTypeDetector

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "docs" / "RAG 知识库"
OUTPUT_DIR = PROJECT_ROOT / "data" / "RAG_doc" / "_doc_md"

# 排除的目录（教材类）
EXCLUDE_DIRS = ["01 专业教材"]


def get_scanned_files(source_dir: Path) -> List[Path]:
    """获取需要解析的扫描版文件列表（排除教材）"""
    files = []

    for pdf_file in source_dir.rglob("*.pdf"):
        # 检查是否在排除目录中
        rel_path = pdf_file.relative_to(source_dir)
        if any(exclude in rel_path.parts for exclude in EXCLUDE_DIRS):
            logger.debug(f"跳过教材: {pdf_file.name}")
            continue

        files.append(pdf_file)

    return sorted(files)


def parse_file(
    file_path: Path,
    output_dir: Path,
    use_agent_api: bool = True,
    token: str = "",
) -> Tuple[bool, str]:
    """使用 MinerU 解析单个文件

    Returns:
        (success, message)
    """
    # 生成输出文件名
    stem = file_path.stem
    output_file = output_dir / f"{stem}_minerU_parsed.md"

    # 检查是否已存在
    if output_file.exists():
        return True, f"已存在，跳过: {output_file.name}"

    # 创建加载器
    loader = MinerULoader(
        file_path,
        use_agent_api=use_agent_api,
        token=token,
        timeout=300,
    )

    try:
        # 解析文档
        start_time = time.time()
        docs = loader.load()

        if not docs:
            return False, "解析结果为空"

        content = docs[0].page_content
        parse_time = time.time() - start_time

        # 保存结果
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# {stem}\n\n")
            f.write(f"<!-- 解析信息 -->\n")
            f.write(f"<!-- 解析器: MinerU -->\n")
            f.write(f"<!-- 源文件: {file_path} -->\n")
            f.write(f"<!-- 解析耗时: {parse_time:.2f}s -->\n\n")
            f.write(content)

        return True, f"成功: {len(content)} 字符, {parse_time:.2f}s"

    except Exception as e:
        import traceback
        return False, f"失败: {str(e)}"


def main():
    parser = argparse.ArgumentParser(description="批量 MinerU 解析扫描版文档")
    parser.add_argument("--limit", type=int, default=0, help="限制处理文件数量（0=全部）")
    parser.add_argument("--dry-run", action="store_true", help="仅列出文件，不解析")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="跳过已存在的文件")
    args = parser.parse_args()

    # 加载配置
    try:
        from app.core.settings import MINERU_TOKEN, MINERU_USE_AGENT_API
        token = MINERU_TOKEN
        use_agent_api = MINERU_USE_AGENT_API
    except ImportError:
        token = ""
        use_agent_api = True

    if not token:
        logger.warning("未配置 MINERU_TOKEN，将使用 Agent 轻量 API（限制 ≤10MB, ≤20页）")

    # 获取文件列表
    files = get_scanned_files(SOURCE_DIR)
    logger.info(f"找到 {len(files)} 个扫描版文件（已排除教材）")

    if args.limit > 0:
        files = files[: args.limit]
        logger.info(f"限制处理前 {args.limit} 个文件")

    if args.dry_run:
        logger.info("=== 文件列表 ===")
        for i, f in enumerate(files, 1):
            output_file = OUTPUT_DIR / f"{f.stem}_minerU_parsed.md"
            status = "✓ 已存在" if output_file.exists() else "○ 待处理"
            logger.info(f"{i:3d}. {status} {f.name}")
        return

    # 确保输出目录存在
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 统计
    success_count = 0
    fail_count = 0
    skip_count = 0

    # 处理每个文件
    for i, file_path in enumerate(files, 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"[{i}/{len(files)}] 处理: {file_path.name}")
        logger.info(f"{'='*60}")

        # 检查是否已存在
        output_file = OUTPUT_DIR / f"{file_path.stem}_minerU_parsed.md"
        if args.skip_existing and output_file.exists():
            logger.info(f"  已存在，跳过")
            skip_count += 1
            continue

        # 解析
        success, message = parse_file(
            file_path,
            OUTPUT_DIR,
            use_agent_api=use_agent_api,
            token=token,
        )

        if success:
            logger.info(f"  ✓ {message}")
            success_count += 1
        else:
            logger.error(f"  ✗ {message}")
            fail_count += 1

        # 避免请求过快
        if i < len(files):
            time.sleep(2)

    # 汇总
    logger.info(f"\n{'='*60}")
    logger.info("处理完成")
    logger.info(f"{'='*60}")
    logger.info(f"成功: {success_count}")
    logger.info(f"失败: {fail_count}")
    logger.info(f"跳过: {skip_count}")
    logger.info(f"输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()