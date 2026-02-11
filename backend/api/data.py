"""
Data API - Simplified Data Access Layer

This API provides access to historical planning data, checkpoints, and layer content.

Endpoints:
- GET /api/data/villages - List all villages
- GET /api/data/villages/{name}/sessions - Get village sessions
- GET /api/data/villages/{name}/layers/{layer} - Get layer content
- GET /api/data/villages/{name}/checkpoints - Get checkpoints
- GET /api/data/villages/{name}/compare/{cp1}/{cp2} - Compare checkpoints
- GET /api/data/villages/{name}/plan - Get combined plan
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.api.tool_manager import tool_manager
from src.utils.paths import get_results_dir

router = APIRouter()
logger = logging.getLogger(__name__)

# Session directory name pattern
SESSION_PATTERN = re.compile(r'\d{8}_\d{6}')

# Layer name mapping
LAYER_MAP = {
    "layer_1_analysis": "layer_1_analysis",
    "layer_2_concept": "layer_2_concept",
    "layer_3_detailed": "layer_3_detailed",
    "analysis": "layer_1_analysis",
    "concept": "layer_2_concept",
    "detailed": "layer_3_detailed",
}


# ============================================
# Helper Functions
# ============================================

def _sanitize_name(name: str) -> str:
    """Sanitize project name for file system"""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def _validate_session_id(session_id: str) -> bool:
    """Validate session ID format (YYYYMMDD_HHMMSS)"""
    return bool(re.match(r'^\d{8}_\d{6}$', session_id))


def _get_layer_dir(layer: str) -> str:
    """Get the actual directory name for a layer identifier"""
    result = LAYER_MAP.get(layer)
    if not result:
        raise ValueError(f"Invalid layer: {layer}")
    return result


def _find_village_directory(
    village_name: str,
    session_id: str | None = None
) -> Path | None:
    """Find village directory (exact match)"""
    safe_name = _sanitize_name(village_name)
    results_dir = get_results_dir()

    village_dir = results_dir / safe_name
    if not village_dir.exists() or not village_dir.is_dir():
        return None

    if session_id:
        if not _validate_session_id(session_id):
            return None
        session_dir = village_dir / session_id
        return session_dir if session_dir.exists() and session_dir.is_dir() else None

    return village_dir


def _read_file_content(file_path: Path) -> str:
    """Read file content with UTF-8 encoding"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")
        return ""


def _scan_session_directory(session_dir: Path) -> dict[str, Any] | None:
    """Scan a session directory and extract metadata"""
    try:
        checkpoint_dir = session_dir / "checkpoints"
        checkpoint_count = 0
        if checkpoint_dir.exists():
            checkpoint_count = len(list(checkpoint_dir.glob("*.json")))

        has_final_report = any(session_dir.glob("final_combined_*.md"))

        return {
            "session_id": session_dir.name,
            "timestamp": session_dir.name,
            "checkpoint_count": checkpoint_count,
            "has_final_report": has_final_report
        }
    except Exception as e:
        logger.warning(f"Failed to scan session {session_dir.name}: {e}")
        return None


def _collect_village_sessions(village_dir: Path) -> list[dict[str, Any]]:
    """Collect all valid sessions from a village directory"""
    sessions = []

    for session_dir in village_dir.iterdir():
        if not session_dir.is_dir():
            continue

        if not SESSION_PATTERN.match(session_dir.name):
            continue

        session_info = _scan_session_directory(session_dir)
        if session_info:
            sessions.append(session_info)

    sessions.sort(key=lambda x: x["timestamp"], reverse=True)
    return sessions


def _read_checkpoint_file(checkpoint_file: Path) -> dict[str, Any] | None:
    """Read a checkpoint file and return its metadata"""
    try:
        data = json.loads(_read_file_content(checkpoint_file))
        return {
            "checkpoint_id": checkpoint_file.stem,
            "description": data.get("description", ""),
            "timestamp": data.get("timestamp", ""),
            "layer": data.get("layer", 1)
        }
    except Exception as e:
        logger.warning(f"Failed to read checkpoint {checkpoint_file}: {e}")
        return None


# ============================================
# API Endpoints
# ============================================

