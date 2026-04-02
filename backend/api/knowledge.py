"""
Knowledge Base API endpoints - 知识库管理接口
提供前端管理知识库的 REST API

功能：
- 列出知识库文档
- 上传文档到知识库（增量添加）
- 删除文档
- 获取统计信息
- 同步源目录
"""

import logging
import os
import stat
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

router = APIRouter()

logger = logging.getLogger(__name__)

# 知识库类别常量
KB_CATEGORIES = ["policies", "cases", "standards", "domain", "local"]


# ============================================
# Response Schemas
# ============================================

class KnowledgeDocument(BaseModel):
    """知识库文档信息"""
    source: str = Field(..., description="文档名称（文件名）")
    chunk_count: int = Field(..., description="切片数量")
    doc_type: str = Field(..., description="文档类型")
    # 元数据字段（新增）
    dimension_tags: Optional[list[str]] = Field(None, description="维度标签列表")
    terrain: Optional[str] = Field(None, description="地形类型")
    regions: Optional[list[str]] = Field(None, description="地区列表")
    category: Optional[str] = Field(None, description="文档类别")


class KnowledgeStats(BaseModel):
    """知识库统计信息"""
    total_documents: int = Field(..., description="文档总数")
    total_chunks: int = Field(..., description="切片总数")
    vector_db_path: str = Field(..., description="向量库路径")
    source_dir: str = Field(..., description="源文件目录")


class AddDocumentResponse(BaseModel):
    """添加文档响应"""
    status: str = Field(..., description="状态：success/error/processing")
    message: str = Field(..., description="消息")
    source: Optional[str] = Field(None, description="文档名称")
    chunks_added: Optional[int] = Field(None, description="添加的切片数")


class SyncResponse(BaseModel):
    """同步响应"""
    status: str = Field(..., description="状态")
    message: str = Field(..., description="消息")
    added_count: Optional[int] = Field(None, description="添加的文档数")


# ============================================
# Helper Functions
# ============================================

def get_kb_manager():
    """获取知识库管理器（延迟导入）"""
    from src.rag.core.kb_manager import get_kb_manager as _get_kb_manager
    return _get_kb_manager()


async def add_document_task(
    file_path: str,
    category: Optional[str] = None,
    doc_type: Optional[str] = None,
    dimension_tags: Optional[list[str]] = None,
    terrain: Optional[str] = None,
):
    """后台任务：添加文档到知识库"""
    try:
        manager = get_kb_manager()
        result = manager.add_document(
            file_path,
            category=category,
            doc_type=doc_type,
            dimension_tags=dimension_tags,
            terrain=terrain,
        )

        if result["status"] == "success":
            logger.info(f"[Knowledge] 后台添加文档成功：{result['source']}, {result['chunks_added']} 切片")
        else:
            logger.error(f"[Knowledge] 后台添加文档失败：{result['message']}")

    except Exception as e:
        logger.error(f"[Knowledge] 后台添加文档异常：{e}")


# ============================================
# API Endpoints
# ============================================

@router.get("/documents", response_model=list[KnowledgeDocument])
async def list_documents():
    """
    列出知识库中的所有文档

    Returns:
        文档列表，包含名称、切片数、类型、元数据
    """
    try:
        manager = get_kb_manager()
        docs = manager.list_documents()
        return [KnowledgeDocument(**doc) for doc in docs]
    except Exception as e:
        logger.error(f"[Knowledge] 列出文档失败：{e}")
        raise HTTPException(status_code=500, detail=f"列出文档失败：{str(e)}")


