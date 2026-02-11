"""
Database Integration Tests
数据库集成测试

Test suite for SQLite + SQLModel persistence layer.
"""

import sys
from pathlib import Path

# Add parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime
from backend.database import (
    init_db,
    # Planning sessions
    create_planning_session,
    get_planning_session,
    update_planning_session,
    delete_planning_session,
    list_planning_sessions,
    update_session_state,
    add_session_event,
    get_session_events,
    # Checkpoints
    create_checkpoint,
    get_checkpoint,
    list_checkpoints,
    delete_checkpoint,
    # UI sessions
    create_ui_session,
    get_ui_session,
    update_ui_session,
    delete_ui_session,
    list_ui_sessions,
    # UI messages
    create_ui_message,
    get_ui_messages,
    delete_ui_messages,
)


def test_planning_sessions():
    """Test planning session CRUD operations"""
    print("\n" + "=" * 60)
    print("Testing Planning Session CRUD")
    print("=" * 60)

    # Test data
    session_id = "test_session_001"
    state = {
        "session_id": session_id,
        "project_name": "测试村庄",
        "village_data": "测试村庄数据",
        "task_description": "制定村庄总体规划方案",
        "constraints": "无特殊约束",
        "current_layer": 1,
        "previous_layer": 1,
        "layer_1_completed": False,
        "layer_2_completed": False,
        "layer_3_completed": False,
        "need_human_review": False,
        "step_mode": True,
        "output_path": "/test/path",
        "status": "running",
    }

    # Create
    print("\n1. Creating session...")
    result = create_planning_session(state)
    assert result == session_id, "Session ID mismatch"
    print(f"   ✓ Created: {result}")

    # Read
    print("\n2. Reading session...")
    session = get_planning_session(session_id)
    assert session is not None, "Session not found"
    assert session["project_name"] == "测试村庄", "Project name mismatch"
    print(f"   ✓ Read: {session['project_name']}")

    # Update
    print("\n3. Updating session...")
    success = update_planning_session(session_id, {
        "current_layer": 2,
        "layer_1_completed": True
    })
    assert success, "Update failed"
    session = get_planning_session(session_id)
    assert session["current_layer"] == 2, "Current layer not updated"
    assert session["layer_1_completed"] == True, "Layer 1 completion not updated"
    print(f"   ✓ Updated: layer={session['current_layer']}")

    # Add event
    print("\n4. Adding event...")
    event = {
        "type": "test_event",
        "message": "Test event message",
        "timestamp": datetime.now().isoformat()
    }
    success = add_session_event(session_id, event)
    assert success, "Failed to add event"
    events = get_session_events(session_id)
    assert len(events) > 0, "No events found"
    print(f"   ✓ Event added: {len(events)} total events")

    # List
    print("\n5. Listing sessions...")
    sessions = list_planning_sessions(project_name="测试村庄")
    assert len(sessions) > 0, "No sessions found"
    print(f"   ✓ Found {len(sessions)} session(s)")

    # Cleanup
    print("\n6. Deleting session...")
    delete_planning_session(session_id)
    session = get_planning_session(session_id)
    assert session is None, "Session still exists after delete"
    print(f"   ✓ Deleted")

    print("\n✅ Planning session tests passed!")


def test_checkpoints():
    """Test checkpoint CRUD operations"""
    print("\n" + "=" * 60)
    print("Testing Checkpoint CRUD")
    print("=" * 60)

    # Test data
    checkpoint_id = "test_checkpoint_001"
    session_id = "test_session_002"
    state = {"test": "data", "layer": 1}
    metadata = {
        "layer": 1,
        "description": "Test checkpoint"
    }

    # Create
    print("\n1. Creating checkpoint...")
    success = create_checkpoint(
        project_name="测试村庄",
        timestamp=session_id,
        checkpoint_id=checkpoint_id,
        state=state,
        metadata=metadata
    )
    assert success, "Failed to create checkpoint"
    print(f"   ✓ Created: {checkpoint_id}")

    # Read
    print("\n2. Reading checkpoint...")
    checkpoint = get_checkpoint(checkpoint_id)
    assert checkpoint is not None, "Checkpoint not found"
    assert checkpoint["layer"] == 1, "Layer mismatch"
    print(f"   ✓ Read: layer={checkpoint['layer']}")

    # List
    print("\n3. Listing checkpoints...")
    checkpoints = list_checkpoints(session_id=session_id)
    assert len(checkpoints) > 0, "No checkpoints found"
    print(f"   ✓ Found {len(checkpoints)} checkpoint(s)")

    # Cleanup
    print("\n4. Deleting checkpoint...")
    delete_checkpoint(checkpoint_id)
    checkpoint = get_checkpoint(checkpoint_id)
    assert checkpoint is None, "Checkpoint still exists after delete"
    print(f"   ✓ Deleted")

    print("\n✅ Checkpoint tests passed!")


def test_ui_sessions():
    """Test UI session CRUD operations"""
    print("\n" + "=" * 60)
    print("Testing UI Session CRUD")
    print("=" * 60)

    # Test data
    conversation_id = "test_conversation_001"

    # Create
    print("\n1. Creating UI session...")
    result = create_ui_session(conversation_id, "conversation")
    assert result == conversation_id, "Conversation ID mismatch"
    print(f"   ✓ Created: {result}")

    # Read
    print("\n2. Reading UI session...")
    session = get_ui_session(conversation_id)
    assert session is not None, "Session not found"
    assert session["status"] == "idle", "Status mismatch"
    print(f"   ✓ Read: status={session['status']}")

    # Update
    print("\n3. Updating UI session...")
    success = update_ui_session(conversation_id, {
        "status": "planning",
        "project_name": "测试项目"
    })
    assert success, "Update failed"
    session = get_ui_session(conversation_id)
    assert session["status"] == "planning", "Status not updated"
    print(f"   ✓ Updated: status={session['status']}")

    # Add messages
    print("\n4. Adding messages...")
    create_ui_message(
        session_id=conversation_id,
        role="user",
        content="测试消息"
    )
    create_ui_message(
        session_id=conversation_id,
        role="assistant",
        content="回复消息"
    )
    messages = get_ui_messages(conversation_id)
    assert len(messages) == 2, "Message count mismatch"
    print(f"   ✓ Added {len(messages)} messages")

    # List
    print("\n5. Listing UI sessions...")
    sessions = list_ui_sessions(status="planning")
    assert len(sessions) > 0, "No sessions found"
    print(f"   ✓ Found {len(sessions)} session(s)")

    # Cleanup
    print("\n6. Deleting UI session...")
    delete_ui_messages(conversation_id)
    delete_ui_session(conversation_id)
    session = get_ui_session(conversation_id)
    assert session is None, "Session still exists after delete"
    print(f"   ✓ Deleted")

    print("\n✅ UI session tests passed!")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Database Integration Test Suite")
    print("=" * 60)

    # Initialize database
    print("\nInitializing database...")
    if not init_db():
        print("❌ Failed to initialize database")
        return
    print("✅ Database initialized")

    # Run tests
    try:
        test_planning_sessions()
        test_checkpoints()
        test_ui_sessions()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
