"""知识检索工具 - 使用新 RAG 模块"""

from typing import Any
from ..rag.core.tools import knowledge_search_tool


def knowledge_query(query: str) -> str:
    """
    Tool 接口：对外暴露的知识检索函数，接受自然语言查询并返回检索聚合回答。
    
    Args:
        query: 查询问题或关键词
        
    Returns:
        匹配的文档片段列表
    """
    return knowledge_search_tool.invoke({
        "query": query,
        "top_k": 5,
        "context_mode": "standard"
    })