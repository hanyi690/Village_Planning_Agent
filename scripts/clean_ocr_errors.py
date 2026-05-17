#!/usr/bin/env python3
"""
清洗 OCR 解析错误

针对 04 《城乡规划管理与法规 》——耿慧志_minerU_parsed.md 中的 OCR 乱码表格：
- 检测重复的"乡、乡、乡..."和"面积范围为"模式
- 将乱码表格行替换为占位符

使用方法：
    python scripts/clean_ocr_errors.py [--dry-run]
"""

import argparse
import re
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MD_DIR = PROJECT_ROOT / "data" / "RAG_doc" / "_doc_md"

# OCR 错误文档
OCR_ERROR_DOC = "04 《城乡规划管理与法规 》——耿慧志_minerU_parsed.md"

# 乱码检测模式
GARBAGE_PATTERNS = [
    (r"乡、乡、乡", 5),       # "乡、乡、乡" 重复超过 5 次
    (r"面积范围为", 20),     # "面积范围为" 重复超过 20 次
]


def detect_ocr_garbage(content: str) -> bool:
    """检测 OCR 解析错误产生的乱码"""
    for pattern, threshold in GARBAGE_PATTERNS:
        matches = re.findall(pattern, content)
        if len(matches) > threshold:
            return True
    return False


def clean_table_garbage(table_content: str) -> str:
    """清洗表格中的乱码行"""
    # 提取表格行
    rows = re.findall(r'<tr>.*?</tr>', table_content, re.DOTALL)
    cleaned_rows = []
    garbage_count = 0

    for row in rows:
        if detect_ocr_garbage(row):
            # 替换乱码行为占位符
            cleaned_rows.append("<tr><td>[表格内容因 OCR 解析错误已省略]</td></tr>")
            garbage_count += 1
        else:
            cleaned_rows.append(row)

    # 重建表格
    result = "<table>" + "\n".join(cleaned_rows) + "</table>"
    return result, garbage_count


def clean_document(md_path: Path, dry_run: bool = False) -> dict:
    """清洗文档中的 OCR 错误"""
    content = md_path.read_text(encoding="utf-8")
    original_size = len(content)

    # 查找所有表格
    tables = re.findall(r'<table>.*?</table>', content, re.DOTALL)
    total_garbage = 0
    cleaned_content = content

    for table in tables:
        if detect_ocr_garbage(table):
            cleaned_table, garbage_count = clean_table_garbage(table)
            cleaned_content = cleaned_content.replace(table, cleaned_table)
            total_garbage += garbage_count
            logger.info(f"发现乱码表格: {garbage_count} 行乱码")

    cleaned_size = len(cleaned_content)

    if not dry_run and total_garbage > 0:
        # 保存清洗后的内容
        md_path.write_text(cleaned_content, encoding="utf-8")
        logger.info(f"已保存清洗后的文档: {md_path}")

    return {
        "original_size": original_size,
        "cleaned_size": cleaned_size,
        "garbage_rows": total_garbage,
        "tables_found": len(tables),
        "tables_cleaned": sum(1 for t in tables if detect_ocr_garbage(t)),
    }


def main():
    parser = argparse.ArgumentParser(description="清洗 OCR 解析错误")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不保存")
    args = parser.parse_args()

    # 查找 OCR 错误文档
    md_path = None
    for f in MD_DIR.rglob(OCR_ERROR_DOC):
        md_path = f
        break

    if md_path is None:
        logger.error(f"未找到文档: {OCR_ERROR_DOC}")
        return

    logger.info(f"处理文档: {md_path}")

    if args.dry_run:
        logger.info("=== 预览模式 ===")

    result = clean_document(md_path, dry_run=args.dry_run)

    logger.info("\n=== 清洗报告 ===")
    logger.info(f"原始大小: {result['original_size']} 字符")
    logger.info(f"清洗后大小: {result['cleaned_size']} 字符")
    logger.info(f"发现表格: {result['tables_found']} 个")
    logger.info(f"乱码表格: {result['tables_cleaned']} 个")
    logger.info(f"乱码行数: {result['garbage_rows']} 行")

    if args.dry_run:
        logger.info("\n提示: 使用 --dry-run 预览，去掉参数执行实际清洗")
    else:
        logger.info("\n清洗完成")


if __name__ == "__main__":
    main()