"""
File Processing Utilities - 文件处理工具模块

提供文档加载、文件类型检测、PDF 解析等基础设施。
"""

from .document_loader import (
    FileTypeDetector,
    MarkItDownLoader,
    MarkdownCleaner,
    DocToDocxConverter,
    classify_file_type,
    load_documents_from_directory,
    _create_loader,
)

from .pdf_fallback import (
    PDFFallbackParser,
    PyPDF2Extractor,
    pdfplumberExtractor,
    parse_pdf_with_fallback,
)

__all__ = [
    "FileTypeDetector",
    "MarkItDownLoader",
    "MarkdownCleaner",
    "DocToDocxConverter",
    "classify_file_type",
    "load_documents_from_directory",
    "_create_loader",
    "PDFFallbackParser",
    "PyPDF2Extractor",
    "pdfplumberExtractor",
    "parse_pdf_with_fallback",
]
