"""
Quick validation script for database implementation
数据库实现快速验证脚本
"""

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
            init_db,
            PlanningSession,
            Checkpoint,
            UISession,
            UIMessage,
            create_planning_session,
            get_planning_session,
            update_planning_session,
            delete_planning_session,
            list_planning_sessions,
            create_checkpoint,
            get_checkpoint,
            list_checkpoints,
            delete_checkpoint,
            create_ui_session,
            get_ui_session,
            update_ui_session,
            delete_ui_session,
            list_ui_sessions,
            create_ui_message,
            get_ui_messages,
            delete_ui_messages,
        )
        print("  ✓ All imports successful")
        return True
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        return False


def validate_database_init():
    """Validate database initialization"""
    print("\nValidating database initialization...")

    try:
        from backend.database import init_db, get_db_path

        if init_db():
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


def validate_crud_operations():
    """Validate basic CRUD operations"""
    print("\nValidating CRUD operations...")

    try:
        from backend.database import (
            create_planning_session,
            get_planning_session,
            delete_planning_session
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

        result = create_planning_session(state)
        print(f"  ✓ Created session: {result}")

        # Test Read
        session = get_planning_session(session_id)
        if session and session["project_name"] == "验证测试":
            print(f"  ✓ Retrieved session: {session['project_name']}")
        else:
            print("  ✗ Failed to retrieve session")
            return False

        # Test Delete
        if delete_planning_session(session_id):
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


def validate_checkpoint_operations():
    """Validate checkpoint operations"""
    print("\nValidating checkpoint operations...")

    try:
        from backend.database import (
            create_checkpoint,
            get_checkpoint,
            delete_checkpoint
        )

        # Test Create
        checkpoint_id = "validation_checkpoint_001"
        success = create_checkpoint(
            project_name="验证测试",
            timestamp="test_session",
            checkpoint_id=checkpoint_id,
            state={"test": "data"},
            metadata={"layer": 1}
        )

        if success:
            print(f"  ✓ Created checkpoint: {checkpoint_id}")
        else:
            print("  ✗ Failed to create checkpoint")
            return False

        # Test Read
        checkpoint = get_checkpoint(checkpoint_id)
        if checkpoint and checkpoint["layer"] == 1:
            print(f"  ✓ Retrieved checkpoint: layer {checkpoint['layer']}")
        else:
            print("  ✗ Failed to retrieve checkpoint")
            return False

        # Test Delete
        if delete_checkpoint(checkpoint_id):
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


def main():
    """Run all validations"""
    print("=" * 60)
    print("Database Implementation Validation")
    print("=" * 60)

    results = []

    # Run validations
    results.append(("Imports", validate_imports()))
    results.append(("Database Init", validate_database_init()))
    results.append(("CRUD Operations", validate_crud_operations()))
    results.append(("Checkpoint Operations", validate_checkpoint_operations()))

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
    sys.exit(main())
