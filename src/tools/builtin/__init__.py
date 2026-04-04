"""
内置工具模块

提供核心工具实现，简化版注册机制。
"""

from typing import Dict, Any

from ...utils.logger import get_logger

logger = get_logger(__name__)


def knowledge_search_tool(context: Dict[str, Any]) -> str:
    """
    RAG 知识检索工具

    从知识库中检索相关信息，支持专业数据和法规条文的查询。

    Args:
        context: 包含 query 和可选参数的上下文字典
            - query: 查询字符串（必需）
            - top_k: 返回结果数量（可选，默认 5）
            - context_mode: 上下文模式（可选，默认 "standard"）

    Returns:
        格式化的知识检索结果
    """
    try:
        from ...rag.core.tools import knowledge_search_tool as rag_search_tool

        query = context.get("query", "")
        top_k = context.get("top_k", 5)
        context_mode = context.get("context_mode", "standard")

        if not query:
            return "## 知识检索错误\n\n错误: 缺少查询参数 'query'"

        result = rag_search_tool.invoke({
            "query": query,
            "top_k": top_k,
            "context_mode": context_mode
        })

        logger.info(f"[ToolRegistry] 知识检索成功: query='{query[:50]}...'")
        return result

    except Exception as e:
        logger.error(f"[ToolRegistry] 知识检索失败: {e}")
        return f"## 知识检索错误\n\n错误: {str(e)}"


def web_search_tool(context: Dict[str, Any]) -> str:
    """
    网络搜索工具

    从互联网搜索实时信息，支持新闻、政策、技术数据等查询。

    Args:
        context: 包含查询参数的上下文字典
            - query: 搜索查询字符串（必需）
            - backend: 搜索后端（可选，默认"tavily"）
            - num_results: 返回结果数量（可选，默认 5）

    Returns:
        格式化的网络搜索结果
    """
    try:
        from ..search_tool import get_search_backend, format_search_results

        query = context.get("query", "")
        backend = context.get("backend", "tavily")
        num_results = context.get("num_results", 5)

        if not query:
            return "## 网络搜索错误\n\n错误：缺少查询参数 'query'"

        logger.info(f"[web_search] 执行搜索：query='{query[:50]}...', backend={backend}")

        search_backend = get_search_backend(backend)
        results = search_backend.search(query, num_results=num_results)

        return format_search_results(results, max_results=num_results)

    except ImportError as e:
        logger.error(f"[web_search] 搜索模块导入失败：{e}")
        return f"## 网络搜索错误\n\n错误：搜索模块未正确安装 - {str(e)}"
    except ValueError as e:
        logger.error(f"[web_search] 配置错误：{e}")
        return f"## 网络搜索错误\n\n错误：{str(e)}"
    except Exception as e:
        logger.error(f"[web_search] 搜索失败：{e}")
        return f"## 网络搜索错误\n\n错误：{str(e)}"


__all__ = [
    "knowledge_search_tool",
    "web_search_tool",
]