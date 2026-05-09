"""
Event Factory - Create SSE events with consistent structure.

Provides factory functions for creating SSE events to ensure
consistent event structure across the codebase.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


def create_completed_event(session_id: str) -> Dict[str, Any]:
    """Create a completed event."""
    return {
        "type": "completed",
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
    }


def create_error_event(session_id: str, error_message: str) -> Dict[str, Any]:
    """Create an error event."""
    return {
        "type": "error",
        "session_id": session_id,
        "message": error_message,
        "timestamp": datetime.now().isoformat(),
    }


def create_checkpoint_saved_event(
    checkpoint_id: str,
    layer: int,
    phase: str,
    session_id: str,
    is_revision: bool = False,
    revised_dimensions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a checkpoint_saved event."""
    event = {
        "type": "checkpoint_saved",
        "checkpoint_id": checkpoint_id,
        "layer": layer,
        "phase": phase,
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
    }
    if is_revision:
        event["is_revision"] = True
        event["revised_dimensions"] = revised_dimensions or []
    return event


def create_layer_started_event(
    layer: int,
    layer_name: str,
    dimension_count: int,
    session_id: str,
) -> Dict[str, Any]:
    """Create a layer_started event."""
    return {
        "type": "layer_started",
        "layer": layer,
        "layer_name": layer_name,
        "dimension_count": dimension_count,
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
    }


def create_layer_completed_event(
    layer: int,
    phase: str,
    reports: Dict[str, Any],
    pause_after_step: bool,
    previous_layer: int,
    session_id: str,
    knowledge_sources_cache: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Create a layer_completed event."""
    layer_key = f"layer{layer}"
    layer_reports = reports.get(layer_key, {})
    total_chars = sum(len(v) for v in layer_reports.values()) if layer_reports else 0

    return {
        "type": "layer_completed",
        "layer": layer,
        "phase": phase,
        "report_count": len(layer_reports),
        "total_chars": total_chars,
        "pause_after_step": pause_after_step,
        "previous_layer": previous_layer,
        "session_id": session_id,
        "knowledge_sources_cache": knowledge_sources_cache or {},
        "timestamp": datetime.now().isoformat(),
    }


__all__ = [
    "create_completed_event",
    "create_error_event",
    "create_checkpoint_saved_event",
    "create_layer_started_event",
    "create_layer_completed_event",
]