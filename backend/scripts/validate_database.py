"""
Quick validation script for database implementation (async)
数据库实现快速验证脚本（异步版本）
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def validate_imports():
    """Validate all imports work"""
    print("Validating imports...")

    try:
        from backend.database import (
            get_session,
            init_async_db,
            PlanningSession,
            Checkpoint,
            UISession,
            UIMessage,
            create_planning_session_async,
            get_planning_session_async,
            update_planning_session_async,
            delete_planning_session_async,
            list_planning_sessions_async,
            create_checkpoint_async,
            get_checkpoint_async,
            list_checkpoints_async,
            delete_checkpoint_async,
            create_ui_session_async,
            get_ui_session_async,
            update_ui_session_async,
            delete_ui_session_async,
            list_ui_sessions_async,
            create_ui_message_async,
            get_ui_messages_async,
            delete_ui_messages_async,
        )
        print("  ✓ All imports successful")
        return True
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        return False


async def validate_database_init():
    """Validate database initialization (async)"""
    print("\nValidating database initialization...")

    try:
        from backend.database import init_async_db, get_db_path

        if await init_async_db():
            db_path = get_db_path()
            print(f"  ✓ Database initialized at: {db_path}")
            return True
        else:
            print("  ✗ Database initialization failed")
            return False
    except Exception as e:
        print(f"  ✗ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def validate_crud_operations():
    """Validate basic CRUD operations (async)"""
    print("\nValidating CRUD operations...")

    try:
        from backend.database import (
            create_planning_session_async,
            get_planning_session_async,
            delete_planning_session_async
        )

        # Test Create
        session_id = "validation_test_001"
        state = {
            "session_id": session_id,
            "project_name": "验证测试",
            "village_data": "测试数据",
            "task_description": "测试任务",
            "current_layer": 1,
            "status": "running",
        }

        result = await create_planning_session_async(state)
        print(f"  ✓ Created session: {result}")

        # Test Read
        session = await get_planning_session_async(session_id)
        if session and session["project_name"] == "验证测试":
            print(f"  ✓ Retrieved session: {session['project_name']}")
        else:
            print("  ✗ Failed to retrieve session")
            return False

        # Test Delete
        if await delete_planning_session_async(session_id):
            print("  ✓ Deleted session")
        else:
            print("  ✗ Failed to delete session")
            return False

        return True

    except Exception as e:
        print(f"  ✗ CRUD validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def validate_checkpoint_operations():
    """Validate checkpoint operations (async)"""
    print("\nValidating checkpoint operations...")

    try:
        from backend.database import (
            create_checkpoint_async,
            get_checkpoint_async,
            delete_checkpoint_async
        )

        # Test Create
        checkpoint_id = "validation_checkpoint_001"
        success = await create_checkpoint_async(
            checkpoint_id=checkpoint_id,
            session_id="test_session",
            layer=1,
            description="Test checkpoint",
            state_snapshot={"test": "data"},
            checkpoint_metadata={"layer": 1}
        )

        if success:
            print(f"  ✓ Created checkpoint: {checkpoint_id}")
        else:
            print("  ✗ Failed to create checkpoint")
            return False

        # Test Read
        checkpoint = await get_checkpoint_async(checkpoint_id)
        if checkpoint and checkpoint["layer"] == 1:
            print(f"  ✓ Retrieved checkpoint: layer {checkpoint['layer']}")
        else:
            print("  ✗ Failed to retrieve checkpoint")
            return False

        # Test Delete
        if await delete_checkpoint_async(checkpoint_id):
            print("  ✓ Deleted checkpoint")
        else:
            print("  ✗ Failed to delete checkpoint")
            return False

        return True

    except Exception as e:
        print(f"  ✗ Checkpoint validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all validations (async)"""
    print("=" * 60)
    print("Database Implementation Validation (Async)")
    print("=" * 60)

    results = []

    # Run validations
    results.append(("Imports", validate_imports()))
    results.append(("Database Init", await validate_database_init()))
    results.append(("CRUD Operations", await validate_crud_operations()))
    results.append(("Checkpoint Operations", await validate_checkpoint_operations()))

    # Print summary
    print("\n" + "=" * 60)
    print("Validation Summary")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 60)

    if all_passed:
        print("\n✅ ALL VALIDATIONS PASSED!")
        print("\nThe database implementation is ready to use.")
        return 0
    else:
        print("\n❌ SOME VALIDATIONS FAILED!")
        print("\nPlease fix the issues above before using the database.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))