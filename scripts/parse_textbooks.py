#!/usr/bin/env python3
"""
教材 MinerU 解析脚本

使用 MinerU 精准 API（需 Token）分批处理大型教材文件：
- 每次最多处理 200 页（API 限制）
- 使用 vlm 模型（推荐）
- 自动合并分批结果
- 生成高质量的 Markdown 输出

使用方法：
    python scripts/parse_textbooks.py [--limit N] [--dry-run] [--book "书名"]
"""

import argparse
import logging
import sys
import time
import requests
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Tuple

# 添加 backend 到路径
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from app.core.settings import MINERU_TOKEN, MINERU_TIMEOUT

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "docs" / "RAG 知识库" / "01 专业教材"
OUTPUT_DIR = PROJECT_ROOT / "data" / "RAG_doc" / "_doc_md" / "01_专业教材"

# MinerU 精准 API URL
MINERU_PRECISE_URL = "https://mineru.net/api/v4"

# 每批最大页数（API 限制）
MAX_PAGES_PER_BATCH = 200


def get_textbook_files(source_dir: Path) -> List[Path]:
    """获取教材文件列表"""
    files = []
    for pdf_file in source_dir.glob("*.pdf"):
        files.append(pdf_file)
    return sorted(files)


def get_pdf_page_count(pdf_path: Path) -> int:
    """获取 PDF 页数"""
    doc = fitz.open(str(pdf_path))
    page_count = doc.page_count
    doc.close()
    return page_count


