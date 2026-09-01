"""
Async Database CRUD Operations
异步数据库 CRUD 操作

High-level async database operations for planning sessions, checkpoints,
and UI conversations using SQLAlchemy async support.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlmodel import SQLModel

from .engine import get_async_session
from .models import (
    PlanningSession,
    UISession,
    UploadedFile,
    PlanningBundle,
)

logger = logging.getLogger(__name__)


# ==========================================
# Helper Functions
# ==========================================

def make_json_serializable(obj: Any) -> Any:
    """
    Recursively convert non-JSON serializable types to serializable types
    递归转换不可JSON序列化的类型为可序列化类型
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)  # set → list
    if isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_json_serializable(i) for i in obj]
    # Other non-serializable objects → convert to string
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)


def _planning_session_to_dict(db_session: PlanningSession) -> Dict[str, Any]:
    """Convert PlanningSession model to dictionary"""
    return {
        "session_id": db_session.session_id,
        "project_name": db_session.project_name,
        "village_name": db_session.village_name,
        "province": db_session.province,
        "city": db_session.city,
        "county": db_session.county,
        "township": db_session.township,
        "planning_period": db_session.planning_period,
        "execution_error": db_session.execution_error,
        "village_data": db_session.village_data,
        "task_description": db_session.task_description,
        "constraints": db_session.constraints,
        "output_path": db_session.output_path,
        "created_at": db_session.created_at.isoformat() if db_session.created_at else None,
        "updated_at": db_session.updated_at.isoformat() if db_session.updated_at else None,
        "completed_at": db_session.completed_at.isoformat() if db_session.completed_at else None,
    }


def _ui_session_to_dict(db_session: UISession) -> Dict[str, Any]:
    """Convert UISession model to dictionary"""
    return {
        "conversation_id": db_session.conversation_id,
        "status": db_session.status,
        "project_name": db_session.project_name,
        "task_id": db_session.task_id,
        "created_at": db_session.created_at.isoformat() if db_session.created_at else None,
        "updated_at": db_session.updated_at.isoformat() if db_session.updated_at else None,
    }


# ==========================================
# Planning Session Operations
# ==========================================

