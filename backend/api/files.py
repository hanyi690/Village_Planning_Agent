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
from typing import Dict, Any, Set, Optional, List
from pydantic import BaseModel, Field
from pathlib import Path
import logging
import io
import tempfile
import base64

# 导入 .doc 文件转换器
from src.rag.utils.loaders import DocToDocxConverter
from src.core.config import MAX_IMAGE_SIZE_MULTIMODAL

router = APIRouter()

# Setup logger
logger = logging.getLogger(__name__)


# ============================================
# Response Schemas
# ============================================

class EmbeddedImage(BaseModel):
    """Embedded image from document"""
    image_base64: str = Field(..., description="Base64 encoded image data")
    image_format: str = Field(..., description="Image format: jpg, png, gif, etc.")
    thumbnail_base64: str = Field(..., description="Base64 encoded thumbnail")
    image_width: int = Field(..., description="Image width in pixels")
    image_height: int = Field(..., description="Image height in pixels")


class FileUploadResponse(BaseModel):
    """File upload response"""
    content: str = Field(..., description="Decoded file content")
    encoding: str = Field(..., description="Detected encoding or 'markitdown'")
    size: int = Field(..., description="Content size in characters")
    file_type: Optional[str] = Field(None, description="File type: 'document' or 'image'")
    image_base64: Optional[str] = Field(None, description="Base64 encoded image data")
    image_format: Optional[str] = Field(None, description="Image format: jpg, png, gif, etc.")
    thumbnail_base64: Optional[str] = Field(None, description="Base64 encoded thumbnail")
    image_width: Optional[int] = Field(None, description="Image width in pixels")
    image_height: Optional[int] = Field(None, description="Image height in pixels")
    embedded_images: Optional[List[EmbeddedImage]] = Field(None, description="Embedded images from document")


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

# 图片格式
IMAGE_EXTENSIONS: Set[str] = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'
}

