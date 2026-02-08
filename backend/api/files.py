"""
Files API endpoints - File upload helper
文件API端点 - 文件上传辅助

集成RAG系统：上传文件后自动构建知识库
"""

import io
import logging
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.api.tool_manager import tool_manager

# RAG imports (conditional)
try:
    from src.rag.scripts.build_kb_auto import auto_build_knowledge_base
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    auto_build_knowledge_base = None  # type: ignore
    logger = logging.getLogger(__name__)
    logger.warning("[RAG集成] auto_build_knowledge_base 不可用，文件上传将不会自动构建知识库")

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================
# Response Schemas
# ============================================

class FileUploadResponse(BaseModel):
    """File upload response"""
    content: str = Field(..., description="Decoded file content")
    encoding: str = Field(..., description="Detected encoding")
    size: int = Field(..., description="Content size in characters")
    # RAG集成字段（可选）
    kb_indexed: bool = Field(False, description="是否已添加到知识库")
    chunks_created: int = Field(0, description="创建的切片数量")
    summary_generated: bool = Field(False, description="是否已生成摘要")


# ============================================
# Helper Functions
# ============================================

def decode_file_content(content: bytes) -> tuple[str, str]:
    """
    Decode file content with automatic encoding detection.

    Tries UTF-8 first, then uses chardet to detect encoding,
    and falls back to GBK if detection fails.

    Args:
        content: Raw bytes from file

    Returns:
        Tuple of (decoded_string, encoding_used)
    """
    # Try UTF-8 first (most common for modern files)
    try:
        return content.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        pass

    # Try to detect encoding using chardet
    try:
        import chardet
        detected = chardet.detect(content)
        encoding = detected.get('encoding')
        confidence = detected.get('confidence', 0)

        if encoding and confidence > 0.5:
            logger.info(f"[Encoding] Detected encoding: {encoding} (confidence: {confidence:.2f})")
            try:
                return content.decode(encoding), encoding
            except (UnicodeDecodeError, LookupError):
                pass
    except ImportError:
        logger.warning("[Encoding] chardet not installed, using fallback encodings")

    # Try GBK (common for Chinese Windows files)
    try:
        return content.decode('gbk'), 'gbk'
    except UnicodeDecodeError:
        pass

    # Try GB2312 (simplified subset of GBK)
    try:
        return content.decode('gb2312'), 'gb2312'
    except UnicodeDecodeError:
        pass

    # Last resort: decode with error replacement
    logger.warning("[Encoding] All encoding attempts failed, using UTF-8 with error replacement")
    return content.decode('utf-8', errors='replace'), 'utf-8-replace'


def parse_docx(content: bytes) -> str:
    """Parse .docx file and extract text"""
    from docx import Document

    doc = Document(io.BytesIO(content))
    paragraphs = []
    for para in doc.paragraphs:
        if para.text.strip():
            paragraphs.append(para.text.strip())
    return "\n".join(paragraphs)


def parse_pdf(content: bytes) -> str:
    """Parse .pdf file and extract text"""
    from pypdf import PdfReader

    pdf_reader = PdfReader(io.BytesIO(content))
    pages_text = []
    for page in pdf_reader.pages:
        text = page.extract_text()
        if text and text.strip():
            pages_text.append(text.strip())
    return "\n\n".join(pages_text)


