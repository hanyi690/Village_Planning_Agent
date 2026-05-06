"""
PDF Fallback 解析链

当 MarkItDown (pdfminer.six) 解析失败时，自动尝试备用解析器。

解析优先级：
1. MarkItDown (pdfminer.six + OCR Plugin) → 主解析器，支持扫描版 PDF
2. PyMuPDF OCR → 扫描版 PDF 自定义 OCR（支持切分优化的 prompt）
3. PyMuPDF (fitz) → 复杂字体/布局容错
4. pdfplumber → 表格/结构化内容提取

注意：扫描版 PDF 由 OCR 处理，使用优化的 prompt 便于切分。
"""
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import base64

# Optional imports - 安装失败不影响其他功能
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    fitz = None

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    pdfplumber = None

# OCR Prompt（优化为便于切分的 Markdown 格式）
OCR_PROMPT = """识别图片所有文字，直接输出原文内容，不要加任何解释。规则：
- 章节标题用 # 标记（如"第一章"）
- 小节标题用 ## 标记（如"1.1 xxx"）
- 正文保持原有排版
- 表格用 Markdown 格式"""


def check_parsers() -> Dict[str, bool]:
    """
    检测 PDF 解析器可用性

    Returns:
        字典格式: {'pymupdf': bool, 'pdfplumber': bool, 'ocr': bool}
    """
    # 检查 OCR 可用性
    ocr_available = False
    try:
        from src.core.config import DASHSCOPE_API_KEY, OCR_MODEL_NAME
        ocr_available = bool(DASHSCOPE_API_KEY)
    except ImportError:
        pass

    return {
        'pymupdf': PYMUPDF_AVAILABLE,
        'pdfplumber': PDFPLUMBER_AVAILABLE,
        'ocr': ocr_available,
    }


def extract_with_ocr(
    file_path: Path,
    pages: Optional[List[int]] = None,
    max_pages: int = 50,
) -> Tuple[Optional[str], Optional[str]]:
    """
    使用 OCR 提取扫描版 PDF 文字（自定义 prompt，便于切分）

    Args:
        file_path: PDF 文件路径
        pages: 要处理的页码列表（None 表示自动检测扫描页）
        max_pages: 最大处理页数（防止超时）

    Returns:
        (文本内容, 错误信息)，成功时错误为 None
    """
    if not PYMUPDF_AVAILABLE:
        return None, "PyMuPDF 未安装，OCR 需要 PyMuPDF 渲染图片"

    try:
        from src.core.config import DASHSCOPE_API_KEY, DASHSCOPE_API_BASE, OCR_MODEL_NAME
        from openai import OpenAI
    except ImportError as e:
        return None, f"OCR 配置缺失: {e}"

    if not DASHSCOPE_API_KEY:
        return None, "DASHSCOPE_API_KEY 未配置"

    try:
        doc = fitz.open(str(file_path))
        client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_API_BASE)

        # 确定要处理的页码
        if pages is None:
            # 自动检测：只处理无文本的页面（扫描页）
            pages_to_process = []
            for i in range(min(max_pages, len(doc))):
                page = doc[i]
                if not page.get_text().strip():
                    pages_to_process.append(i)
        else:
            pages_to_process = [p for p in pages if p < len(doc)][:max_pages]

        if not pages_to_process:
            return None, "未检测到扫描页面"

        print(f"  OCR 处理 {len(pages_to_process)} 个扫描页...")

        text_parts = []
        for page_num in pages_to_process:
            page = doc[page_num]
            pix = page.get_pixmap()
            img_base64 = base64.b64encode(pix.tobytes('png')).decode()

            response = client.chat.completions.create(
                model=OCR_MODEL_NAME,
                messages=[{
                    'role': 'user',
                    'content': [
                        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{img_base64}'}},
                        {'type': 'text', 'text': OCR_PROMPT}
                    ]
                }],
                max_tokens=2000
            )

            text = response.choices[0].message.content
            if text:
                text_parts.append(f"## Page {page_num + 1}\n\n{text}")

        doc.close()

        content = "\n\n".join(text_parts)
        if not content.strip():
            return None, "OCR 提取内容为空"

        return content, None

    except Exception as e:
        return None, f"OCR 处理错误: {e}"


