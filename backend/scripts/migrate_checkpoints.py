"""
Migration script: JSON checkpoints to SQLite
迁移脚本：将 JSON 检查点迁移到 SQLite

This script scans the results/ directory for JSON checkpoint files
and migrates them to the SQLite database.
"""

import json
import re
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.database import init_db, create_checkpoint
from src.utils.logger import get_logger
from src.utils.paths import get_project_root

logger = get_logger(__name__)


def sanitize_name(name: str) -> str:
    """清理文件名（移除不安全字符）"""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def scan_checkpoints(results_dir: Path) -> list[dict]:
    """
    Scan results directory for JSON checkpoint files

    Args:
        results_dir: Path to results directory

    Returns:
        List of checkpoint data dictionaries
    """
    checkpoints = []

    try:
        if not results_dir.exists():
            logger.warning(f"Results directory not found: {results_dir}")
            return checkpoints

        # Iterate through project directories
        for project_dir in sorted(results_dir.iterdir()):
            if not project_dir.is_dir():
                continue

            project_name = project_dir.name

            # Iterate through session directories
            for session_dir in sorted(project_dir.iterdir()):
                if not session_dir.is_dir():
                    continue

                # Look for checkpoints directory
                checkpoint_dir = session_dir / "checkpoints"
                if not checkpoint_dir.exists():
                    continue

                # Extract timestamp (session_id)
                timestamp = session_dir.name

                # Scan JSON files
                for json_file in sorted(checkpoint_dir.glob("*.json")):
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                        checkpoints.append({
                            "project_name": project_name,
                            "timestamp": timestamp,
                            "checkpoint_id": data.get("checkpoint_id"),
                            "state": data.get("state", {}),
                            "metadata": data.get("metadata", {}),
                            "file_path": str(json_file)
                        })

                    except Exception as e:
                        logger.warning(f"Failed to read checkpoint file {json_file}: {e}")

        logger.info(f"Found {len(checkpoints)} checkpoint files")
        return checkpoints

    except Exception as e:
        logger.error(f"Failed to scan checkpoints: {e}", exc_info=True)
        return checkpoints


def migrate_checkpoints(checkpoints: list[dict], dry_run: bool = False) -> dict:
    """
    Migrate checkpoints to SQLite database

    Args:
        checkpoints: List of checkpoint data
        dry_run: If True, don't actually write to database

    Returns:
        Migration statistics
    """
    stats = {
        "total": len(checkpoints),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "errors": []
    }

    for cp in checkpoints:
        try:
            checkpoint_id = cp["checkpoint_id"]

            if not checkpoint_id:
                stats["skipped"] += 1
                logger.warning(f"Skipping checkpoint without ID: {cp['file_path']}")
                continue

            if dry_run:
                logger.info(f"[DRY RUN] Would migrate: {checkpoint_id}")
                stats["success"] += 1
                continue

            # Create checkpoint in database
            success = create_checkpoint(
                project_name=cp["project_name"],
                timestamp=cp["timestamp"],
                checkpoint_id=checkpoint_id,
                state=cp["state"],
                metadata=cp["metadata"]
            )

            if success:
                stats["success"] += 1
                logger.info(f"Migrated: {checkpoint_id}")
            else:
                stats["failed"] += 1
                stats["errors"].append(f"Failed to migrate: {checkpoint_id}")
                logger.error(f"Failed to migrate: {checkpoint_id}")

        except Exception as e:
            stats["failed"] += 1
            stats["errors"].append(f"{cp.get('checkpoint_id', 'unknown')}: {str(e)}")
            logger.error(f"Failed to migrate checkpoint {cp.get('checkpoint_id')}: {e}")

    return stats


def main():
    """Main migration function"""
    print("=" * 60)
    print("Checkpoint Migration: JSON → SQLite")
    print("=" * 60)

    # Initialize database
    print("\n1. Initializing database...")
    if not init_db():
        print("❌ Failed to initialize database")
        return

    print("✅ Database initialized")

    # Get results directory
    results_dir = get_project_root() / "results"
    print(f"\n2. Scanning checkpoints in: {results_dir}")

    # Scan for checkpoints
    checkpoints = scan_checkpoints(results_dir)
    print(f"✅ Found {len(checkpoints)} checkpoint files")

    if not checkpoints:
        print("\nNo checkpoints to migrate. Done.")
        return

    # Show sample
    print("\n3. Sample checkpoints:")
    for i, cp in enumerate(checkpoints[:3]):
        print(f"   - {cp['checkpoint_id']} ({cp['project_name']}/{cp['timestamp']})")

    if len(checkpoints) > 3:
        print(f"   ... and {len(checkpoints) - 3} more")

    # Confirm migration
    print("\n4. Starting migration...")
    stats = migrate_checkpoints(checkpoints, dry_run=False)

    # Print results
    print("\n" + "=" * 60)
    print("Migration Results")
    print("=" * 60)
    print(f"Total:    {stats['total']}")
    print(f"Success:  {stats['success']}")
    print(f"Failed:   {stats['failed']}")
    print(f"Skipped:  {stats['skipped']}")

    if stats["errors"]:
        print("\nErrors:")
        for error in stats["errors"][:10]:
            print(f"  - {error}")
        if len(stats["errors"]) > 10:
            print(f"  ... and {len(stats['errors']) - 10} more errors")

    print("\n✅ Migration complete!")


if __name__ == "__main__":
    main()
