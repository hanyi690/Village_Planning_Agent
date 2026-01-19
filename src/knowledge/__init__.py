"""
知识库模块 (Knowledge Module)

包含 RAG (检索增强生成) 相关功能。
"""

from .rag import (
    query_knowledge,
    add_single_document,
    add_directory_documents,
    add_texts,
    get_document_count,
    search_similar_documents,
    clear_vectorstore,
    get_vectorstore_info,
    initialize_rag_system
)

__all__ = [
    "query_knowledge",
    "add_single_document",
    "add_directory_documents",
    "add_texts",
    "get_document_count",
    "search_similar_documents",
    "clear_vectorstore",
    "get_vectorstore_info",
    "initialize_rag_system",
]
