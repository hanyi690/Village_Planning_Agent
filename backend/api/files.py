"""
Files API endpoints - File upload helper
文件API端点 - 文件上传辅助
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import Dict, Any
from pydantic import BaseModel
from pathlib import Path
import sys
import logging

# Add parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

router = APIRouter()

# Setup logger
logger = logging.getLogger(__name__)


# ============================================
# Response Schemas
# ============================================

class FileUploadResponse(BaseModel):
    """File upload response"""
    content: str = Field(..., description="Decoded file content")
    encoding: str = Field(..., description="Detected encoding")
    size: int = Field(..., description="Content size in characters")


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


# ============================================
# File Endpoints
# ============================================

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """
    Upload and decode a file
    上传并解码文件

    Returns the decoded content with encoding information.
    """
    try:
        # Read file content
        content = await file.read()
        file_size = len(content)
        logger.info(f"[Upload] File received: {file.filename}, size: {file_size} bytes")

        # Validate file size
        if file_size == 0:
            raise HTTPException(status_code=400, detail="文件内容为空")

        if file_size > 10_000_000:  # 10MB limit
            raise HTTPException(status_code=400, detail="文件过大（限制10MB）")

        # Decode with automatic encoding detection
        decoded_content, encoding = decode_file_content(content)
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
