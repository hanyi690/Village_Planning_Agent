"""
Files API endpoints - File upload helper
文件API端点 - 文件上传辅助

支持多种文档格式：
- Word (.docx)
- PDF
- Excel (.xlsx, .xls)
- PowerPoint (.pptx, .ppt)
- 纯文本文件

使用 MarkItDown (Microsoft) 将文档转换为 Markdown 格式，
保留文档结构（标题、列表、表格等），便于 LLM 处理。
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import Dict, Any, Set
from pydantic import BaseModel, Field
from pathlib import Path
import logging
import io

router = APIRouter()

# Setup logger
logger = logging.getLogger(__name__)


# ============================================
# Response Schemas
# ============================================

class FileUploadResponse(BaseModel):
    """File upload response"""
    content: str = Field(..., description="Decoded file content")
    encoding: str = Field(..., description="Detected encoding or 'markitdown'")
    size: int = Field(..., description="Content size in characters")


# ============================================
# Configuration
# ============================================

# MarkItDown 支持的文档格式
MARKITDOWN_EXTENSIONS: Set[str] = {
    '.docx', '.doc',      # Word
    '.pdf',               # PDF
    '.xlsx', '.xls',      # Excel
    '.pptx', '.ppt',      # PowerPoint
    '.epub',              # EPUB
    '.html', '.htm',      # HTML
    '.csv',               # CSV
    '.json',              # JSON
    '.xml',               # XML
    '.zip',               # ZIP (会遍历内容)
}

# 纯文本格式（使用传统解码方式）
TEXT_EXTENSIONS: Set[str] = {
    '.txt', '.md', '.markdown', '.rst',
    '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h',
    '.css', '.scss', '.less',
    '.yaml', '.yml', '.toml', '.ini', '.cfg',
}


# ============================================
# Helper Functions
# ============================================

def decode_text_content(content: bytes) -> tuple[str, str]:
    """
    Decode plain text file content with automatic encoding detection.

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


def convert_with_markitdown(content: bytes, file_extension: str) -> tuple[str, str]:
    """
    Convert document to Markdown using MarkItDown.

    Args:
        content: Raw file bytes
        file_extension: File extension (e.g., '.docx', '.pdf')

    Returns:
        Tuple of (markdown_content, 'markitdown')

    Raises:
        ImportError: If markitdown is not installed
        Exception: If conversion fails
    """
    try:
        from markitdown import MarkItDown
    except ImportError:
        logger.error("[MarkItDown] markitdown library not installed. Install with: pip install 'markitdown[docx,pdf,xlsx,pptx]'")
        raise ImportError("markitdown 库未安装，请运行: pip install 'markitdown[docx,pdf,xlsx,pptx]'")

    # 创建 MarkItDown 实例
    md = MarkItDown(enable_plugins=False)

    # 使用 BytesIO 进行流式转换
    stream = io.BytesIO(content)

    try:
        result = md.convert_stream(stream, file_ext=file_extension)
        return result.text_content, 'markitdown'
    except Exception as e:
        logger.error(f"[MarkItDown] Conversion failed: {str(e)}")
        raise


# ============================================
# File Endpoints
# ============================================

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """
    Upload and decode a file
    上传并解码文件

    支持多种文档格式：
    - Word (.docx, .doc)
    - PDF
    - Excel (.xlsx, .xls)
    - PowerPoint (.pptx, .ppt)
    - 纯文本文件 (.txt, .md 等)

    返回解码后的内容（Markdown 格式）和编码信息。
    """
    try:
        # Read file content
        content = await file.read()
        file_size = len(content)
        logger.info(f"[Upload] File received: {file.filename}, size: {file_size} bytes")

        # Validate file size
        if file_size == 0:
            raise HTTPException(status_code=400, detail="文件内容为空")

        if file_size > 50_000_000:  # 50MB limit for documents
            raise HTTPException(status_code=400, detail="文件过大（限制50MB）")

        # 获取文件扩展名
        file_ext = Path(file.filename).suffix.lower()
        if not file_ext:
            # 无扩展名，尝试作为文本处理
            logger.info(f"[Upload] No file extension, treating as text")
            decoded_content, encoding = decode_text_content(content)
        elif file_ext in MARKITDOWN_EXTENSIONS:
            # 使用 MarkItDown 转换
            logger.info(f"[Upload] Using MarkItDown for {file_ext} file")
            try:
                decoded_content, encoding = convert_with_markitdown(content, file_ext)
            except ImportError as e:
                raise HTTPException(status_code=500, detail=str(e))
            except Exception as e:
                # MarkItDown 失败，尝试传统解码
                logger.warning(f"[Upload] MarkItDown failed, falling back to text decoding: {e}")
                decoded_content, encoding = decode_text_content(content)
        elif file_ext in TEXT_EXTENSIONS:
            # 纯文本文件
            logger.info(f"[Upload] Processing as plain text: {file_ext}")
            decoded_content, encoding = decode_text_content(content)
        else:
            # 未知格式，尝试文本解码
            logger.info(f"[Upload] Unknown extension {file_ext}, trying text decode")
            decoded_content, encoding = decode_text_content(content)

        content_length = len(decoded_content)
        logger.info(f"[Upload] Successfully decoded {content_length} characters using {encoding}")

        # Validate decoded content
        if not decoded_content or len(decoded_content.strip()) < 10:
            logger.error(f"[Upload] Invalid decoded content: length={len(decoded_content.strip())}")
            raise HTTPException(status_code=400, detail="文件内容不能为空或过短（至少需要10个字符）")

        return FileUploadResponse(
            content=decoded_content,
            encoding=encoding,
            size=content_length
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Upload] File processing failed: {str(e)}")
        raise HTTPException(status_code=400, detail=f"文件处理失败: {str(e)}")