# 图片格式映射（用于 base64 编码时的 format 参数）
IMAGE_FORMAT_MAP: Dict[str, str] = {
    '.jpg': 'jpeg', '.jpeg': 'jpeg',
    '.png': 'png', '.gif': 'gif',
    '.webp': 'webp', '.bmp': 'bmp',
    '.emf': 'emf', '.wmf': 'wmf', '.tiff': 'tiff'
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
        # keep_data_uris=False 防止 base64 图片嵌入 Markdown（避免内容膨胀）
        result = md.convert_stream(stream, file_ext=file_extension, keep_data_uris=False)
        return result.text_content, 'markitdown'
    except Exception as e:
        logger.error(f"[MarkItDown] Conversion failed: {str(e)}")
        raise


def _encode_image_with_thumbnail(
    img: 'Image.Image',
    max_display_size: int = 1024,
    thumb_size: tuple[int, int] = (200, 150),
    needs_full_image: bool = True,
    output_format: str = 'jpeg',
) -> Dict[str, Any]:
    """
    Unified image encoding: RGB conversion, resize, thumbnail generation, base64 encoding.

    Args:
        img: PIL Image object
        max_display_size: Max dimension for display image
        thumb_size: Thumbnail size tuple
        needs_full_image: Whether to generate full-size image
        output_format: Output format for encoding (default 'jpeg')

    Returns:
        Dict with: image_base64, image_format, thumbnail_base64, width, height
    """
    from PIL import Image  # Import for Image.new and Image.Resampling

    # Record original dimensions
    original_width, original_height = img.size

    # RGB conversion (handle RGBA/P modes)
    if img.mode in ('RGBA', 'P'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # Encode full image (optional, resize if too large)
    image_base64 = None
    if needs_full_image:
        if max(img.size) > max_display_size:
            ratio = max_display_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img.thumbnail(new_size, Image.Resampling.LANCZOS)

        full_buffer = io.BytesIO()
        img.save(full_buffer, format=output_format.upper())
        image_base64 = base64.b64encode(full_buffer.getvalue()).decode('utf-8')

    # Generate thumbnail from current image state
    thumb_img = img.copy()
    thumb_img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
    thumb_buffer = io.BytesIO()
    thumb_img.save(thumb_buffer, format=output_format.upper())
    thumbnail_base64 = base64.b64encode(thumb_buffer.getvalue()).decode('utf-8')

    return {
        'image_base64': image_base64,
        'image_format': output_format,
        'thumbnail_base64': thumbnail_base64,
        'image_width': original_width,
        'image_height': original_height,
    }


def _extract_embedded_images(content: bytes, file_ext: str) -> List[Dict[str, Any]]:
    """
    Extract embedded images from document files.

    .docx files are ZIP archives with images stored in word/media/.
    This function extracts those images and returns them as base64-encoded data.

    Args:
        content: Raw document bytes
        file_ext: File extension (.docx, etc.)

    Returns:
        List of image dicts with: image_base64, image_format, thumbnail_base64, width, height
    """
    if file_ext != '.docx':
        return []

    try:
        import zipfile
        from PIL import Image
    except ImportError:
        logger.warning("[ImageExtract] zipfile or Pillow not available")
        return []

    images = []
    try:
        with zipfile.ZipFile(io.BytesIO(content), 'r') as z:
            # Find media files in word/media/
            media_files = [f for f in z.namelist()
                          if f.startswith('word/media/') and not f.endswith('/')]

            logger.info(f"[ImageExtract] Found {len(media_files)} media files in .docx")

            # Limit to 10 images to avoid excessive processing
            for media_file in media_files[:10]:
                try:
                    img_data = z.read(media_file)

                    # Open and process image using shared function (outputs JPEG)
                    img = Image.open(io.BytesIO(img_data))
                    result = _encode_image_with_thumbnail(img)
                    images.append(result)

                    logger.info(f"[ImageExtract] Extracted: {media_file}, {result['image_width']}x{result['image_height']}")

                except Exception as e:
                    logger.warning(f"[ImageExtract] Failed to extract {media_file}: {e}")
                    continue

    except Exception as e:
        logger.warning(f"[ImageExtract] Failed to open .docx as ZIP: {e}")

    return images


def _process_doc_file(content: bytes, filename: str) -> tuple[str, str]:
    """
    处理 .doc 文件：先转换为 .docx，再用 MarkItDown 解析
    
    MarkItDown 不支持旧版 .doc (OLE 格式)，
    需要使用 DocToDocxConverter (win32com) 先转换为 .docx
    
    Args:
        content: 原始文件字节
        filename: 文件名（用于日志）
        
    Returns:
        Tuple of (markdown_content, 'markitdown')
        
    Raises:
        Exception: 如果转换或解析失败
    """
    # 检查转换器是否可用
    if not DocToDocxConverter.is_available():
        raise Exception(
            "无法处理 .doc 文件。请安装 pywin32: pip install pywin32\n"
            "或将文件另存为 .docx 格式后重新上传。"
        )
    
    # 保存到临时文件
    with tempfile.NamedTemporaryFile(suffix='.doc', delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    try:
        # 转换 .doc 为 .docx
        logger.info(f"[Upload] Converting .doc to .docx: {filename}")
        docx_path = DocToDocxConverter.convert(tmp_path)
        
        if docx_path is None:
            raise Exception("doc 到 docx 转换失败")
        
        # 读取转换后的 .docx 文件
        with open(docx_path, 'rb') as f:
            docx_content = f.read()
        
        # 用 MarkItDown 处理 .docx
        logger.info(f"[Upload] Processing converted .docx file")
        decoded_content, encoding = convert_with_markitdown(docx_content, '.docx')
        
        return decoded_content, encoding
        
    finally:
        # 清理临时文件
        if tmp_path.exists():
            tmp_path.unlink()


def process_image(
    content: bytes,
    file_ext: str,
    needs_full_image: bool = True,
    max_display_size: int = 1024,
) -> Dict[str, Any]:
    """
    Process image file and return base64 encoded data with metadata.

    Args:
        content: Raw image bytes
        file_ext: File extension (e.g., '.jpg', '.png')
        needs_full_image: If True, encode full image for LLM. If False, only thumbnail.
        max_display_size: Max dimension for display image (default 1024). Large images
                         are resized to reduce memory/cost for LLM consumption.

    Returns:
        Dict with image_base64, image_format, thumbnail_base64, width, height

    Raises:
        ImportError: If Pillow is not installed
        Exception: If image processing fails
    """
    try:
        from PIL import Image
    except ImportError:
        logger.error("[Image] Pillow library not installed. Install with: pip install Pillow")
        raise ImportError("Pillow 库未安装，请运行: pip install Pillow")

    image_format = IMAGE_FORMAT_MAP.get(file_ext, 'jpeg')

    try:
        img = Image.open(io.BytesIO(content))
        result = _encode_image_with_thumbnail(
            img,
            max_display_size=max_display_size,
            needs_full_image=needs_full_image,
            output_format=image_format,
        )

        # Log resize info if applicable
        if needs_full_image and max(img.size) > max_display_size:
            ratio = max_display_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            logger.info(f"[Image] Resized for LLM: {result['image_width']}x{result['image_height']} -> {new_size[0]}x{new_size[1]}")

        logger.info(f"[Image] Processed: {result['image_width']}x{result['image_height']}, format={image_format}, full_encoded={result['image_base64'] is not None}")

        return result

    except Exception as e:
        logger.error(f"[Image] Processing failed: {str(e)}")
        raise Exception(f"图片处理失败: {str(e)}")


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
    - 图片文件 (.jpg, .jpeg, .png, .gif, .webp, .bmp)

    返回解码后的内容（Markdown 格式）和编码信息。
    图片文件返回 base64 编码数据。
    """
    try:
        # Read file content
        content = await file.read()
        file_size = len(content)
        logger.info(f"[Upload] File received: {file.filename}, size: {file_size} bytes")

        # Validate file size
        if file_size == 0:
            raise HTTPException(status_code=400, detail="文件内容为空")

        # 图片文件大小限制
        file_ext = Path(file.filename).suffix.lower()
        if file_ext in IMAGE_EXTENSIONS and file_size > MAX_IMAGE_SIZE_MULTIMODAL:
            raise HTTPException(status_code=400, detail=f"图片文件过大（限制{MAX_IMAGE_SIZE_MULTIMODAL // 1_000_000}MB）")
        elif file_size > 50_000_000:  # 50MB limit for documents
            raise HTTPException(status_code=400, detail="文件过大（限制50MB）")

        # 获取文件扩展名
        if not file_ext:
            # 无扩展名，尝试作为文本处理
            logger.info(f"[Upload] No file extension, treating as text")
            decoded_content, encoding = decode_text_content(content)
        elif file_ext in IMAGE_EXTENSIONS:
            # 图片文件处理
            logger.info(f"[Upload] Processing image file: {file_ext}")
            try:
                image_data = process_image(content, file_ext)
                # 图片文件返回简短描述作为 content
                decoded_content = f"[图片: {file.filename}, 尺寸: {image_data['image_width']}x{image_data['image_height']}]"
                encoding = 'base64'

                return FileUploadResponse(
                    content=decoded_content,
                    encoding=encoding,
                    size=len(decoded_content),
                    file_type='image',
                    image_base64=image_data['image_base64'],
                    image_format=image_data['image_format'],
                    thumbnail_base64=image_data['thumbnail_base64'],
                    image_width=image_data['image_width'],
                    image_height=image_data['image_height'],
                )
            except ImportError as e:
                raise HTTPException(status_code=500, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"图片处理失败: {str(e)}")
        elif file_ext == '.doc':
            # 特殊处理 .doc 文件：MarkItDown 不支持 OLE 格式，需要先转换
            logger.info(f"[Upload] Processing .doc file (OLE format), converting to .docx...")
            try:
                decoded_content, encoding = _process_doc_file(content, file.filename)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f".doc 文件处理失败: {str(e)}")
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

        # Extract embedded images for .docx files
        embedded_images = []
        if file_ext == '.docx':
            embedded_images = _extract_embedded_images(content, file_ext)
            if embedded_images:
                logger.info(f"[Upload] Extracted {len(embedded_images)} embedded images from .docx")

        return FileUploadResponse(
            content=decoded_content,
            encoding=encoding,
            size=content_length,
            file_type='document',
            embedded_images=embedded_images if embedded_images else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Upload] File processing failed: {str(e)}")
        raise HTTPException(status_code=400, detail=f"文件处理失败: {str(e)}")