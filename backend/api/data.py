"""
Data API - Database-Backed Data Access Layer

This API provides access to historical planning data using the database
and LangGraph AsyncSqliteSaver for checkpoints.

Endpoints:
- GET /api/data/villages - List all villages (projects)
- GET /api/data/villages/{name}/sessions - Get village sessions
- GET /api/data/villages/{name}/layers/{layer} - Get layer content
- GET /api/data/villages/{name}/checkpoints - Get checkpoints
- GET /api/data/villages/{name}/compare/{cp1}/{cp2} - Compare checkpoints
- GET /api/data/villages/{name}/plan - Get combined plan
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.database.operations_async import (
    list_projects_async,
    list_planning_sessions_async,
    list_project_sessions_async,
)
from backend.database.engine import get_db_path

router = APIRouter()
logger = logging.getLogger(__name__)

# Layer name mapping
LAYER_MAP = {
    "layer_1_analysis": "layer_1_analysis",
    "layer_2_concept": "layer_2_concept",
    "layer_3_detailed": "layer_3_detailed",
    "analysis": "layer_1_analysis",
    "concept": "layer_2_concept",
    "detailed": "layer_3_detailed",
}

# Layer to state key mapping
LAYER_TO_STATE_KEY = {
    "layer_1_analysis": "analysis_reports",
    "layer_2_concept": "concept_reports",
    "layer_3_detailed": "detail_reports",
    "analysis": "analysis_reports",
    "concept": "concept_reports",
    "detailed": "detail_reports",
}


# ============================================
# Helper Functions
# ============================================

def _get_layer_dir(layer: str) -> str:
    """Get the actual directory name for a layer identifier"""
    result = LAYER_MAP.get(layer)
    if not result:
        raise ValueError(f"Invalid layer: {layer}")
    return result


async def _get_langgraph_checkpointer():
    """Get LangGraph AsyncSqliteSaver instance"""
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    
    conn = await aiosqlite.connect(get_db_path(), check_same_thread=False)
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver, conn


async def _get_session_checkpoints(thread_id: str) -> List[Dict[str, Any]]:
    """Get checkpoints for a session using LangGraph API"""
    from src.orchestration.main_graph import create_village_planning_graph
    
    checkpoints = []
    try:
        saver, conn = await _get_langgraph_checkpointer()
        try:
            graph = create_village_planning_graph(checkpointer=saver)
            config = {"configurable": {"thread_id": thread_id}}

            async for state_snapshot in graph.aget_state_history(config):
                checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
                metadata = state_snapshot.metadata or {}
                values = state_snapshot.values or {}
                
                checkpoints.append({
                    "checkpoint_id": checkpoint_id,
                    "timestamp": metadata.get("write_ts", ""),
                    "layer": values.get("current_layer", 1),
                    "description": f"Layer {values.get('current_layer', 1)} checkpoint"
                })
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"[Data API] Failed to get checkpoints: {e}", exc_info=True)
    
    return checkpoints


async def _get_state_from_checkpoint(thread_id: str, checkpoint_id: str = None) -> Dict[str, Any]:
    """Get state from LangGraph checkpoint"""
    from src.orchestration.main_graph import create_village_planning_graph
    
    try:
        saver, conn = await _get_langgraph_checkpointer()
        try:
            graph = create_village_planning_graph(checkpointer=saver)
            
            config = {"configurable": {"thread_id": thread_id}}
            if checkpoint_id:
                config["configurable"]["checkpoint_id"] = checkpoint_id
            
            state_snapshot = await graph.aget_state(config)
            return state_snapshot.values or {}
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"[Data API] Failed to get state: {e}", exc_info=True)
        return {}


# ============================================
# API Endpoints
# ============================================

@router.get("/api/data/villages")
async def list_villages():
    """List all villages (projects) from database"""
    try:
        # Get projects grouped by project_name
        projects = await list_projects_async()
        
        villages = []
        for project in projects:
            # Get sessions for this project
            logger.info(f"[Data API] Processing project: {project['name']}, session_count: {project.get('session_count', 'N/A')}")
            sessions = await list_project_sessions_async(project["name"], limit=10)
            logger.info(f"[Data API] Found {len(sessions)} sessions for project '{project['name']}'")
            
            village_sessions = []
            for session in sessions:
                village_sessions.append({
                    "session_id": session["session_id"],
                    "timestamp": session["created_at"],
                    "status": session["status"],
                    "has_final_report": session["status"] == "completed",
                    "checkpoint_count": 0  # TODO: 从 LangGraph checkpoint 获取实际数量
                })
            
            villages.append({
                "name": project["name"],
                "display_name": project["name"],
                "session_count": project["session_count"],
                "sessions": village_sessions
            })
        
        logger.info(f"[Data API] Found {len(villages)} villages from database")
        return {"villages": villages}

    except Exception as e:
        logger.error(f"[Data API] Error listing villages: {e}", exc_info=True)
        return {"villages": []}


@router.get("/api/data/villages/{name}/sessions")
async def get_village_sessions(name: str):
    """Get sessions for a specific village from database"""
    try:
        sessions = await list_project_sessions_async(name)
        
        if not sessions:
            raise HTTPException(status_code=404, detail=f"Village not found: {name}")
        
        result_sessions = []
        for session in sessions:
            result_sessions.append({
                "session_id": session["session_id"],
                "timestamp": session["created_at"],
                "status": session["status"],
                "has_final_report": session["status"] == "completed"
            })
        
        return {"sessions": result_sessions}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Data API] Error getting sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get sessions: {str(e)}")


@router.get("/api/data/villages/{name}/layers/{layer}")
async def get_layer_content(
    name: str,
    layer: str,
    session: str | None = Query(None, description="Session ID"),
    checkpoint_id: str | None = Query(None, description="Checkpoint ID"),
    format: str = Query("markdown", description="Content format: markdown | html | json")
):
    """Get layer content from LangGraph checkpoint state"""
    try:
        layer_dir_name = _get_layer_dir(layer)
        content_key = LAYER_TO_STATE_KEY.get(layer, f"{layer_dir_name}_reports")
        
        # Get session_id if not provided
        if not session:
            sessions = await list_project_sessions_async(name, limit=1)
            if not sessions:
                raise HTTPException(status_code=404, detail=f"No sessions found for: {name}")
            session = sessions[0]["session_id"]
        
        # Get state from checkpoint
        state = await _get_state_from_checkpoint(session, checkpoint_id)
        
        if not state:
            raise HTTPException(status_code=404, detail=f"State not found for session: {session}")
        
        # Extract layer content
        content = ""
        
        # Try to get reports dict first
        reports = state.get(content_key, {})
        if reports:
            if isinstance(reports, dict):
                # Combine all dimension reports
                content_parts = []
                for dim_name, dim_content in reports.items():
                    if dim_content:
                        content_parts.append(f"## {dim_name}\n\n{dim_content}")
                content = "\n\n---\n\n".join(content_parts)
            else:
                content = str(reports)
        
        # Fallback: try individual report keys
        if not content:
            # Try legacy keys
            legacy_keys = [
                "analysis_report", "planning_concept", "detailed_plan",
                "final_output", "detailed_plan_report"
            ]
            for key in legacy_keys:
                if key in state and state[key]:
                    content = state[key]
                    break
        
        if not content:
            raise HTTPException(status_code=404, detail=f"No content found for layer: {layer}")
        
        return {
            "layer": layer,
            "content": content,
            "session": session,
            "checkpoint_id": checkpoint_id,
            "timestamp": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Data API] Error getting layer content: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get layer content: {str(e)}")


@router.get("/api/data/villages/{name}/checkpoints")
async def get_checkpoints(
    name: str,
    session: str | None = Query(None, description="Session ID")
):
    """Get checkpoints for a village using LangGraph API"""
    try:
        # Get session_id if not provided
        if not session:
            sessions = await list_project_sessions_async(name, limit=1)
            if not sessions:
                return {
                    "project_name": name,
                    "checkpoints": [],
                    "count": 0
                }
            session = sessions[0]["session_id"]
        
        # Get checkpoints from LangGraph
        checkpoints = await _get_session_checkpoints(session)
        
        return {
            "project_name": name,
            "session": session,
            "checkpoints": checkpoints,
            "count": len(checkpoints)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Data API] Error getting checkpoints: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get checkpoints: {str(e)}")


@router.get("/api/data/villages/{name}/compare/{cp1}/{cp2}")
async def compare_checkpoints(name: str, cp1: str, cp2: str):
    """Compare two checkpoints using LangGraph API"""
    try:
        # Get latest session
        sessions = await list_project_sessions_async(name, limit=1)
        if not sessions:
            raise HTTPException(status_code=404, detail=f"No sessions found for: {name}")
        
        session_id = sessions[0]["session_id"]
        
        # Get both states
        state1 = await _get_state_from_checkpoint(session_id, cp1)
        state2 = await _get_state_from_checkpoint(session_id, cp2)
        
        if not state1:
            raise HTTPException(status_code=404, detail=f"Checkpoint not found: {cp1}")
        if not state2:
            raise HTTPException(status_code=404, detail=f"Checkpoint not found: {cp2}")
        
        # Compare states
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
    """Get combined planning report from LangGraph checkpoint"""
    try:
        # Get session_id if not provided
        if not session:
            sessions = await list_project_sessions_async(name, limit=1)
            if not sessions:
                raise HTTPException(status_code=404, detail=f"No sessions found for: {name}")
            session = sessions[0]["session_id"]
        
        # Get state
        state = await _get_state_from_checkpoint(session)
        
        if not state:
            raise HTTPException(status_code=404, detail=f"State not found for session: {session}")
        
        # Build combined content
        content_parts = []
        
        # Layer 1
        analysis_reports = state.get("analysis_reports", {})
        if analysis_reports:
            content_parts.append("# 现状分析\n\n")
            for dim_name, dim_content in analysis_reports.items():
                if dim_content:
                    content_parts.append(f"## {dim_name}\n\n{dim_content}\n\n")
            content_parts.append("\n---\n\n")
        
        # Layer 2
        concept_reports = state.get("concept_reports", {})
        if concept_reports:
            content_parts.append("# 规划思路\n\n")
            for dim_name, dim_content in concept_reports.items():
                if dim_content:
                    content_parts.append(f"## {dim_name}\n\n{dim_content}\n\n")
            content_parts.append("\n---\n\n")
        
        # Layer 3
        detail_reports = state.get("detail_reports", {})
        if detail_reports:
            content_parts.append("# 详细规划\n\n")
            for dim_name, dim_content in detail_reports.items():
                if dim_content:
                    content_parts.append(f"## {dim_name}\n\n{dim_content}\n\n")
        
        # Final output
        if state.get("final_output"):
            content_parts.append("# 最终成果\n\n")
            content_parts.append(state["final_output"])
        
        if not content_parts:
            raise HTTPException(status_code=404, detail="No plan content found")
        
        return {
            "content": "".join(content_parts),
            "format": format,
            "session": session,
            "source": "langgraph_checkpoint"
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