@router.get("/api/data/villages")
async def list_villages():
    """List all villages and their sessions"""
    try:
        results_dir = get_results_dir()

        if not results_dir.exists():
            logger.warning(f"Results directory not found: {results_dir}")
            return {"villages": []}

        villages = []

        for village_dir in sorted(results_dir.iterdir()):
            if not village_dir.is_dir():
                continue

            sessions = _collect_village_sessions(village_dir)

            if sessions:
                villages.append({
                    "name": village_dir.name,
                    "display_name": village_dir.name,
                    "session_count": len(sessions),
                    "sessions": sessions
                })

        logger.info(f"[Data API] Found {len(villages)} villages")
        return {"villages": villages}

    except Exception as e:
        logger.error(f"[Data API] Error listing villages: {e}", exc_info=True)
        return {"villages": []}


@router.get("/api/data/villages/{name}/sessions")
async def get_village_sessions(name: str):
    """Get sessions for a specific village"""
    try:
        village_dir = _find_village_directory(name)
        if not village_dir:
            raise HTTPException(status_code=404, detail=f"Village not found: {name}")

        sessions = _collect_village_sessions(village_dir)
        return {"sessions": sessions}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Data API] Error getting sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get sessions: {str(e)}")


@router.get("/api/data/villages/{name}/layers/{layer}")
async def get_layer_content(
    name: str,
    layer: str,
    session: str | None = Query(None, description="Session ID (YYYYMMDD_HHMMSS)"),
    checkpoint_id: str | None = Query(None, description="Checkpoint ID"),
    format: str = Query("markdown", description="Content format: markdown | html | json")
):
    """Get layer content"""
    try:
        layer_dir_name = _get_layer_dir(layer)
        village_dir = _find_village_directory(name, session)

        if not village_dir:
            raise HTTPException(status_code=404, detail=f"Village/session not found: {name}")

        layer_dir = village_dir / layer_dir_name

        if not layer_dir.exists():
            checkpoint_dir = village_dir / "checkpoints"

            if checkpoint_dir.exists():
                checkpoint_files = list(checkpoint_dir.glob("checkpoint_*.json"))

                if checkpoint_files:
                    latest_checkpoint = max(checkpoint_files, key=lambda p: p.stat().st_mtime)
                    checkpoint_id = latest_checkpoint.stem

                    try:
                        checkpoint_data = json.loads(_read_file_content(latest_checkpoint))
                        state = checkpoint_data.get("state", {})

                        layer_to_key_map = {
                            "layer_1_analysis": "analysis_report",
                            "layer_2_concept": "planning_concept",
                            "layer_3_detailed": "detailed_plan"
                        }
                        content_key = layer_to_key_map.get(layer, f"{layer_dir_name}_result")

                        if content_key in state:
                            content = state[content_key]
                            if isinstance(content, dict):
                                content = content.get("content", str(content))
                            return {
                                "layer": layer,
                                "content": content,
                                "checkpoint_id": checkpoint_id,
                                "timestamp": checkpoint_data.get("timestamp", "")
                            }
                    except Exception as e:
                        logger.error(f"[Data API] Failed to load checkpoint {checkpoint_id}: {e}")

            raise HTTPException(status_code=404, detail=f"Layer content not found: {layer}")

        content_parts = []
        for md_file in sorted(layer_dir.glob("*.md")):
            content_parts.append(_read_file_content(md_file))

        content = "\n\n---\n\n".join(content_parts)

        if not content:
            raise HTTPException(status_code=404, detail=f"No content found for layer: {layer}")

        return {
            "layer": layer,
            "content": content,
            "session": session,
            "timestamp": datetime.fromtimestamp(layer_dir.stat().st_mtime).isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Data API] Error getting layer content: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get layer content: {str(e)}")


@router.get("/api/data/villages/{name}/checkpoints")
async def get_checkpoints(
    name: str,
    session: str | None = Query(None, description="Session ID (YYYYMMDD_HHMMSS format)")
):
    """Get checkpoints for a village"""
    try:
        if session and not _validate_session_id(session):
            raise HTTPException(status_code=400, detail="Invalid session ID format")

        checkpoint_tool = tool_manager.get_checkpoint_tool(name)

        if session:
            session_dir = _find_village_directory(name, session)
            if not session_dir:
                raise HTTPException(status_code=404, detail=f"Session not found: {session}")

            checkpoint_dir = session_dir / "checkpoints"
            if checkpoint_dir.exists():
                checkpoints = [
                    cp for cp in (
                        _read_checkpoint_file(cp_file)
                        for cp_file in sorted(checkpoint_dir.glob("checkpoint_*.json"), reverse=True)
                    ) if cp is not None
                ]

                return {
                    "project_name": name,
                    "session": session,
                    "checkpoints": checkpoints,
                    "count": len(checkpoints)
                }

        list_result = checkpoint_tool.list(include_all=True)

        if not list_result.get("success"):
            return {
                "project_name": name,
                "checkpoints": [],
                "error": list_result.get("error", "Unknown error")
            }

        return {
            "project_name": name,
            "checkpoints": list_result.get("checkpoints", []),
            "count": list_result.get("count", 0)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Data API] Error getting checkpoints: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get checkpoints: {str(e)}")