def parse_batch(
    file_path: Path,
    page_start: int,
    page_end: int,
    token: str,
    timeout: int = 600,
) -> Tuple[bool, str]:
    """解析指定页范围

    Args:
        file_path: PDF 文件路径
        page_start: 起始页（从 1 开始）
        page_end: 结束页（包含）
        token: MinerU Token
        timeout: 超时时间

    Returns:
        (success, content_or_error)
    """
    file_name = file_path.name
    page_range = f"{page_start}-{page_end}"

    logger.info(f"  解析页范围: {page_range}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    # 1. 获取批量上传 URL（使用 vlm 模型）
    data = {
        "files": [{"name": file_name, "page_ranges": page_range}],
        "model_version": "vlm",  # 推荐使用 vlm 模型
    }

    resp = requests.post(
        f"{MINERU_PRECISE_URL}/file-urls/batch",
        headers=headers,
        json=data,
        timeout=30,
    )
    result = resp.json()

    if result.get("code") != 0:
        return False, f"获取上传 URL 失败: {result.get('msg')}"

    batch_id = result["data"]["batch_id"]
    file_urls = result["data"]["file_urls"]

    # 2. 上传文件
    with open(file_path, "rb") as f:
        put_resp = requests.put(file_urls[0], data=f, timeout=120)
        if put_resp.status_code not in (200, 201):
            return False, f"上传失败: HTTP {put_resp.status_code}"

    # 3. 轮询等待结果
    start_time = time.time()
    while time.time() - start_time < timeout:
        resp = requests.get(
            f"{MINERU_PRECISE_URL}/extract-results/batch/{batch_id}",
            headers=headers,
            timeout=30,
        )
        result = resp.json()

        if result.get("code") != 0:
            return False, f"查询失败: {result.get('msg')}"

        extract_results = result["data"]["extract_result"]
        elapsed = int(time.time() - start_time)

        for res in extract_results:
            state = res["state"]

            if state == "done":
                zip_url = res["full_zip_url"]
                logger.info(f"    [{elapsed}s] 完成，下载结果...")
                content = download_and_extract_markdown(zip_url)
                return True, content

            if state == "failed":
                err_msg = res.get("err_msg", "Unknown error")
                return False, f"解析失败: {err_msg}"

        logger.info(f"    [{elapsed}s] 处理中...")
        time.sleep(5)

    return False, f"超时 ({timeout}s)"


def download_and_extract_markdown(zip_url: str) -> str:
    """下载 ZIP 并提取 Markdown"""
    import zipfile
    import tempfile

    zip_resp = requests.get(zip_url, timeout=120)
    if zip_resp.status_code != 200:
        raise Exception(f"下载 ZIP 失败: HTTP {zip_resp.status_code}")

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_resp.content)
        tmp_path = tmp.name

    try:
        with zipfile.ZipFile(tmp_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith("full.md"):
                    return zf.read(name).decode("utf-8")
            for name in zf.namelist():
                if name.endswith(".md"):
                    return zf.read(name).decode("utf-8")
        raise Exception("ZIP 中未找到 Markdown 文件")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def parse_textbook(
    file_path: Path,
    output_dir: Path,
    token: str,
    timeout: int = 600,
) -> Tuple[bool, str]:
    """解析整本教材（分批处理）

    Returns:
        (success, message)
    """
    stem = file_path.stem
    output_file = output_dir / f"{stem}_minerU_parsed.md"

    # 检查是否已存在
    if output_file.exists():
        return True, f"已存在，跳过"

    # 获取页数
    page_count = get_pdf_page_count(file_path)
    logger.info(f"  总页数: {page_count}")

    # 计算批次
    batches = []
    for start in range(1, page_count + 1, MAX_PAGES_PER_BATCH):
        end = min(start + MAX_PAGES_PER_BATCH - 1, page_count)
        batches.append((start, end))

    logger.info(f"  分批处理: {len(batches)} 批")

    # 处理每批
    all_content = []
    batch_times = []

    for i, (start, end) in enumerate(batches, 1):
        logger.info(f"  批次 {i}/{len(batches)}: 页 {start}-{end}")

        batch_start = time.time()
        success, result = parse_batch(file_path, start, end, token, timeout)
        batch_time = time.time() - batch_start

        if not success:
            return False, f"批次 {i} 失败: {result}"

        all_content.append(result)
        batch_times.append(batch_time)

        # 批次间隔
        if i < len(batches):
            time.sleep(3)

    # 合并内容
    final_content = "\n\n".join(all_content)

    # 保存结果
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# {stem}\n\n")
        f.write(f"<!-- 解析信息 -->\n")
        f.write(f"<!-- 解析器: MinerU 精准 API (vlm) -->\n")
        f.write(f"<!-- 源文件: {file_path} -->\n")
        f.write(f"<!-- 总页数: {page_count} -->\n")
        f.write(f"<!-- 分批数: {len(batches)} -->\n")
        f.write(f"<!-- 总耗时: {sum(batch_times):.1f}s -->\n\n")
        f.write(final_content)

    return True, f"成功: {len(final_content)} 字符, {len(batches)} 批, {sum(batch_times):.1f}s"


def main():
    parser = argparse.ArgumentParser(description="教材 MinerU 解析")
    parser.add_argument("--limit", type=int, default=0, help="限制处理数量（0=全部）")
    parser.add_argument("--dry-run", action="store_true", help="仅列出文件")
    parser.add_argument("--book", type=str, default="", help="指定书名关键词")
    parser.add_argument("--timeout", type=int, default=600, help="每批超时时间（秒）")
    args = parser.parse_args()

    # 检查 Token
    if not MINERU_TOKEN:
        logger.error("未配置 MINERU_TOKEN，请先配置")
        return

    # 获取文件列表
    files = get_textbook_files(SOURCE_DIR)
    logger.info(f"找到 {len(files)} 本教材")

    # 筛选指定书籍
    if args.book:
        files = [f for f in files if args.book in f.name]
        logger.info(f"筛选后: {len(files)} 本")

    if args.limit > 0:
        files = files[:args.limit]
        logger.info(f"限制处理: {len(files)} 本")

    if args.dry_run:
        logger.info("=== 教材列表 ===")
        for i, f in enumerate(files, 1):
            page_count = get_pdf_page_count(f)
            batches = (page_count + MAX_PAGES_PER_BATCH - 1) // MAX_PAGES_PER_BATCH
            output_file = OUTPUT_DIR / f"{f.stem}_minerU_parsed.md"
            status = "✓ 已存在" if output_file.exists() else f"○ {batches} 批"
            logger.info(f"{i:2d}. {status} | {page_count:4d}页 | {f.name}")
        return

    # 确保输出目录存在
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 统计
    success_count = 0
    fail_count = 0
    skip_count = 0

    # 处理每本教材
    for i, file_path in enumerate(files, 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"[{i}/{len(files)}] {file_path.name}")
        logger.info(f"{'='*60}")

        success, message = parse_textbook(
            file_path,
            OUTPUT_DIR,
            MINERU_TOKEN,
            args.timeout,
        )

        if "已存在" in message:
            logger.info(f"  ○ {message}")
            skip_count += 1
        elif success:
            logger.info(f"  ✓ {message}")
            success_count += 1
        else:
            logger.error(f"  ✗ {message}")
            fail_count += 1

        # 教材间隔
        if i < len(files):
            time.sleep(5)

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