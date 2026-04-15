"""
PDF Fallback 解析链

当 MarkItDown (pdfminer.six) 解析失败时，自动尝试备用解析器。

解析优先级：
1. MarkItDown (pdfminer.six + OCR Plugin) → 主解析器，支持扫描版 PDF
2. PyMuPDF (fitz) → 复杂字体/布局容错
3. pdfplumber → 表格/结构化内容提取

注意：扫描版 PDF 由 MarkItDown OCR 插件处理，无需在此检测。
"""
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

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


def check_parsers() -> Dict[str, bool]:
    """
    检测 PDF 解析器可用性

    Returns:
        字典格式: {'pymupdf': bool, 'pdfplumber': bool}
    """
    return {
        'pymupdf': PYMUPDF_AVAILABLE,
        'pdfplumber': PDFPLUMBER_AVAILABLE,
    }


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
) -> Tuple[str, str]:
    """
    PDF Fallback 解析链主函数

    优先级：PyMuPDF → pdfplumber

    Args:
        file_path: PDF 文件路径
        min_content_length: 最小有效内容长度（字符）

    Returns:
        (解析内容, 使用的解析器名称)

    Raises:
        Exception: 所有解析器都失败时抛出详细错误
    """
    parsers_status = check_parsers()
    errors = []

    # 1. 尝试 PyMuPDF
    if parsers_status['pymupdf']:
        print("🔄 尝试 PyMuPDF 解析...")
        content, error = extract_with_pymupdf(file_path)
        if content and len(content.strip()) >= min_content_length:
            print(f"✅ PyMuPDF 解析成功，内容长度: {len(content)}")
            return content, 'pymupdf'
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
        status = "✅ 已安装" if available else "❌ 未安装"
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