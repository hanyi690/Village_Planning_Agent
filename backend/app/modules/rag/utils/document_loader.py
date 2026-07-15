"""
Shim: re-exports document_loader for rag module internal use

Used by: backend/app/services/modules/rag/service.py
"""

from app.utils.document_loader import (
    FileTypeDetector,
    MarkItDownLoader,
    MarkdownCleaner,
    DocToDocxConverter,
    classify_file_type,
    load_documents_from_directory,
    _create_loader,
)

__all__ = [
    "FileTypeDetector",
    "MarkItDownLoader",
    "MarkdownCleaner",
    "DocToDocxConverter",
    "classify_file_type",
    "load_documents_from_directory",
    "_create_loader",
]