def extract_with_pymupdf(file_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    使用 PyMuPDF 提取文本

    PyMuPDF 特点：
    - 复杂字体编码容错（如 CID 字体）
    - 快速提取，适合大文件
    - 可检测扫描版 PDF

    Args:
        file_path: PDF 文件路径

    Returns:
        (文本内容, 错误信息)，成功时错误为 None
    """
    if not PYMUPDF_AVAILABLE:
        return None, "PyMuPDF 未安装，请运行: pip install pymupdf"

    try:
        doc = fitz.open(str(file_path))
        text_parts = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                text_parts.append(f"--- Page {page_num + 1} ---\n{text}")

        doc.close()

        content = "\n\n".join(text_parts)
        if not content.strip():
            return None, "PyMuPDF 提取内容为空（可能是扫描版 PDF）"

        return content, None

    except Exception as e:
        return None, f"PyMuPDF 解析错误: {e}"


def extract_with_pdfplumber(file_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    使用 pdfplumber 提取文本和表格

    pdfplumber 特点：
    - 保留表格结构（Markdown 格式）
    - 精确的字符定位
    - 支持中文表格提取

    Args:
        file_path: PDF 文件路径

    Returns:
        (文本内容, 错误信息)，成功时错误为 None
    """
    if not PDFPLUMBER_AVAILABLE:
        return None, "pdfplumber 未安装，请运行: pip install pdfplumber"

    try:
        with pdfplumber.open(str(file_path)) as pdf:
            text_parts = []

            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""

                # 提取表格并转换为 Markdown
                tables = page.extract_tables()
                for table in tables:
                    if table:
                        table_md = _table_to_markdown(table)
                        page_text += f"\n\n{table_md}"

                if page_text.strip():
                    text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")

            content = "\n\n".join(text_parts)
            if not content.strip():
                return None, "pdfplumber 提取内容为空"

            return content, None

    except Exception as e:
        return None, f"pdfplumber 解析错误: {e}"


def _table_to_markdown(table: list) -> str:
    """
    将表格数据转换为 Markdown 格式

    Args:
        table: pdfplumber 提取的表格数据（二维列表）

    Returns:
        Markdown 格式的表格字符串
    """
    if not table or not table[0]:
        return ""

    lines = []

    # 表头
    header = table[0]
    lines.append("| " + " | ".join(str(cell or "") for cell in header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")

    # 表体
    for row in table[1:]:
        lines.append("| " + " | ".join(str(cell or "") for cell in row) + " |")

    return "\n".join(lines)


def pdf_fallback_chain(
    file_path: Path,
    min_content_length: int = 100,
    force_ocr: bool = False,
) -> Tuple[str, str]:
    """
    PDF Fallback 解析链主函数

    优先级：
    1. OCR（扫描版 PDF 或 force_ocr=True）
    2. PyMuPDF（原生 PDF）
    3. pdfplumber（表格结构）

    Args:
        file_path: PDF 文件路径
        min_content_length: 最小有效内容长度（字符）
        force_ocr: 强制使用 OCR（用于测试）

    Returns:
        (解析内容, 使用的解析器名称)

    Raises:
        Exception: 所有解析器都失败时抛出详细错误
    """
    parsers_status = check_parsers()
    errors = []

    # 0. 强制 OCR 模式
    if force_ocr and parsers_status['ocr']:
        print("🔄 强制 OCR 解析...")
        content, error = extract_with_ocr(file_path)
        if content:
            print(f"✅ OCR 解析成功，内容长度: {len(content)}")
            return content, 'ocr'
        if error:
            errors.append(f"OCR: {error}")

    # 1. 尝试 PyMuPDF（检测是否为扫描版）
    if parsers_status['pymupdf']:
        print("🔄 尝试 PyMuPDF 解析...")
        content, error = extract_with_pymupdf(file_path)
        if content and len(content.strip()) >= min_content_length:
            print(f"✅ PyMuPDF 解析成功，内容长度: {len(content)}")
            return content, 'pymupdf'

        # PyMuPDF 检测到扫描版，尝试 OCR
        if error and "扫描版" in error and parsers_status['ocr']:
            print("  检测到扫描版 PDF，切换 OCR...")
            content, ocr_error = extract_with_ocr(file_path)
            if content and len(content.strip()) >= min_content_length:
                print(f"✅ OCR 解析成功，内容长度: {len(content)}")
                return content, 'ocr'
            if ocr_error:
                errors.append(f"OCR: {ocr_error}")

        if error:
            errors.append(f"PyMuPDF: {error}")

    # 2. 尝试 pdfplumber
    if parsers_status['pdfplumber']:
        print("🔄 尝试 pdfplumber 解析...")
        content, error = extract_with_pdfplumber(file_path)
        if content and len(content.strip()) >= min_content_length:
            print(f"✅ pdfplumber 解析成功，内容长度: {len(content)}")
            return content, 'pdfplumber'
        if error:
            errors.append(f"pdfplumber: {error}")

    # 所有解析器都失败
    error_msg = "PDF 解析失败，所有备用解析器都无法提取内容。\n"
    error_msg += "\n解析器状态:\n"
    for name, available in parsers_status.items():
        status = "已安装" if available else "未安装"
        error_msg += f"  - {name}: {status}\n"
    error_msg += "\n错误详情:\n" + "\n".join(errors)

    raise Exception(error_msg)


def get_parser_info() -> Dict[str, Any]:
    """
    获取 PDF 解析器信息（用于调试和日志）

    Returns:
        解析器状态和版本信息
    """
    info = {
        'parsers': check_parsers(),
        'versions': {},
    }

    if PYMUPDF_AVAILABLE:
        info['versions']['pymupdf'] = fitz.__version__

    if PDFPLUMBER_AVAILABLE:
        info['versions']['pdfplumber'] = pdfplumber.__version__

    return info