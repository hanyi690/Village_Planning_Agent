from typing import Any

try:
    from ..knowledge.rag import query_knowledge
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

def knowledge_query(query: str) -> str:
    """
    Tool 接口：对外暴露的知识检索函数，接受自然语言查询并返回检索聚合回答。

    如果 RAG 系统不可用，返回提示信息。
    """
    if not _RAG_AVAILABLE:
        return "RAG 知识库系统当前不可用。请检查系统配置或使用其他数据源。"
    return query_knowledge(query)
