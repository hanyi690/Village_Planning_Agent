#!/usr/bin/env python3
"""
重新入库需要处理的文档

功能：
1. 读取需要重新入库的文档列表（25 个）
2. 删除旧 index 缓存和向量库存储
3. 清洗 OCR 错误文档
4. 使用 LLM 矫正和完整入库流程重新入库

使用方法：
    python scripts/reindex_documents.py [--dry-run] [--limit N]
"""

import argparse
import asyncio
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 添加 backend 到路径
backend_path = Path(__file__).parent.parent / "backend"
import sys
sys.path.insert(0, str(backend_path))

from app.services.modules.rag.service import RagService
from app.core.settings import OUTLINE_INDEX_DIR, CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME

# 路径配置
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MD_DIR = PROJECT_ROOT / "data" / "RAG_doc" / "_doc_md"
CACHE_DIR = PROJECT_ROOT / "data" / "RAG_doc" / "_cache"
REINDEX_LIST_FILE = CACHE_DIR / "reindex_list.txt"

# 需要重新入库的文档列表（从 chunk_analysis_summary_5000.json）
# 直接从 reindex_list.txt 读取
def load_reindex_docs():
    """从文件加载需要重新入库的文档列表"""
    if REINDEX_LIST_FILE.exists():
        return [line.strip() for line in REINDEX_LIST_FILE.read_text(encoding='utf-8').strip().split('\n') if line.strip()]
    # 如果文件不存在，使用硬编码列表
    return [
        "01 《城市规划原理》——吴志强等_minerU_parsed_index.json",
        "01 《广东省村庄规划编制基本技术指南（试行）》_minerU_parsed_index.json",
        "01 《村庄规划用地分类指南》_minerU_parsed_index.json",
        "02 《乡村规划原理 》——李京生_minerU_parsed_index.json",
        "03 《乡村规划概论》——何杰等_minerU_parsed_index.json",
        "04 《土地利用现状分类》GBT 21010-2017_minerU_parsed_index.json",
        "04 《城乡规划管理与法规 》——耿慧志_minerU_parsed_index.json",
        "05 《实用性村庄规划编制手册》——李巍等_minerU_parsed_index.json",
        "06 《村镇总体规划》——叶昌东_minerU_parsed_index.json",
        "08 《国土空间调查、规划、用途管制用地用海分类指南（试行）》_minerU_parsed_index.json",
        "08 《美丽乡村系列丛书 美丽乡村规划设计概论与案例分析 》——张天柱等_minerU_parsed_index.json",
        "13 《乡村振兴用地政策指南（2023 年）》_minerU_parsed_index.json",
        "GB 5749-2022.生活饮用水卫生标准_minerU_parsed_index.json",
        "【文本图件附件】池州市青阳县丁桥镇牛山村村庄规划（2021-2035）_minerU_parsed_index.json",
        "休宁县岭南乡溪西村 _minerU_parsed_index.json",
        "住建部 全国优秀村镇规划案例集_minerU_parsed_index.json",
        "住建部_全国优秀村镇规划案例集_minerU_parsed_index.json",
        "宿州市埇桥区永安镇永安村村庄规划（2021-2035年）_minerU_parsed_index.json",
        "村土地利用规划编制技术导则_minerU_parsed_index.json",
        "海丰县县域乡村建设规划（2015-2035年）文本_minerU_parsed_index.json",
        "赫山区兰溪镇莲花塘村和金石村村庄规划（2020-2035年）_minerU_parsed_index.json",
        "镇规划标准（GB 50188 — 2007）_minerU_parsed_index.json",
        "高青县常家镇艾李湖村、胡家堡村村庄规划文本_minerU_parsed_index.json",
        "高青县常家镇艾李湖村、胡家堡村村庄规划说明书_minerU_parsed_index.json",
    ]

REINDEX_DOCS = load_reindex_docs()

# OCR 错误文档（需要先清洗）
OCR_ERROR_DOC = "04 《城乡规划管理与法规 》——耿慧志_minerU_parsed_index.json"


def get_md_path(index_name: str) -> Path:
    """从 index 文件名获取对应的 md 文件路径"""
    # index 文件名格式: xxx_minerU_parsed_index.json
    # md 文件名格式: xxx_minerU_parsed.md
    md_name = index_name.replace("_index.json", ".md")
    for f in MD_DIR.rglob(md_name):
        return f
    return None


def get_source_name(index_name: str) -> str:
    """从 index 文件名获取 source_name"""
    return index_name.replace("_index.json", ".md")


