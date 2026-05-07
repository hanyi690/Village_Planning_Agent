"""
Export session checkpoint from SQLite database.
直接读取 LangGraph checkpoint 表，无需加载完整环境。

导出每个 layer 完成时的独立 checkpoint：
- Layer1 checkpoint: phase=layer1, L1=12 dimensions
- Layer2 checkpoint: phase=layer2, L2=4 dimensions
- Layer3 checkpoint: phase=layer3, L3=12 dimensions
"""

import asyncio
import json
import msgpack
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Any

# Import dimension metadata helpers
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.config.dimension_metadata import get_dimension_layer

class BytesEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles bytes and other non-serializable types."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, bytes):
            return obj.decode('utf-8', errors='replace')
        return super().default(obj)

# Database path
DB_PATH = Path(__file__).parent.parent.parent / "data" / "village_planning.db"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "experiments" / "cascade_consistency" / "baseline"

# Session ID to export
SESSION_ID = "23bb7190-49cc-4432-91d8-b1e8eee3fbf9"


def find_layer_checkpoints(session_id: str) -> dict:
    """Find checkpoint IDs for each layer completion."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT checkpoint_id, checkpoint
        FROM checkpoints
        WHERE thread_id = ?
        ORDER BY checkpoint_id
    ''', (session_id,))

    rows = cursor.fetchall()

    layer_checkpoints = {
        'layer1': None,
        'layer2': None,
        'layer3': None,
    }

    for row in rows:
        try:
            data = msgpack.unpackb(row['checkpoint'], raw=False)
            channel_values = data.get('channel_values', {})
            phase = channel_values.get('phase', 'unknown')

            completed = channel_values.get('completed_dimensions', {})

            # 处理两种格式
            if isinstance(completed, dict):
                l1_count = len(completed.get('layer1', []))
                l2_count = len(completed.get('layer2', []))
                l3_count = len(completed.get('layer3', []))
            elif isinstance(completed, list):
                # 扁平列表：根据维度所属层级计数
                l1_count = len([d for d in completed if get_dimension_layer(d) == 1])
                l2_count = len([d for d in completed if get_dimension_layer(d) == 2])
                l3_count = len([d for d in completed if get_dimension_layer(d) == 3])

            # Layer1 completion: first checkpoint with L1=12
            if l1_count == 12 and layer_checkpoints['layer1'] is None:
                layer_checkpoints['layer1'] = {
                    'checkpoint_id': row['checkpoint_id'],
                    'state': channel_values,
                    'phase': phase,
                }

            # Layer2 completion: first checkpoint with L2=4
            if l2_count == 4 and layer_checkpoints['layer2'] is None:
                layer_checkpoints['layer2'] = {
                    'checkpoint_id': row['checkpoint_id'],
                    'state': channel_values,
                    'phase': phase,
                }

            # Layer3 completion: first checkpoint with L3=12
            if l3_count == 12 and layer_checkpoints['layer3'] is None:
                layer_checkpoints['layer3'] = {
                    'checkpoint_id': row['checkpoint_id'],
                    'state': channel_values,
                    'phase': phase,
                }

        except Exception as e:
            print(f"[Export] Error parsing checkpoint: {e}")

    conn.close()
    return layer_checkpoints


def sanitize_for_json(obj):
    """Convert bytes and other non-serializable types to JSON-compatible format."""
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    else:
        return obj


def save_layer_checkpoint(layer_key: str, checkpoint_data: dict, output_dir: Path):
    """Save checkpoint data for a specific layer."""
    checkpoint_id = checkpoint_data['checkpoint_id']
    state = checkpoint_data['state']
    phase = checkpoint_data['phase']

    reports = state.get('reports', {})
    completed_dimensions = state.get('completed_dimensions', {})

    layer_reports = reports.get(layer_key, {})
    layer_completed = completed_dimensions.get(layer_key, [])

    # Compute fingerprint
    import hashlib
    state_str = json.dumps(sanitize_for_json(state), sort_keys=True, ensure_ascii=False, cls=BytesEncoder)
    state_fingerprint = hashlib.md5(state_str.encode()).hexdigest()[:16]

    layer_num = int(layer_key.replace('layer', ''))

    # Save layer checkpoint file (for load_layer_checkpoint)
    checkpoint_file_data = {
        "layer": layer_num,
        "checkpoint_id": checkpoint_id,
        "phase": phase,
        "timestamp": datetime.now().isoformat(),
        "state_fingerprint": state_fingerprint,
        "completed_dimensions": sanitize_for_json(layer_completed),
        "success": True,
        "exported_from_db": True,
    }
    with open(output_dir / f"{layer_key}_checkpoint.json", "w", encoding="utf-8") as f:
        json.dump(checkpoint_file_data, f, indent=2, ensure_ascii=False, cls=BytesEncoder)
    print(f"[Export] Saved {layer_key}_checkpoint.json: checkpoint_id={checkpoint_id[:24]}...")

    # Save layer reports file
    layer_data = {
        "layer": layer_num,
        "checkpoint_id": checkpoint_id,
        "phase": phase,
        "state_fingerprint": state_fingerprint,
        "reports": sanitize_for_json(layer_reports),
        "completed_dimensions": sanitize_for_json(layer_completed),
        "report_count": len(layer_reports),
        "total_chars": sum(len(v) for v in layer_reports.values()) if layer_reports else 0,
        "exported_from_db": True,
        "exported_at": datetime.now().isoformat(),
    }

    filename = f"{layer_key}_reports.json"
    with open(output_dir / filename, "w", encoding="utf-8") as f:
        json.dump(layer_data, f, indent=2, ensure_ascii=False, cls=BytesEncoder)
    print(f"[Export] Saved {filename}: {len(layer_reports)} reports")


def save_checkpoints_summary(layer_checkpoints: dict, output_dir: Path, session_id: str):
    """Save checkpoints summary."""
    summary = {
        "session_id": session_id,
        "layer_checkpoints": {},
        "exported_from_db": True,
        "collected_at": datetime.now().isoformat(),
    }

    for layer_key, cp in layer_checkpoints.items():
        if cp:
            # Compute fingerprint for each layer
            import hashlib
            state_str = json.dumps(sanitize_for_json(cp['state']), sort_keys=True, ensure_ascii=False, cls=BytesEncoder)
            state_fingerprint = hashlib.md5(state_str.encode()).hexdigest()[:16]

            summary["layer_checkpoints"][layer_key] = {
                "checkpoint_id": cp['checkpoint_id'],
                "phase": cp['phase'],
                "state_fingerprint": state_fingerprint,
            }

    with open(output_dir / "checkpoints.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, cls=BytesEncoder)
    print(f"[Export] Saved checkpoints.json")


def save_session_metadata(layer_checkpoints: dict, output_dir: Path, session_id: str):
    """Save session metadata."""
    # Use final state for overall metadata
    final_cp = layer_checkpoints.get('layer3') or layer_checkpoints.get('layer2') or layer_checkpoints.get('layer1')
    if not final_cp:
        return

    state = final_cp['state']

    import hashlib
    state_str = json.dumps(sanitize_for_json(state), sort_keys=True, ensure_ascii=False, cls=BytesEncoder)
    state_fingerprint = hashlib.md5(state_str.encode()).hexdigest()[:16]

    session_meta = {
        "session_id": session_id,
        "checkpoint_id": final_cp['checkpoint_id'],
        "project_name": sanitize_for_json(state.get("project_name", "")),
        "phase": state.get("phase", ""),
        "created_at": datetime.now().isoformat(),
        "state_fingerprint": state_fingerprint,
        "exported_from_db": True,
    }

    with open(output_dir / "session_id.json", "w", encoding="utf-8") as f:
        json.dump(session_meta, f, indent=2, ensure_ascii=False, cls=BytesEncoder)
    print(f"[Export] Saved session_id.json")


def main():
    """Main entry point."""
    print("=" * 60)
    print("[Export] Starting database export")
    print(f"[Export] Session ID: {SESSION_ID}")
    print("=" * 60)

    # Find layer checkpoints
    layer_checkpoints = find_layer_checkpoints(SESSION_ID)

    if not any(layer_checkpoints.values()):
        print("[Export] No checkpoints found!")
        return

    print(f"[Export] Found checkpoints:")
    for layer_key, cp in layer_checkpoints.items():
        if cp:
            print(f"  {layer_key}: {cp['checkpoint_id'][:24]}...")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Save each layer checkpoint
    for layer_key, cp in layer_checkpoints.items():
        if cp:
            save_layer_checkpoint(layer_key, cp, OUTPUT_DIR)

    # Save checkpoints summary
    save_checkpoints_summary(layer_checkpoints, OUTPUT_DIR, SESSION_ID)

    # Save session metadata
    save_session_metadata(layer_checkpoints, OUTPUT_DIR, SESSION_ID)

    print("=" * 60)
    print("[Export] Export completed successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()