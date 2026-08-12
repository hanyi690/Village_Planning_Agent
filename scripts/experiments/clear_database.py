"""Database clearing utility - clear all data except specified sessions.

Usage:
    python scripts/experiments/run.py clear --keep baseline_e0f06d60
    python scripts/experiments/clear_database.py --keep baseline_e0f06d60

Database Tables:
    - planning_sessions: 规划会话元数据 (project_name, village_name, created_at)
    - dimension_reports: 维度报告内容 (session_id, dimension_key, layer, content)
    - dimension_revisions: 维度修订记录 (session_id, dimension_key, revision_number)
    - ui_sessions: UI 会话状态 (conversation_id, task_id)
    - checkpoints: LangGraph 检查点 (thread_id = session_id)
    - writes: LangGraph 写入记录 (thread_id = session_id)

Note:
    - session_id 在 dimension_reports 表中存储
    - thread_id 在 checkpoints/writes 表中存储，值与 session_id 相同
    - 清理时需要同时清理这两个标识符
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project roots on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlmodel import select, delete

from backend.app.database.engine import get_async_session
from backend.app.database.models import PlanningSession, DimensionReport, DimensionRevision, UISession

logger = logging.getLogger(__name__)


async def clear_all_except(keep_session_ids: List[str]) -> Dict[str, int]:
    """Clear all database data except specified sessions.

    Args:
        keep_session_ids: List of session_ids to preserve

    Returns:
        Dict with deletion counts for each table
    """
    counts = {
        "planning_sessions": 0,
        "dimension_reports": 0,
        "dimension_revisions": 0,
        "ui_sessions": 0,
        "checkpoints": 0,
        "cache_files": 0,
    }

    async with get_async_session() as db:
        # 1. Delete DimensionReport records (not in keep list)
        stmt = delete(DimensionReport).where(
            DimensionReport.session_id.not_in(keep_session_ids)
        )
        result = await db.execute(stmt)
        counts["dimension_reports"] = result.rowcount

        # 2. Delete DimensionRevision records (linked to deleted sessions)
        stmt = delete(DimensionRevision).where(
            DimensionRevision.session_id.not_in(keep_session_ids)
        )
        result = await db.execute(stmt)
        counts["dimension_revisions"] = result.rowcount

        # 3. Delete PlanningSession records (not in keep list)
        stmt = delete(PlanningSession).where(
            PlanningSession.session_id.not_in(keep_session_ids)
        )
        result = await db.execute(stmt)
        counts["planning_sessions"] = result.rowcount

        # 4. Delete UISession records (task_id linked to deleted sessions)
        # Note: UISession uses conversation_id as PK, task_id links to planning session
        stmt = delete(UISession)
        result = await db.execute(stmt)
        counts["ui_sessions"] = result.rowcount

        # 5. Clear LangGraph checkpoints for deleted sessions
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            from backend.app.core.settings import DATABASE_DIR

            db_path = DATABASE_DIR / "checkpoints.db"
            if db_path.exists():
                async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
                    # Get all thread_ids (session_ids) from checkpoints
                    # Note: LangGraph stores checkpoints by thread_id
                    for session_id in await _get_all_checkpoint_thread_ids():
                        if session_id not in keep_session_ids:
                            try:
                                # Delete all checkpoints for this thread
                                await saver.adelete(session_id)
                                counts["checkpoints"] += 1
                            except Exception as e:
                                logger.warning(f"Failed to delete checkpoint {session_id}: {e}")
        except Exception as e:
            logger.warning(f"Failed to clear checkpoints: {e}")

        await db.commit()

    # 6. Clear file cache (except baseline cache)
    cache_dir = _PROJECT_ROOT / "output" / "experiments" / "cache"
    if cache_dir.exists():
        for cache_file in cache_dir.glob("*.json"):
            # Keep baseline cache files
            if any(kid in cache_file.name for kid in keep_session_ids):
                continue
            # Keep baseline_jintian cache
            if "baseline_jintian" in cache_file.name:
                continue
            try:
                cache_file.unlink()
                counts["cache_files"] += 1
            except Exception as e:
                logger.warning(f"Failed to delete cache file {cache_file}: {e}")

    logger.info("[Clear] Deletion counts: %s", counts)
    return counts


async def _get_all_checkpoint_thread_ids() -> List[str]:
    """Get all thread_ids (session_ids) from LangGraph checkpoints table."""
    import aiosqlite
    from backend.app.core.settings import DATABASE_DIR

    db_path = DATABASE_DIR / "checkpoints.db"
    if not db_path.exists():
        return []

    thread_ids = set()
    async with aiosqlite.connect(str(db_path)) as db:
        try:
            async with db.execute("SELECT DISTINCT thread_id FROM checkpoints") as cursor:
                async for row in cursor:
                    if row[0]:
                        thread_ids.add(row[0])
        except Exception as e:
            logger.warning(f"Failed to query checkpoints: {e}")

    return list(thread_ids)


async def list_all_sessions() -> List[Dict[str, str]]:
    """List all sessions in the database."""
    sessions = []
    async with get_async_session() as db:
        stmt = select(PlanningSession)
        result = await db.execute(stmt)
        for session in result.scalars().all():
            sessions.append({
                "session_id": session.session_id,
                "project_name": session.project_name,
                "village_name": session.village_name,
                "created_at": session.created_at.isoformat() if session.created_at else None,
            })
    return sessions


async def main():
    parser = argparse.ArgumentParser(description="Clear database except specified sessions")
    parser.add_argument(
        "--keep",
        default="baseline_e0f06d60",
        help="Comma-separated session_ids to keep (default: baseline_e0f06d60)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all sessions without deleting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.list:
        sessions = await list_all_sessions()
        print(f"\nFound {len(sessions)} sessions:")
        for s in sessions:
            print(f"  - {s['session_id']}: {s['project_name']} ({s['village_name']})")
        return

    keep_ids = [s.strip() for s in args.keep.split(",")]

    if args.dry_run:
        sessions = await list_all_sessions()
        to_delete = [s for s in sessions if s["session_id"] not in keep_ids]
        print(f"\nWould delete {len(to_delete)} sessions:")
        for s in to_delete:
            print(f"  - {s['session_id']}: {s['project_name']}")
        print(f"\nWould keep {len(keep_ids)} sessions: {keep_ids}")
        return

    print(f"Clearing database, keeping: {keep_ids}")
    result = await clear_all_except(keep_ids)
    print(f"\nDeletion summary:")
    for table, count in result.items():
        print(f"  - {table}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