def delete_old_cache(source_name: str) -> bool:
    """删除旧的 index 缓存"""
    index_path = OUTLINE_INDEX_DIR / source_name.replace(".md", "_index.json")
    if index_path.exists():
        index_path.unlink()
        logger.info(f"删除旧缓存: {index_path}")
        return True
    return False


def delete_from_vector_store(source_name: str) -> bool:
    """从向量库删除旧向量"""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
        collection = client.get_collection(name=CHROMA_COLLECTION_NAME)

        # 查询并删除
        results = collection.get(
            where={"source": source_name},
            include=["metadatas"]
        )

        if results.get("ids"):
            collection.delete(ids=results["ids"])
            logger.info(f"删除向量: {len(results['ids'])} 条")
            return True

        return False
    except Exception as e:
        logger.warning(f"删除向量失败: {e}")
        return False


async def ingest_document(service: RagService, md_path: Path, use_llm: bool = True) -> Dict:
    """入库单个文档（使用 LLM 矫正）"""
    file_path = str(md_path)

    # 使用完整的 LLM 矫正入库流程
    result = await service.add_markdown_document(
        file_path=file_path,
        use_llm_inference=use_llm,  # 使用 LLM 推断文档类型
    )

    return {
        "status": result.get("status"),
        "chunks_added": result.get("chunks_added", 0),
        "message": result.get("message", ""),
        "doc_type": result.get("doc_type", ""),
    }


async def main():
    parser = argparse.ArgumentParser(description="重新入库文档")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不执行")
    parser.add_argument("--limit", type=int, default=0, help="限制处理数量（0=全部）")
    parser.add_argument("--skip-clean", action="store_true", help="跳过 OCR 清洗")
    parser.add_argument("--no-llm", action="store_true", help="不使用 LLM 矫正（加快速度）")
    args = parser.parse_args()

    docs = REINDEX_DOCS
    if args.limit > 0:
        docs = docs[:args.limit]
        logger.info(f"限制处理前 {args.limit} 个文档")

    if args.dry_run:
        logger.info("=== 预览模式 ===")
        logger.info(f"待处理文档: {len(docs)} 个")
        for i, doc in enumerate(docs, 1):
            md_path = get_md_path(doc)
            source_name = get_source_name(doc)
            status = "OK" if md_path else "MISSING"
            ocr_flag = " [OCR_ERROR]" if doc == OCR_ERROR_DOC else ""
            logger.info(f"{i:3d}. [{status}] {source_name}{ocr_flag}")
        return

    # 1. 清洗 OCR 错误文档
    if not args.skip_clean:
        ocr_md_path = get_md_path(OCR_ERROR_DOC)
        if ocr_md_path:
            logger.info(f"\n=== 清洗 OCR 错误文档 ===")
            from clean_ocr_errors import clean_document
            clean_result = clean_document(ocr_md_path, dry_run=False)
            logger.info(f"清洗完成: {clean_result['garbage_rows']} 行乱码已替换")
        else:
            logger.warning(f"OCR 错误文档未找到: {OCR_ERROR_DOC}")

    # 2. 初始化服务
    service = RagService.get_instance()

    # 3. 处理每个文档
    success_count = 0
    fail_count = 0

    logger.info(f"\n=== 开始重新入库 ===")
    logger.info(f"待处理文档: {len(docs)} 个")
    logger.info(f"LLM 矫正: {'开启' if not args.no_llm else '关闭'}")

    for i, doc in enumerate(docs, 1):
        source_name = get_source_name(doc)
        md_path = get_md_path(doc)

        if md_path is None:
            logger.error(f"[{i}/{len(docs)}] FAIL: MD file not found: {source_name}")
            fail_count += 1
            continue

        logger.info(f"\n[{i}/{len(docs)}] Processing: {source_name}")

        try:
            start_time = time.time()
            result = await ingest_document(service, md_path, use_llm=not args.no_llm)
            ingest_time = time.time() - start_time

            if result["status"] == "success":
                logger.info(f"  OK: {result['chunks_added']} chunks, {ingest_time:.1f}s, type={result['doc_type']}")
                success_count += 1
            elif result["status"] == "skipped":
                logger.info(f"  SKIP: {result['message']}")
                success_count += 1
            else:
                logger.error(f"  FAIL: {result['message']}")
                fail_count += 1

        except Exception as e:
            logger.error(f"  ERROR: {e}")
            fail_count += 1

    # 汇总
    logger.info(f"\n{'='*60}")
    logger.info("Processing complete")
    logger.info(f"{'='*60}")
    logger.info(f"Success: {success_count}")
    logger.info(f"Failed: {fail_count}")
    logger.info(f"Total: {len(docs)}")


if __name__ == "__main__":
    asyncio.run(main())