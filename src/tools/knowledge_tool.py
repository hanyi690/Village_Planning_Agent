from typing import Any
from ..knowledge.rag import query_knowledge

def knowledge_query(query: str) -> str:
    """
    Tool 接口：对外暴露的知识检索函数，接受自然语言查询并返回检索聚合回答。
    """
    return query_knowledge(query)