@router.post("/documents", response_model=AddDocumentResponse)
async def add_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    dimension_tags: Optional[str] = Form(None),  # 逗号分隔的维度标签
    terrain: Optional[str] = Form(None),
):
    """
    上传文档到知识库（增量添加）

    Args:
        file: 上传的文件
        category: 文档类别（policies/cases/standards/domain/local）
        doc_type: 文档类型（policy/standard/case/guide/report）
        dimension_tags: 维度标签（逗号分隔，如：land_use,infrastructure,traffic）
        terrain: 地形类型（mountain/plain/hill/coastal/riverside/all）

    Returns:
        添加结果，处理在后台进行
    """
    try:
        # 检查文件扩展名
        file_ext = Path(file.filename).suffix.lower()
        supported_extensions = {'.txt', '.md', '.pdf', '.docx', '.doc', '.pptx', '.ppt'}

        if file_ext not in supported_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式：{file_ext}。支持：{supported_extensions}"
            )

        # 解析维度标签
        dimension_tags_list = None
        if dimension_tags:
            dimension_tags_list = [tag.strip() for tag in dimension_tags.split(',')]

        # 保存文件到源目录
        from src.rag.config import DATA_DIR

        save_dir = DATA_DIR / (category or "policies")
        save_dir.mkdir(parents=True, exist_ok=True)

        file_path = save_dir / file.filename

        # 如果文件已存在且为只读，移除只读属性
        if file_path.exists():
            current_mode = os.stat(file_path).st_mode
            if not (current_mode & stat.S_IWRITE):
                os.chmod(file_path, current_mode | stat.S_IWRITE)
                logger.info(f"[Knowledge] 已移除只读属性：{file_path}")

        # 写入文件
        content = await file.read()
        with open(file_path, 'wb') as f:
            f.write(content)

        logger.info(f"[Knowledge] 文件已保存：{file_path}")

        # 添加后台任务处理文档
        background_tasks.add_task(
            add_document_task,
            str(file_path),
            category,
            doc_type,
            dimension_tags_list,
            terrain,
        )

        return AddDocumentResponse(
            status="processing",
            message=f"文件 {file.filename} 已上传，正在后台处理",
            source=file.filename
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Knowledge] 上传文档失败：{e}")
        raise HTTPException(status_code=500, detail=f"上传文档失败：{str(e)}")


@router.delete("/documents/{filename}")
async def delete_document(filename: str):
    """
    从知识库删除文档

    Args:
        filename: 文档名称（文件名）

    Returns:
        删除结果
    """
    try:
        manager = get_kb_manager()
        result = manager.delete_document(filename)

        if result["status"] == "error":
            raise HTTPException(status_code=500, detail=result["message"])

        # 同时删除源文件
        from src.rag.config import DATA_DIR
        for subdir in KB_CATEGORIES:
            file_path = DATA_DIR / subdir / filename
            if file_path.exists():
                file_path.unlink()
                logger.info(f"[Knowledge] 已删除源文件：{file_path}")
                break

        return {"status": "success", "message": f"已删除文档：{filename}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Knowledge] 删除文档失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除文档失败：{str(e)}")


@router.get("/stats", response_model=KnowledgeStats)
async def get_stats():
    """
    获取知识库统计信息

    Returns:
        统计信息
    """
    try:
        manager = get_kb_manager()
        stats = manager.get_stats()

        return KnowledgeStats(
            total_documents=stats.get("total_documents", 0),
            total_chunks=stats.get("total_chunks", 0),
            vector_db_path=stats.get("vector_db_path", ""),
            source_dir=stats.get("source_dir", "")
        )
    except Exception as e:
        logger.error(f"[Knowledge] 获取统计信息失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取统计信息失败：{str(e)}")


@router.post("/sync", response_model=SyncResponse)
async def sync_documents(background_tasks: BackgroundTasks):
    """
    同步源目录到知识库

    扫描源目录，将新增的文件添加到知识库

    Returns:
        同步结果
    """
    try:
        from src.rag.config import DATA_DIR
        from src.rag.utils.loaders import SUPPORTED_EXTENSIONS

        # 排除的目录（缓存、临时文件等）
        EXCLUDE_DIRS = {'vectordb', 'backup', 'chroma_db', '__pycache__', '.git'}

        # 获取知识库中已有的文档
        manager = get_kb_manager()
        existing_docs = {d["source"] for d in manager.list_documents()}

        # 扫描源文件目录，排除缓存目录
        source_files = []
        for ext in SUPPORTED_EXTENSIONS.keys():
            for f in DATA_DIR.rglob(f"*{ext}"):
                # 排除缓存目录中的文件
                if not any(excluded in f.parts for excluded in EXCLUDE_DIRS):
                    source_files.append(f)

        # 找出需要添加的文件
        to_add = [f for f in source_files if f.name not in existing_docs]

        if not to_add:
            return SyncResponse(
                status="success",
                message="知识库已是最新",
                added_count=0
            )

        # 添加后台任务
        for f in to_add:
            # 根据路径确定类别
            category = "policies"  # 默认值
            for keyword in KB_CATEGORIES:
                if keyword in str(f):
                    category = keyword
                    break
            background_tasks.add_task(add_document_task, str(f), category)

        return SyncResponse(
            status="processing",
            message=f"正在处理 {len(to_add)} 个新文件",
            added_count=len(to_add)
        )

    except Exception as e:
        logger.error(f"[Knowledge] 同步失败：{e}")
        raise HTTPException(status_code=500, detail=f"同步失败：{str(e)}")
