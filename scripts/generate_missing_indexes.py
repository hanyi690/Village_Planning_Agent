#!/usr/bin/env python3
"""
为缺失索引的文档生成索引

使用 HierarchySlicer 的完整流程（包括 LLM 矫正）生成索引。
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys_path = PROJECT_ROOT / "backend"
sys.path.insert(0, str(sys_path))

from app.services.modules.rag.chunker import HierarchySlicer

PENDING_FILES = [
    "data/RAG_doc/_doc_md/01_专业教材/04 《城乡规划管理与法规 》——耿慧志_minerU_parsed.md",
    "data/RAG_doc/_doc_md/03_政策文件/01_国家层面/08 《国土空间调查、规划、用途管制用地用海分类指南（试行）》_minerU_parsed.md",
    "data/RAG_doc/_doc_md/04_技术规范/01_国家层面/镇规划标准（GB 50188 — 2007）_minerU_parsed.md",
    "data/RAG_doc/_doc_md/06_相关案例/休宁县岭南乡溪西村 _minerU_parsed.md",
    "data/RAG_doc/_doc_md/06_相关案例/海丰县县域乡村建设规划（2015-2035年）文本_minerU_parsed.md",
    "data/RAG_doc/_doc_md/06_相关案例/高青县常家镇艾李湖村、胡家堡村村庄规划文本_minerU_parsed.md",
]


def main():
    slicer = HierarchySlicer(use_llm_outline=True)

    for file_path in PENDING_FILES:
        full_path = PROJECT_ROOT / file_path
        if not full_path.exists():
            logger.warning(f"文件不存在: {full_path}")
            continue

        logger.info(f"处理文档: {full_path.name}")

        try:
            chunks, index_data = slicer.slice_with_cache(
                str(full_path),
                force_refresh=True
            )
            logger.info(f"  生成 {len(chunks)} 个切片")
        except Exception as e:
            logger.error(f"  处理失败: {e}")

    logger.info("索引生成完成")


if __name__ == "__main__":
    main()