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
    PlanningTextDocument,
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
            village_name=config.get("village_name", ""),
            province=config.get("province", ""),
            city=config.get("city", ""),
            county=config.get("county", ""),
            township=config.get("township", ""),
            planning_period=config.get("planning_period", "2022-2035年"),
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


async def add_session_event_async(session_id: str, event: Dict[str, Any]) -> bool:
    """
    Add event to session (compatibility stub - no-op)

    Note: Events are now managed by SSEManager in memory.
    This function does nothing and always returns True.

    Args:
        session_id: Session ID
        event: Event dictionary

    Returns:
        bool: Always True
    """
    return True


async def get_session_events_async(session_id: str) -> List[Dict[str, Any]]:
    """
    Get session events (async)

    Note: Events are now managed by AsyncSqliteSaver in checkpoints table.
    This function returns empty list for compatibility.

    Args:
        session_id: Session ID

    Returns:
        List of event dictionaries (empty for now)
    """
    return []


# ==========================================
# Stream State Operations (Compatibility)
# ==========================================

async def is_execution_active_async(session_id: str) -> bool:
    """
    Check if execution is active (compatibility stub)

    Note: Execution state is now managed by LangGraph Checkpointer.
    This function always returns False for compatibility.

    Args:
        session_id: Session ID

    Returns:
        bool: Always False (execution state is in Checkpointer)
    """
    return False


async def set_execution_active_async(session_id: str, active: bool) -> bool:
    """
    Set execution active state (compatibility stub)

    Note: Execution state is now managed by LangGraph Checkpointer.
    This function is a no-op for compatibility.

    Args:
        session_id: Session ID
        active: Active state to set

    Returns:
        bool: Always True
    """
    return True


async def get_stream_state_async(session_id: str) -> str:
    """
    Get stream state (compatibility stub)

    Note: Stream state is now managed by LangGraph Checkpointer.
    This function always returns "active" for compatibility.

    Args:
        session_id: Session ID

    Returns:
        str: Always "active"
    """
    return "active"


async def set_stream_state_async(session_id: str, state: str) -> bool:
    """
    Set stream state (compatibility stub)

    Note: Stream state is now managed by LangGraph Checkpointer.
    This function is a no-op for compatibility.

    Args:
        session_id: Session ID
        state: New stream state

    Returns:
        bool: Always True
    """
    return True


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
    file_type: str,
    filename: str,
    original_filename: str,
    file_size: int,
    content_type: str,
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
                file_type=file_type,
                filename=filename,
                original_filename=original_filename,
                file_size=file_size,
                content_type=content_type,
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
                    "file_type": f.file_type,
                    "filename": f.filename,
                    "original_filename": f.original_filename,
                    "file_size": f.file_size,
                    "content_type": f.content_type,
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

            return [f.gis_data for f in files if f.gis_data]
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
                session.delete(f)

            await session.commit()
            logger.info(f"[Async DB] Deleted {count} uploaded files for session {session_id}")
            return count
    except Exception as e:
        logger.error(f"[Async DB] Failed to delete uploaded files: {e}", exc_info=True)
        return 0


# ==========================================
# Planning Text Document Operations
# ==========================================

