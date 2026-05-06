"""
Knowledge Base API endpoints - 知识库管理接口

功能：
- 列出知识库文档
- 上传文档到知识库（增量添加）
- 异步上传文档（并行处理）
- 删除文档
- 获取统计信息
- 同步源目录
- 查询任务状态
"""

import logging
import os
import stat
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)

KB_CATEGORIES = ["policies", "cases", "standards", "domain", "local"]
SUPPORTED_EXTENSIONS = {'.txt', '.md', '.pdf', '.docx', '.doc', '.pptx', '.ppt'}


# ============================================
# Response Schemas
# ============================================

class KnowledgeDocument(BaseModel):
    source: str
    chunk_count: int
    doc_type: str
    dimension_tags: Optional[List[str]] = None
    terrain: Optional[str] = None
    regions: Optional[List[str]] = None
    category: Optional[str] = None


class KnowledgeStats(BaseModel):
    total_documents: int
    total_chunks: int
    vector_db_path: str
    source_dir: str


class AddDocumentResponse(BaseModel):
    status: str
    message: str
    source: Optional[str] = None
    chunks_added: Optional[int] = None


class SyncResponse(BaseModel):
    status: str
    message: str
    added_count: Optional[int] = None


class TaskProgressResponse(BaseModel):
    task_id: str
    filename: str
    status: str
    progress: float
    current_step: str
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class AsyncUploadResponse(BaseModel):
    task_id: str
    filename: str
    status: str
    message: str


# ============================================
# Helper Functions
# ============================================

def get_kb_manager():
    from src.rag.core.kb_manager import get_kb_manager as _get
    return _get()


def get_task_manager():
    from src.rag.core.task_manager import get_task_manager as _get
    return _get()


async def _add_document_task(file_path: str, category: Optional[str] = None,
                             doc_type: Optional[str] = None,
                             dimension_tags: Optional[List[str]] = None,
                             terrain: Optional[str] = None):
    """后台任务：添加文档到知识库"""
    try:
        manager = get_kb_manager()
        result = manager.add_document(file_path, category=category, doc_type=doc_type,
                                      dimension_tags=dimension_tags, terrain=terrain)
        if result["status"] == "success":
            logger.info(f"[Knowledge] 添加成功：{result['source']}, {result['chunks_added']} 切片")
        else:
            logger.error(f"[Knowledge] 添加失败：{result['message']}")
    except Exception as e:
        logger.error(f"[Knowledge] 添加异常：{e}")


# ============================================
# API Endpoints
# ============================================

@router.get("/documents", response_model=list[KnowledgeDocument])
async def list_documents():
    try:
        docs = get_kb_manager().list_documents()
        return [KnowledgeDocument(**doc) for doc in docs]
    except Exception as e:
        logger.error(f"[Knowledge] 列出文档失败：{e}")
        raise HTTPException(500, f"列出文档失败：{str(e)}")


@router.post("/documents", response_model=AddDocumentResponse)
async def add_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    dimension_tags: Optional[str] = Form(None),
    terrain: Optional[str] = Form(None),
):
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式：{ext}。支持：{SUPPORTED_EXTENSIONS}")

    # 解析维度标签
    tags_list = [t.strip() for t in dimension_tags.split(',')] if dimension_tags else None

    # 保存文件
    from src.rag.config import DATA_DIR
    save_dir = DATA_DIR / (category or "policies")
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / file.filename

    if file_path.exists():
        mode = os.stat(file_path).st_mode
        if not (mode & stat.S_IWRITE):
            os.chmod(file_path, mode | stat.S_IWRITE)

    content = await file.read()
    with open(file_path, 'wb') as f:
        f.write(content)

    logger.info(f"[Knowledge] 文件已保存：{file_path}")
    background_tasks.add_task(_add_document_task, str(file_path), category, doc_type, tags_list, terrain)

    return AddDocumentResponse(status="processing", message=f"文件 {file.filename} 已上传，正在后台处理", source=file.filename)


@router.delete("/documents/{filename}")
async def delete_document(filename: str):
    manager = get_kb_manager()
    result = manager.delete_document(filename)
    if result["status"] == "error":
        raise HTTPException(500, result["message"])

    # 删除源文件
    from src.rag.config import DATA_DIR
    for subdir in KB_CATEGORIES:
        p = DATA_DIR / subdir / filename
        if p.exists():
            p.unlink()
            logger.info(f"[Knowledge] 已删除源文件：{p}")
            break

    return {"status": "success", "message": f"已删除文档：{filename}"}


@router.get("/stats", response_model=KnowledgeStats)
async def get_stats():
    try:
        stats = get_kb_manager().get_stats()
        return KnowledgeStats(
            total_documents=stats.get("total_documents", 0),
            total_chunks=stats.get("total_chunks", 0),
            vector_db_path=stats.get("vector_db_path", ""),
            source_dir=stats.get("source_dir", "")
        )
    except Exception as e:
        logger.error(f"[Knowledge] 获取统计失败：{e}")
        raise HTTPException(500, f"获取统计信息失败：{str(e)}")


