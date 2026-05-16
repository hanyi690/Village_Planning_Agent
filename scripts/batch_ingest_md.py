#!/usr/bin/env python3
"""
批量入库 Markdown 文件到 RAG 向量库

使用方法：
    python scripts/batch_ingest_md.py [--limit N] [--dry-run] [--retry-failed] [--dir "子目录名"]
"""

import argparse
import asyncio
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List

# 添加 backend 到路径
backend_path = Path(__file__).parent.parent / "backend"
import sys
sys.path.insert(0, str(backend_path))

from app.services.modules.rag.service import RagService
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 路径配置
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MD_DIR = PROJECT_ROOT / "data" / "RAG_doc" / "_doc_md"
STATE_FILE = PROJECT_ROOT / "data" / "RAG_doc" / "_cache" / "ingest_state.json"


class IngestState:
    """入库状态管理"""

    def __init__(self):
        self.state = self._load()
        self._sync_with_chromadb()

    def _load(self) -> Dict:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {"version": "1.0", "files": {}, "stats": {}}

    def _sync_with_chromadb(self):
        """从 ChromaDB 同步已入库的文档状态"""
        try:
            import chromadb
            from app.core.settings import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME

            client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
            collection = client.get_collection(name=CHROMA_COLLECTION_NAME)

            results = collection.get(include=["metadatas"])
            existing_sources = set()
            for m in results.get("metadatas", []):
                if "source" in m:
                    existing_sources.add(m["source"])

            # 同步状态
            for source in existing_sources:
                file_path = str(MD_DIR / source)
                if file_path not in self.state["files"]:
                    self.state["files"][file_path] = {
                        "status": "completed",
                        "synced_from": "chromadb",
                        "updated_at": datetime.now().isoformat(),
                    }

            if existing_sources:
                logger.info(f"从 ChromaDB 同步 {len(existing_sources)} 个已入库文档")
                self._update_stats()
        except Exception as e:
            logger.warning(f"同步 ChromaDB 状态失败: {e}")

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.state["updated_at"] = datetime.now().isoformat()
        STATE_FILE.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_status(self, file_path: str) -> str:
        return self.state["files"].get(file_path, {}).get("status", "pending")

    def set_status(self, file_path: str, status: str, **kwargs):
        if file_path not in self.state["files"]:
            self.state["files"][file_path] = {}
        self.state["files"][file_path].update(
            {"status": status, "updated_at": datetime.now().isoformat(), **kwargs}
        )
        self._update_stats()

    def _update_stats(self):
        stats = {"total": len(self.state["files"]), "completed": 0, "failed": 0, "pending": 0}
        for f in self.state["files"].values():
            s = f.get("status", "pending")
            if s in stats:
                stats[s] += 1
        self.state["stats"] = stats


def get_md_files(md_dir: Path, subdir: str = None) -> List[Path]:
    """获取 Markdown 文件列表"""
    if subdir:
        search_dir = md_dir / subdir
    else:
        search_dir = md_dir

    if not search_dir.exists():
        logger.error(f"目录不存在: {search_dir}")
        return []

    return sorted(search_dir.rglob("*.md"))


async def ingest_file(service: RagService, md_path: Path) -> Dict:
    """入库单个文件"""
    file_path = str(md_path)

    result = await service.add_markdown_document(
        file_path=file_path,
        use_llm_inference=False,  # 不使用 LLM推断文档类型，加快速度
    )

    return {
        "status": result.get("status"),
        "chunks_added": result.get("chunks_added", 0),
        "message": result.get("message", ""),
    }


async def main():
    parser = argparse.ArgumentParser(description="批量入库 Markdown 文件")
    parser.add_argument("--limit", type=int, default=0, help="限制处理数量（0=全部）")
    parser.add_argument("--dry-run", action="store_true", help="仅列出文件，不入库")
    parser.add_argument("--retry-failed", action="store_true", help="重试失败的文件")
    parser.add_argument("--dir", type=str, default=None, help="指定子目录")
    parser.add_argument("--reset", action="store_true", help="清空状态文件，重新开始")
    args = parser.parse_args()

    # 初始化
    state = IngestState()
    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        state = IngestState()
        logger.info("已清空状态文件")

    service = RagService.get_instance()

    # 获取文件列表
    files = get_md_files(MD_DIR, args.dir)
    logger.info(f"找到 {len(files)} 个 Markdown 文件")

    if args.limit > 0:
        files = files[: args.limit]
        logger.info(f"限制处理前 {args.limit} 个文件")

    if args.dry_run:
        logger.info("=== 文件列表 ===")
        for i, f in enumerate(files, 1):
            status = state.get_status(str(f))
            status_icon = {"completed": "✓", "failed": "✗", "pending": "○"}.get(status, "?")
            logger.info(f"{i:3d}. {status_icon} {f.relative_to(MD_DIR)}")
        return

    # 统计
    success_count = 0
    fail_count = 0
    skip_count = 0

    # 处理每个文件
    for i, md_path in enumerate(files, 1):
        file_path = str(md_path)
        status = state.get_status(file_path)

        # 跳过已完成的文件
        if status == "completed" and not args.retry_failed:
            logger.info(f"[{i}/{len(files)}] 跳过（已完成）: {md_path.name}")
            skip_count += 1
            continue

        # 重试模式只处理失败的文件
        if args.retry_failed and status != "failed":
            continue

        logger.info(f"[{i}/{len(files)}] 入库: {md_path.name}")
        state.set_status(file_path, "ingesting")
        state.save()

        try:
            start_time = time.time()
            result = await ingest_file(service, md_path)
            ingest_time = time.time() - start_time

            if result["status"] == "success":
                state.set_status(
                    file_path,
                    "completed",
                    chunks=result["chunks_added"],
                    time=round(ingest_time, 1),
                )
                logger.info(f"  ✓ 成功: {result['chunks_added']} 切片, {ingest_time:.1f}s")
                success_count += 1
            elif result["status"] == "skipped":
                state.set_status(file_path, "completed", chunks=0, time=0)
                logger.info(f"  ○ 跳过: {result['message']}")
                skip_count += 1
            else:
                state.set_status(file_path, "failed", error=result["message"])
                logger.error(f"  ✗ 失败: {result['message']}")
                fail_count += 1

        except Exception as e:
            state.set_status(file_path, "failed", error=str(e))
            logger.error(f"  ✗ 异常: {e}")
            fail_count += 1

        state.save()

    # 汇总
    logger.info(f"\n{'='*60}")
    logger.info("处理完成")
    logger.info(f"{'='*60}")
    logger.info(f"成功: {success_count}")
    logger.info(f"失败: {fail_count}")
    logger.info(f"跳过: {skip_count}")
    logger.info(f"状态文件: {STATE_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