async def create_planning_session_async(state: Dict[str, Any]) -> str:
    """
    Create planning session (async)

    Args:
        state: Session state dictionary

    Returns:
        str: Session ID
    """
    clean_state = make_json_serializable(state)

    # Support both direct access and nested request dict
    request = clean_state.get("request", {})
    task_desc = clean_state.get("task_description") or request.get("task_description", "制定村庄总体规划方案")
    constraints = clean_state.get("constraints") or request.get("constraints", "无特殊约束")

    # Extract config from state
    config = clean_state.get("config", {})

    async with get_async_session() as session:
        db_session = PlanningSession(
            session_id=clean_state["session_id"],
            project_name=clean_state.get("project_name", ""),
            village_name=config.get("village_name") or clean_state.get("village_name", ""),
            province=config.get("province") or clean_state.get("province", ""),
            city=config.get("city") or clean_state.get("city", ""),
            county=config.get("county") or clean_state.get("county", ""),
            township=config.get("township") or clean_state.get("township", ""),
            planning_period=(
                config.get("planning_period")
                or clean_state.get("planning_period", "2022-2035年")
            ),
            village_data=clean_state.get("village_data") or "",
            task_description=task_desc,
            constraints=constraints,
            output_path=clean_state.get("output_path"),
            completed_at=clean_state.get("completed_at"),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(db_session)
        await session.commit()
        await session.refresh(db_session)
        logger.info(f"[Async DB] Created planning session: {db_session.session_id}")
        return db_session.session_id


async def get_planning_session_async(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get planning session by ID (async)
    
    Args:
        session_id: Session ID
        
    Returns:
        Dict with session data, or None if not found
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                return None
            
            return _planning_session_to_dict(db_session)
    except Exception as e:
        logger.error(f"[Async DB] Failed to get planning session {session_id}: {e}", exc_info=True)
        return None


async def update_planning_session_async(
    session_id: str,
    updates: Dict[str, Any]
) -> bool:
    """
    Update planning session (async)
    
    Args:
        session_id: Session ID
        updates: Fields to update
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] Session {session_id} not found")
                return False
            
            for key, value in updates.items():
                if hasattr(db_session, key):
                    setattr(db_session, key, value)
            
            db_session.updated_at = datetime.now()
            await session.commit()
            logger.info(f"[Async DB] Updated planning session: {session_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to update planning session {session_id}: {e}", exc_info=True)
        return False


async def delete_planning_session_async(session_id: str) -> bool:
    """
    Delete planning session (async)
    
    Args:
        session_id: Session ID
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] Session {session_id} not found")
                return False
            
            await session.delete(db_session)
            await session.commit()
            logger.info(f"[Async DB] Deleted planning session: {session_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to delete planning session {session_id}: {e}", exc_info=True)
        return False


async def list_planning_sessions_async(
    project_name: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    List planning sessions (async)

    Args:
        project_name: Filter by project name
        limit: Maximum number of results

    Returns:
        List of session dictionaries
    """
    try:
        async with get_async_session() as session:
            query = select(PlanningSession)

            if project_name:
                query = query.where(PlanningSession.project_name == project_name)

            query = query.order_by(PlanningSession.created_at.desc()).limit(limit)
            
            result = await session.execute(query)
            sessions = result.scalars().all()
            
            logger.info(f"[Async DB] Found {len(sessions)} sessions for project_name={project_name}")
            return [_planning_session_to_dict(s) for s in sessions]
    except Exception as e:
        logger.error(f"[Async DB] Failed to list planning sessions: {e}", exc_info=True)
        return []


async def list_projects_async() -> List[Dict[str, Any]]:
    """
    List all projects grouped by project_name (async)
    
    Returns:
        List of project dictionaries with session counts
    """
    try:
        async with get_async_session() as session:
            # Query to get project_name and count, grouped by project_name
            query = select(
                PlanningSession.project_name,
                func.count(PlanningSession.session_id).label("session_count"),
                func.max(PlanningSession.created_at).label("last_session_at")
            ).group_by(PlanningSession.project_name).order_by(
                func.max(PlanningSession.created_at).desc()
            )
            
            result = await session.execute(query)
            rows = result.all()
            
            projects = []
            for row in rows:
                projects.append({
                    "name": row.project_name,
                    "display_name": row.project_name,
                    "session_count": row.session_count,
                    "last_session_at": row.last_session_at.isoformat() if row.last_session_at else None
                })
            
            return projects
    except Exception as e:
        logger.error(f"[Async DB] Failed to list projects: {e}", exc_info=True)
        return []


async def list_project_sessions_async(project_name: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    List all sessions for a specific project (async)
    
    Args:
        project_name: Project name
        limit: Maximum number of results
        
    Returns:
        List of session dictionaries
    """
    return await list_planning_sessions_async(project_name=project_name, limit=limit)


async def update_session_state_async(session_id: str, state: Dict[str, Any]) -> bool:
    """
    Update session state (async)
    
    Args:
        session_id: Session ID
        state: State dictionary
        
    Returns:
        bool: True if successful
    """
    clean_state = make_json_serializable(state)
    
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] Session {session_id} not found")
                return False
            
            for key, value in clean_state.items():
                if hasattr(db_session, key) and key not in [
                    "current_layer", "layer_1_completed", "layer_2_completed",
                    "layer_3_completed", "waiting_for_review"
                ]:
                    setattr(db_session, key, value)
            
            db_session.updated_at = datetime.now()
            await session.commit()
            logger.info(f"[Async DB] Updated session state: {session_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to update session state {session_id}: {e}", exc_info=True)
        return False


# ==========================================
# UI Session Operations
# ==========================================

async def create_ui_session_async(
    conversation_id: str,
    session_type: str = "conversation",
    project_name: Optional[str] = None,
    task_id: Optional[str] = None
) -> str:
    """
    Create UI session (async)
    
    Args:
        conversation_id: Conversation ID
        session_type: Session type
        project_name: Project name
        task_id: Task ID
        
    Returns:
        str: Conversation ID
    """
    async with get_async_session() as session:
        db_session = UISession(
            conversation_id=conversation_id,
            status="idle",
            project_name=project_name,
            task_id=task_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(db_session)
        await session.commit()
        await session.refresh(db_session)
        logger.info(f"[Async DB] Created UI session: {conversation_id}")
        return db_session.conversation_id


async def get_ui_session_async(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Get UI session by ID (async)
    
    Args:
        conversation_id: Conversation ID
        
    Returns:
        Dict with session data, or None if not found
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(UISession).where(UISession.conversation_id == conversation_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                return None
            
            return _ui_session_to_dict(db_session)
    except Exception as e:
        logger.error(f"[Async DB] Failed to get UI session {conversation_id}: {e}", exc_info=True)
        return None


async def update_ui_session_async(
    conversation_id: str,
    updates: Dict[str, Any]
) -> bool:
    """
    Update UI session (async)
    
    Args:
        conversation_id: Conversation ID
        updates: Fields to update
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(UISession).where(UISession.conversation_id == conversation_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] UI session {conversation_id} not found")
                return False
            
            for key, value in updates.items():
                if hasattr(db_session, key):
                    setattr(db_session, key, value)
            
            db_session.updated_at = datetime.now()
            await session.commit()
            logger.info(f"[Async DB] Updated UI session: {conversation_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to update UI session {conversation_id}: {e}", exc_info=True)
        return False


async def delete_ui_session_async(conversation_id: str) -> bool:
    """
    Delete UI session (async)
    
    Args:
        conversation_id: Conversation ID
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(UISession).where(UISession.conversation_id == conversation_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] UI session {conversation_id} not found")
                return False
            
            await session.delete(db_session)
            await session.commit()
            logger.info(f"[Async DB] Deleted UI session: {conversation_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to delete UI session {conversation_id}: {e}", exc_info=True)
        return False


async def list_ui_sessions_async(
    status: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    List UI sessions (async)
    
    Args:
        status: Filter by status
        task_id: Filter by task ID
        limit: Maximum number of results
        
    Returns:
        List of session dictionaries
    """
    try:
        async with get_async_session() as session:
            query = select(UISession)
            
            if status:
                query = query.where(UISession.status == status)
            
            if task_id:
                query = query.where(UISession.task_id == task_id)
            
            query = query.order_by(UISession.created_at.desc()).limit(limit)
            
            result = await session.execute(query)
            sessions = result.scalars().all()
            
            return [_ui_session_to_dict(s) for s in sessions]
    except Exception as e:
        logger.error(f"[Async DB] Failed to list UI sessions: {e}", exc_info=True)
        return []



# ==========================================
# Uploaded File Operations
# ==========================================

async def create_uploaded_file_async(
    session_id: str,
    file_category: str,
    input_role: str,
    file_type: str,
    filename: str,
    original_filename: str,
    file_size: int,
    content_type: str,
    source_digest: str = "",
    admission_status: str = "quarantined",
    admission_reason: str = "",
    admission_signals: Optional[List[str]] = None,
    parsed_text: Optional[str] = None,
    gis_data: Optional[Dict[str, Any]] = None,
    gis_data_type: Optional[str] = None,
    parse_status: str = "success",
    parse_error: Optional[str] = None,
) -> int:
    """
    Create an uploaded file record (async)
    创建上传文件记录

    Args:
        session_id: Session identifier
        file_category: "village_data", "task_description", or "constraint"
        file_type: "document", "geojson", "shapefile", etc.
        filename: Stored filename
        original_filename: Original uploaded filename
        file_size: File size in bytes
        content_type: MIME type
        parsed_text: Parsed text content (for documents)
        gis_data: GeoJSON data (for geojson files)
        gis_data_type: Inferred GIS data type
        parse_status: "pending", "success", or "failed"
        parse_error: Error message if parse failed

    Returns:
        int: File database ID
    """
    try:
        async with get_async_session() as session:
            db_file = UploadedFile(
                session_id=session_id,
                file_category=file_category,
                input_role=input_role,
                admission_status=admission_status,
                admission_reason=admission_reason,
                admission_signals=list(admission_signals or []),
                file_type=file_type,
                filename=filename,
                original_filename=original_filename,
                file_size=file_size,
                content_type=content_type,
                source_digest=source_digest,
                parsed_text=parsed_text,
                gis_data=gis_data,
                gis_data_type=gis_data_type,
                parse_status=parse_status,
                parse_error=parse_error,
                created_at=datetime.now(),
            )
            session.add(db_file)
            await session.commit()
            await session.refresh(db_file)
            logger.info(f"[Async DB] Created uploaded file: {filename} (id={db_file.id})")
            return db_file.id
    except Exception as e:
        logger.error(f"[Async DB] Failed to create uploaded file: {e}", exc_info=True)
        raise


async def get_uploaded_files_by_session_async(
    session_id: str,
    file_category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get all uploaded files for a session (async)
    获取会话的所有上传文件

    Args:
        session_id: Session identifier
        file_category: Filter by category (optional)

    Returns:
        List of file dictionaries
    """
    try:
        async with get_async_session() as session:
            query = select(UploadedFile).where(
                UploadedFile.session_id == session_id
            )
            if file_category:
                query = query.where(UploadedFile.file_category == file_category)
            query = query.order_by(UploadedFile.created_at)

            result = await session.execute(query)
            files = result.scalars().all()

            return [
                {
                    "id": f.id,
                    "session_id": f.session_id,
                    "file_category": f.file_category,
                    "input_role": f.input_role,
                    "admission_status": f.admission_status,
                    "admission_reason": f.admission_reason,
                    "admission_signals": list(f.admission_signals or []),
                    "file_type": f.file_type,
                    "filename": f.filename,
                    "original_filename": f.original_filename,
                    "file_size": f.file_size,
                    "content_type": f.content_type,
                    "source_digest": f.source_digest,
                    "parsed_text": f.parsed_text,
                    "gis_data": f.gis_data,
                    "gis_data_type": f.gis_data_type,
                    "parse_status": f.parse_status,
                    "parse_error": f.parse_error,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in files
            ]
    except Exception as e:
        logger.error(f"[Async DB] Failed to get uploaded files: {e}", exc_info=True)
        return []


async def get_uploaded_geojson_data_async(
    session_id: str,
    data_type_hint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get uploaded GIS data (GeoJSON) for a session (async)
    获取会话的上传 GIS 数据

    Args:
        session_id: Session identifier
        data_type_hint: Optional filter by inferred GIS data type

    Returns:
        List of GeoJSON FeatureCollection dicts
    """
    try:
        async with get_async_session() as session:
            query = select(UploadedFile).where(
                UploadedFile.session_id == session_id,
                UploadedFile.file_type == "geojson",
                UploadedFile.gis_data.isnot(None),
            )
            if data_type_hint:
                query = query.where(UploadedFile.gis_data_type == data_type_hint)

            result = await session.execute(query)
            files = result.scalars().all()

            from app.data.ingestion.source_admission import assess_source_admission

            admitted: list[Dict[str, Any]] = []
            for file in files:
                assessment = assess_source_admission(
                    input_role=str(file.input_role or ""),
                    category=str(file.file_category or ""),
                    source="upload",
                    filename=str(file.original_filename or file.filename or ""),
                    parsed_text=str(file.parsed_text or ""),
                    gis_data=(file.gis_data if isinstance(file.gis_data, dict) else None),
                    gis_data_type=str(file.gis_data_type or ""),
                )
                if (
                    assessment.status == "admitted"
                    and assessment.input_role == "current_evidence"
                    and str(file.admission_status or "").casefold() == assessment.status
                    and file.gis_data
                ):
                    admitted.append(file.gis_data)
            return admitted
    except Exception as e:
        logger.error(f"[Async DB] Failed to get uploaded geojson data: {e}", exc_info=True)
        return []


async def delete_uploaded_files_async(session_id: str) -> int:
    """
    Delete all uploaded files for a session (async)
    删除会话的所有上传文件

    Note: This is automatically handled by CASCADE on foreign key,
    but provided for explicit cleanup if needed.

    Args:
        session_id: Session identifier

    Returns:
        int: Number of files deleted
    """
    try:
        async with get_async_session() as session:
            statement = select(UploadedFile).where(
                UploadedFile.session_id == session_id
            )
            result = await session.execute(statement)
            files = result.scalars().all()
            count = len(files)

            for f in files:
                await session.delete(f)

            await session.commit()
            logger.info(f"[Async DB] Deleted {count} uploaded files for session {session_id}")
            return count
    except Exception as e:
        logger.error(f"[Async DB] Failed to delete uploaded files: {e}", exc_info=True)
        return 0


# ==========================================
# Planning Bundle Operations
# ==========================================

async def create_planning_bundle_async(bundle_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a planning bundle snapshot (async)
    创建规划数据包快照

    Args:
        bundle_data: dict with session_id, version, bundle_json, sha256,
            bundle_ref, trigger_reason

    Returns:
        Dict with the stored bundle record
    """
    async with get_async_session() as session:
        db_bundle = PlanningBundle(
            session_id=bundle_data["session_id"],
            version=bundle_data["version"],
            bundle_json=bundle_data["bundle_json"],
            sha256=bundle_data.get("sha256", ""),
            bundle_ref=bundle_data.get("bundle_ref"),
            trigger_reason=bundle_data.get("trigger_reason"),
            built_at=bundle_data.get("built_at") or datetime.now(),
        )
        session.add(db_bundle)
        await session.commit()
        await session.refresh(db_bundle)
        return _planning_bundle_to_dict(db_bundle)


async def get_planning_bundle_async(
    session_id: str,
    version: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get a planning bundle snapshot (async), latest version by default
    获取规划数据包快照（默认最新版本）

    Args:
        session_id: Session identifier
        version: Version number (optional, defaults to latest)

    Returns:
        Dict with bundle record or None
    """
    try:
        async with get_async_session() as session:
            if version is not None:
                query = select(PlanningBundle).where(
                    PlanningBundle.session_id == session_id,
                    PlanningBundle.version == version,
                )
            else:
                query = (
                    select(PlanningBundle)
                    .where(PlanningBundle.session_id == session_id)
                    .order_by(PlanningBundle.version.desc())
                    .limit(1)
                )
            result = await session.execute(query)
            bundle = result.scalar_one_or_none()
            return _planning_bundle_to_dict(bundle) if bundle else None
    except Exception as e:
        logger.error(f"[Async DB] Failed to get planning bundle: {e}", exc_info=True)
        return None


async def list_planning_bundle_versions_async(
    session_id: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    List planning bundle snapshot versions (async)
    列出规划数据包快照版本历史

    Args:
        session_id: Session identifier
        limit: Maximum number of results

    Returns:
        List of bundle metadata dicts (without bundle_json)
    """
    try:
        async with get_async_session() as session:
            query = (
                select(PlanningBundle)
                .where(PlanningBundle.session_id == session_id)
                .order_by(PlanningBundle.version.desc())
                .limit(limit)
            )
            result = await session.execute(query)
            bundles = result.scalars().all()

            return [
                {
                    "version": b.version,
                    "sha256": b.sha256,
                    "trigger_reason": b.trigger_reason,
                    "built_at": b.built_at.isoformat() if b.built_at else None,
                }
                for b in bundles
            ]
    except Exception as e:
        logger.error(f"[Async DB] Failed to list planning bundle versions: {e}", exc_info=True)
        return []


def _planning_bundle_to_dict(db_bundle: PlanningBundle) -> Dict[str, Any]:
    """Convert PlanningBundle model to dictionary."""
    return {
        "id": db_bundle.id,
        "session_id": db_bundle.session_id,
        "version": db_bundle.version,
        "bundle_json": db_bundle.bundle_json,
        "sha256": db_bundle.sha256,
        "bundle_ref": db_bundle.bundle_ref,
        "trigger_reason": db_bundle.trigger_reason,
        "built_at": db_bundle.built_at.isoformat() if db_bundle.built_at else None,
    }