@router.post("/sync", response_model=SyncResponse)
async def sync_documents(background_tasks: BackgroundTasks):
    from src.rag.config import DATA_DIR
    from src.rag.utils.loaders import SUPPORTED_EXTENSIONS as LOADER_EXTS
    EXCLUDE_DIRS = {'vectordb', 'backup', 'chroma_db', '__pycache__', '.git'}

    manager = get_kb_manager()
    existing = {d["source"] for d in manager.list_documents()}

    # Scan all files once, then filter by extension
    valid_extensions = set(LOADER_EXTS.keys())
    source_files = [
        f for f in DATA_DIR.rglob("*")
        if f.is_file() and f.suffix in valid_extensions
        and not any(excluded in f.parts for excluded in EXCLUDE_DIRS)
    ]

    to_add = [f for f in source_files if f.name not in existing]
    if not to_add:
        return SyncResponse(status="success", message="知识库已是最新", added_count=0)

    for f in to_add:
        category = next((kw for kw in KB_CATEGORIES if kw in str(f)), "policies")
        background_tasks.add_task(_add_document_task, str(f), category)

    return SyncResponse(status="processing", message=f"正在处理 {len(to_add)} 个新文件", added_count=len(to_add))


# ============================================
# Async Document Upload Endpoints
# ============================================

def _process_document_async(
    file_path: str,
    progress_callback,
    category: Optional[str] = None,
    doc_type: Optional[str] = None,
    dimension_tags: Optional[List[str]] = None,
    terrain: Optional[str] = None,
) -> Dict[str, Any]:
    """异步文档处理函数（供任务管理器调用）"""
    manager = get_kb_manager()
    return manager.add_document_with_progress(
        file_path,
        progress_callback,
        category=category,
        doc_type=doc_type,
        dimension_tags=dimension_tags,
        terrain=terrain,
    )


@router.post("/documents/async", response_model=AsyncUploadResponse)
async def add_document_async(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    dimension_tags: Optional[str] = Form(None),
    terrain: Optional[str] = Form(None),
):
    """
    异步上传文档（并行处理）

    返回 task_id，可通过 GET /tasks/{task_id} 查询进度
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式：{ext}。支持：{SUPPORTED_EXTENSIONS}")

    # 解析维度标签
    tags_list = [t.strip() for t in dimension_tags.split(',')] if dimension_tags else None

    # 保存文件
    from src.rag.config import DATA_DIR
    save_dir = DATA_DIR / (category or "policies")
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / file.filename

    if file_path.exists():
        mode = os.stat(file_path).st_mode
        if not (mode & stat.S_IWRITE):
            os.chmod(file_path, mode | stat.S_IWRITE)

    content = await file.read()
    with open(file_path, 'wb') as f:
        f.write(content)

    logger.info(f"[Knowledge] 异步上传：文件已保存 {file_path}")

    # 提交到任务管理器
    task_manager = get_task_manager()
    task_id = task_manager.submit(
        str(file_path),
        _process_document_async,
        category=category,
        doc_type=doc_type,
        dimension_tags=tags_list,
        terrain=terrain,
    )

    return AsyncUploadResponse(
        task_id=task_id,
        filename=file.filename,
        status="pending",
        message=f"文件已提交，任务 ID: {task_id}",
    )


@router.get("/tasks/{task_id}", response_model=TaskProgressResponse)
async def get_task_status(task_id: str):
    """获取单个任务状态"""
    task_manager = get_task_manager()
    task = task_manager.get_task(task_id)

    if not task:
        raise HTTPException(404, f"任务不存在: {task_id}")

    return TaskProgressResponse(
        task_id=task.task_id,
        filename=task.filename,
        status=task.status.value,
        progress=task.progress,
        current_step=task.current_step,
        error_message=task.error_message,
        retry_count=task.retry_count,
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


@router.get("/tasks", response_model=List[TaskProgressResponse])
async def list_tasks():
    """列出所有任务"""
    task_manager = get_task_manager()
    tasks = task_manager.get_all_tasks()

    return [
        TaskProgressResponse(
            task_id=t.task_id,
            filename=t.filename,
            status=t.status.value,
            progress=t.progress,
            current_step=t.current_step,
            error_message=t.error_message,
            retry_count=t.retry_count,
            created_at=t.created_at.isoformat() if t.created_at else None,
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
        )
        for t in tasks
    ]


@router.delete("/tasks/{task_id}")
async def clear_task(task_id: str):
    """清理已完成/失败的任务"""
    task_manager = get_task_manager()
    task = task_manager.get_task(task_id)

    if not task:
        raise HTTPException(404, f"任务不存在: {task_id}")

    if task.status.value not in ("completed", "failed"):
        raise HTTPException(400, "只能清理已完成或失败的任务")

    # 任务管理器会在 clear_completed_tasks 时自动清理
    task_manager.clear_completed_tasks(max_age_hours=0)

    return {"status": "success", "message": f"任务 {task_id} 已清理"}