@router.get("/api/data/villages/{name}/compare/{cp1}/{cp2}")
async def compare_checkpoints(name: str, cp1: str, cp2: str):
    """Compare two checkpoints"""
    try:
        checkpoint_tool = tool_manager.get_checkpoint_tool(name)

        load1 = checkpoint_tool.load(cp1)
        load2 = checkpoint_tool.load(cp2)

        if not load1.get("success"):
            raise HTTPException(status_code=404, detail=f"Checkpoint not found: {cp1}")
        if not load2.get("success"):
            raise HTTPException(status_code=404, detail=f"Checkpoint not found: {cp2}")

        state1 = load1.get("state", {})
        state2 = load2.get("state", {})

        differences = []
        layer_keys = ["layer_1_completed", "layer_2_completed", "layer_3_completed"]
        for key in layer_keys:
            val1 = state1.get(key, False)
            val2 = state2.get(key, False)
            if val1 != val2:
                differences.append(f"{key}: {val1} -> {val2}")

        current_layer1 = state1.get("current_layer", 0)
        current_layer2 = state2.get("current_layer", 0)
        if current_layer1 != current_layer2:
            differences.append(f"current_layer: {current_layer1} -> {current_layer2}")

        summary = f"Layer {current_layer1} -> Layer {current_layer2}"
        if differences:
            summary += f"\nChanges: {', '.join(differences)}"

        return {
            "checkpoint_1": cp1,
            "checkpoint_2": cp2,
            "diff": "\n".join(differences) if differences else "No differences",
            "summary": summary
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Data API] Error comparing checkpoints: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to compare checkpoints: {str(e)}")


@router.get("/api/data/villages/{name}/plan")
async def get_combined_plan(
    name: str,
    session: str | None = Query(None, description="Session ID"),
    format: str = Query("markdown", description="Content format: markdown | html | pdf")
):
    """Get combined planning report"""
    try:
        village_dir = _find_village_directory(name, session)

        if not village_dir:
            raise HTTPException(status_code=404, detail=f"Village/session not found: {name}")

        final_reports = list(village_dir.glob("final_combined_*.md"))

        if final_reports:
            latest_report = max(final_reports, key=lambda p: p.stat().st_mtime)
            content = _read_file_content(latest_report)
            return {
                "content": content,
                "format": format,
                "session": session,
                "source": "final_combined"
            }

        layers = ["layer_1_analysis", "layer_2_concept", "layer_3_detailed"]
        content_parts = []

        for layer in layers:
            layer_dir = village_dir / layer
            if layer_dir.exists():
                for md_file in sorted(layer_dir.glob("*.md")):
                    content_parts.append(f"# {layer.replace('_', ' ').title()}\n\n")
                    content_parts.append(_read_file_content(md_file))
                    content_parts.append("\n\n---\n\n")

        if not content_parts:
            raise HTTPException(status_code=404, detail="No plan content found")

        return {
            "content": "".join(content_parts),
            "format": format,
            "session": session,
            "source": "combined_layers"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Data API] Error getting combined plan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get combined plan: {str(e)}")


# ============================================
# Legacy Compatibility Endpoints
# ============================================

@router.get("/api/villages")
async def list_villages_legacy():
    """Legacy endpoint for backward compatibility"""
    return await list_villages()


@router.get("/api/villages/{name}")
async def get_village_legacy(name: str):
    """Legacy endpoint for backward compatibility"""
    sessions_result = await get_village_sessions(name)
    return {
        "name": name,
        "display_name": name,
        **sessions_result
    }


@router.get("/api/villages/{name}/layers/{layer}")
async def get_layer_legacy(name: str, layer: str):
    """Legacy endpoint for backward compatibility"""
    return await get_layer_content(name, layer)


__all__ = ["router"]