# ============================================
# File Endpoints
# ============================================

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile):
    """
    Upload and parse file, supporting multiple formats:
    - .txt, .md: Text files with automatic encoding detection
    - .docx: Word documents, extract all paragraph text
    - .pdf: PDF documents, extract all page text

    上传并解析文件，支持多种格式：
    - .txt, .md: 文本文件，自动编码检测
    - .docx: Word文档，提取所有段落文本
    - .pdf: PDF文档，提取所有页面文本

    【RAG集成】文件上传后自动构建知识库（"即传即用"）
    """
    logger.info(f"[Files API] Upload request received")
    logger.info(f"[Files API] File name: {file.filename}")
    logger.info(f"[Files API] Content type: {file.content_type}")

    # RAG集成标志
    kb_indexed = False
    chunks_created = 0
    summary_generated = False

    try:
        content = await file.read()
        file_size = len(content)
        filename = file.filename or ""
        filename_lower = filename.lower()

        logger.info(f"[Upload] File received: {filename}, size: {file_size} bytes")

        # Validate file size
        if file_size == 0:
            raise HTTPException(status_code=400, detail="文件内容为空")

        if file_size > 10_000_000:  # 10MB limit
            raise HTTPException(status_code=400, detail="文件过大（限制10MB）")

        decoded_content = ""
        encoding = "unknown"

        # Route to appropriate parser based on file extension
        if filename_lower.endswith('.docx'):
            try:
                decoded_content = parse_docx(content)
                encoding = "docx"
                logger.info(f"[Upload] DOCX parsed: {len(decoded_content)} chars")
            except ImportError:
                logger.error("[Upload] python-docx not installed")
                raise HTTPException(
                    status_code=500,
                    detail="服务器缺少 Word 文档解析库，请联系管理员安装 python-docx"
                )
            except Exception as e:
                logger.error(f"[Upload] DOCX parsing failed: {str(e)}")
                raise HTTPException(status_code=400, detail=f"Word文档解析失败: {str(e)}")

        elif filename_lower.endswith('.pdf'):
            try:
                decoded_content = parse_pdf(content)
                encoding = "pdf"
                logger.info(f"[Upload] PDF parsed: {len(decoded_content)} chars")
            except ImportError:
                logger.error("[Upload] pypdf not installed")
                raise HTTPException(
                    status_code=500,
                    detail="服务器缺少 PDF 解析库，请联系管理员安装 pypdf"
                )
            except Exception as e:
                logger.error(f"[Upload] PDF parsing failed: {str(e)}")
                raise HTTPException(status_code=400, detail=f"PDF文档解析失败: {str(e)}")

        else:
            # Parse text files (.txt, .md)
            decoded_content, encoding = decode_file_content(content)
            logger.info(f"[Upload] Text decoded with encoding: {encoding}, {len(decoded_content)} chars")

        # Validate decoded content
        if not decoded_content or len(decoded_content.strip()) < 10:
            logger.error(f"[Upload] Invalid content: length={len(decoded_content.strip())}")
            raise HTTPException(status_code=400, detail="文件内容不能为空或过短（至少需要10个字符）")

        logger.info(f"[Upload] Content preview: {decoded_content[:200]}")

        # 【RAG集成】自动构建知识库
        if RAG_AVAILABLE and auto_build_knowledge_base is not None:
            try:
                logger.info(f"[RAG集成] 开始为 {filename} 构建知识库...")
                kb_result = auto_build_knowledge_base(
                    document_content=decoded_content,
                    document_name=filename,
                    collection_name="rural_planning"
                )
                kb_indexed = kb_result.get("success", False)
                chunks_created = kb_result.get("chunks_created", 0)
                summary_generated = kb_result.get("summary_generated", False)
                logger.info(f"[RAG集成] 知识库构建完成: {chunks_created} 切片, 摘要: {summary_generated}")
            except Exception as e:
                logger.warning(f"[RAG集成] 知识库构建失败（文件仍可使用）: {e}")
                # 不抛出异常，允许文件正常使用

        return FileUploadResponse(
            content=decoded_content,
            encoding=encoding,
            size=len(decoded_content),
            kb_indexed=kb_indexed,
            chunks_created=chunks_created,
            summary_generated=summary_generated
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Upload] File processing failed: {str(e)}")
        raise HTTPException(status_code=400, detail=f"文件处理失败: {str(e)}")


@router.get("/download/{filename}")
async def download_file(filename: str):
    """
    Download a file from the results directory

    下载结果目录中的文件
    """
    from src.utils.paths import get_results_dir

    results_dir = get_results_dir()
    file_path = results_dir / filename

    # Security check: ensure file is within results directory
    if not str(file_path.resolve()).startswith(str(results_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=file_path, filename=filename)