async def create_planning_text_document_async(
    session_id: str,
    markdown_content: str,
    json_content: Optional[Dict[str, Any]] = None,
    article_count: int = 0,
    generation_duration_seconds: Optional[float] = None,
    trigger_reason: Optional[str] = None,
    changed_dimensions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Create a planning text document (async)
    创建规划文本文档（新版本）

    Args:
        session_id: Session identifier
        markdown_content: Markdown content
        json_content: JSON structured content
        article_count: Number of articles
        generation_duration_seconds: Generation duration
        trigger_reason: "initial", "dimension_change", "manual"
        changed_dimensions: List of changed dimension keys

    Returns:
        Dict with created document data
    """
    from uuid import uuid4

    try:
        async with get_async_session() as session:
            # Get the latest version number for this session
            version_result = await session.execute(
                select(func.max(PlanningTextDocument.version)).where(
                    PlanningTextDocument.session_id == session_id,
                )
            )
            latest_version = version_result.scalar() or 0
            new_version = latest_version + 1

            # Create new document
            doc = PlanningTextDocument(
                session_id=session_id,
                version=new_version,
                document_id=str(uuid4()),
                markdown_content=markdown_content,
                json_content=json_content,
                article_count=article_count,
                generation_duration_seconds=generation_duration_seconds,
                status="completed",
                trigger_reason=trigger_reason or "initial",
                changed_dimensions=changed_dimensions,
                generated_at=datetime.now(),
            )
            session.add(doc)
            await session.commit()
            await session.refresh(doc)

            logger.info(
                f"[Async DB] Created planning text document v{new_version} for session {session_id}"
            )
            return {
                "id": doc.id,
                "session_id": doc.session_id,
                "version": doc.version,
                "document_id": doc.document_id,
                "markdown_content": doc.markdown_content,
                "json_content": doc.json_content,
                "article_count": doc.article_count,
                "generated_at": doc.generated_at.isoformat(),
                "generation_duration_seconds": doc.generation_duration_seconds,
                "status": doc.status,
                "trigger_reason": doc.trigger_reason,
                "changed_dimensions": doc.changed_dimensions,
            }
    except Exception as e:
        logger.error(f"[Async DB] Failed to create planning text document: {e}", exc_info=True)
        raise


async def get_planning_text_document_async(
    session_id: str,
    version: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get planning text document (async)
    获取规划文本文档

    Args:
        session_id: Session identifier
        version: Version number (optional, defaults to latest)

    Returns:
        Dict with document data or None
    """
    try:
        async with get_async_session() as session:
            if version is not None:
                query = select(PlanningTextDocument).where(
                    PlanningTextDocument.session_id == session_id,
                    PlanningTextDocument.version == version,
                )
            else:
                # Get latest version
                query = (
                    select(PlanningTextDocument)
                    .where(PlanningTextDocument.session_id == session_id)
                    .order_by(PlanningTextDocument.version.desc())
                    .limit(1)
                )

            result = await session.execute(query)
            doc = result.scalar_one_or_none()

            if not doc:
                return None

            return {
                "id": doc.id,
                "session_id": doc.session_id,
                "version": doc.version,
                "document_id": doc.document_id,
                "markdown_content": doc.markdown_content,
                "json_content": doc.json_content,
                "article_count": doc.article_count,
                "generated_at": doc.generated_at.isoformat(),
                "generation_duration_seconds": doc.generation_duration_seconds,
                "status": doc.status,
                "error_message": doc.error_message,
                "trigger_reason": doc.trigger_reason,
                "changed_dimensions": doc.changed_dimensions,
            }
    except Exception as e:
        logger.error(f"[Async DB] Failed to get planning text document: {e}", exc_info=True)
        return None


async def list_planning_text_versions_async(
    session_id: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    List planning text document versions (async)
    列出规划文本文档版本历史

    Args:
        session_id: Session identifier
        limit: Maximum number of results

    Returns:
        List of version metadata dicts
    """
    try:
        async with get_async_session() as session:
            query = (
                select(PlanningTextDocument)
                .where(PlanningTextDocument.session_id == session_id)
                .order_by(PlanningTextDocument.version.desc())
                .limit(limit)
            )

            result = await session.execute(query)
            docs = result.scalars().all()

            return [
                {
                    "id": d.id,
                    "version": d.version,
                    "document_id": d.document_id,
                    "article_count": d.article_count,
                    "generated_at": d.generated_at.isoformat(),
                    "generation_duration_seconds": d.generation_duration_seconds,
                    "status": d.status,
                    "trigger_reason": d.trigger_reason,
                    "changed_dimensions": d.changed_dimensions,
                }
                for d in docs
            ]
    except Exception as e:
        logger.error(f"[Async DB] Failed to list planning text versions: {e}", exc_info=True)
        return []


async def update_planning_text_status_async(
    session_id: str,
    version: int,
    status: str,
    error_message: Optional[str] = None,
) -> bool:
    """
    Update planning text document status (async)
    更新规划文本文档状态

    Args:
        session_id: Session identifier
        version: Version number
        status: New status ("pending", "generating", "completed", "failed")
        error_message: Error message if failed

    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            query = select(PlanningTextDocument).where(
                PlanningTextDocument.session_id == session_id,
                PlanningTextDocument.version == version,
            )
            result = await session.execute(query)
            doc = result.scalar_one_or_none()

            if not doc:
                logger.error(f"[Async DB] Planning text document not found: {session_id} v{version}")
                return False

            doc.status = status
            if error_message:
                doc.error_message = error_message

            await session.commit()
            logger.info(f"[Async DB] Updated planning text status: {session_id} v{version} -> {status}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to update planning text status: {e}", exc_info=True)
        return False