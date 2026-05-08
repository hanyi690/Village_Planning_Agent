"""
知识库检索工具

迁移来源：src/rag/core/tools.py

核心功能：
1. 知识检索（支持上下文模式 + 元数据过滤）
2. 文档概览（执行摘要 + 章节列表）
3. 章节内容（三级详情）
4. 关键要点搜索
5. 技术指标检索

使用 LangChain @tool 装饰器，并注册到 ToolRegistry。
"""

import re
from pathlib import Path
from typing import Optional, Dict, List, TypedDict, Any
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_core.tools import Tool, tool

from ..registry import ToolRegistry
from app.utils.logger import get_logger
from ...utils.context_manager import get_context_manager
from ...core.settings import DEFAULT_TOP_K

logger = get_logger(__name__)

# ==================== 常量定义 ====================

CONTENT_PREVIEW_LENGTH = 1000


@dataclass
class MetadataFilterParams:
    """元数据过滤参数"""
    dimension: Optional[str] = None
    terrain: Optional[str] = None
    doc_type: Optional[str] = None
    regions: Optional[str] = None
    task_id: Optional[str] = None
    include_summaries: bool = False


def _parse_comma_separated(value: str) -> List[str]:
    """解析逗号分隔字符串为列表（去除空白项）"""
    return [s.strip() for s in value.split(",") if s.strip()]


class KnowledgeSource(TypedDict):
    """知识切片结构化数据"""
    source: str
    page: int
    doc_type: str
    content: str


def extract_sources_from_documents(docs: List[Document]) -> List[KnowledgeSource]:
    """
    从 Document 对象提取知识切片信息

    Args:
        docs: LangChain Document 对象列表

    Returns:
        结构化的 KnowledgeSource 列表
    """
    sources = []
    for doc in docs:
        content = doc.page_content[:CONTENT_PREVIEW_LENGTH]
        if len(doc.page_content) > CONTENT_PREVIEW_LENGTH:
            content += "..."

        sources.append({
            "source": doc.metadata.get("source", "未知来源"),
            "page": doc.metadata.get("page", 0) or 0,
            "doc_type": doc.metadata.get("type", ""),
            "content": content,
        })
    return sources


# ==================== 辅助函数 ====================

def get_vectorstore():
    """获取向量数据库（使用 RagService 单例）"""
    from ...services.rag_service import RagService
    return RagService.get_instance().vectorstore


def format_error(message: str, error: Exception) -> str:
    """格式化错误消息"""
    return f"❌ {message}时发生错误: {error}"


def _build_metadata_filter(params: MetadataFilterParams) -> Optional[Dict]:
    """构建 ChromaDB 过滤器（从数据类）"""
    filter_dict = {}

    if params.include_summaries and params.task_id:
        filter_dict["$or"] = [
            {"doc_type": "policy"},
            {"doc_type": "dimension_summary", "task_id": params.task_id}
        ]
        return filter_dict

    # ChromaDB 不支持 $regex，dimension 和 regions 过滤已移除
    # 依赖语义相似度检索即可满足需求

    if params.terrain and params.terrain != "all":
        filter_dict["terrain"] = params.terrain

    if params.doc_type:
        filter_dict["doc_type"] = params.doc_type

    if params.task_id:
        filter_dict["task_id"] = params.task_id

    return filter_dict if filter_dict else None


def _get_vector_cache():
    """获取向量缓存"""
    from ...services.vector_store import get_vector_cache
    return get_vector_cache()


# ==================== 工具函数 ====================

def list_available_documents(query: str = "") -> str:
    """
    列出知识库中所有可用文档

    **何时使用：**
    - 任务开始时，了解有哪些资料
    - 用户询问"你有什么知识库"、"你能做什么"时

    **返回：**
    - 文档名称、类型、切片数量、内容预览
    """
    try:
        cm = get_context_manager()
        cm._ensure_loaded()

        if not cm.doc_index:
            return "⚠️  知识库中没有文档"

        lines = ["【可用文档列表】\n"]

        for idx, (source, doc_idx) in enumerate(cm.doc_index.items(), 1):
            preview = doc_idx.chunks_info[0]['content_preview'] if doc_idx.chunks_info else 'N/A'
            lines.append(
                f"{idx}. {source}\n"
                f"   类型: {doc_idx.doc_type}\n"
                f"   切片数: {len(doc_idx.chunks_info)}\n"
                f"   预览: {preview}\n"
            )

        return "\n".join(lines)

    except Exception as e:
        return format_error("列出文档", e)


def get_document_overview(source: str, include_chapters: bool = True) -> str:
    """
    获取文档概览（执行摘要 + 可选章节列表）

    **何时使用：**
    - 快速了解文档核心内容
    - 决定是否需要深入阅读
    - 对比多个文档的主题

    **参数：**
    - source (str | required): 文档名称（文件名）
    - include_chapters (bool | optional): 是否包含章节列表，默认 True

    **返回：**
    - 执行摘要（200 字）
    - 章节标题列表（如果 include_chapters=True）
    """
    try:
        cm = get_context_manager()
        result = cm.get_executive_summary(source)

        if "error" in result:
            return f"❌ {result['error']}"

        lines = [
            f"【文档概览】\n",
            f"来源: {result['source']}\n",
            f"类型: {result.get('doc_type', '未知')}\n\n",
        ]

        if result.get("executive_summary"):
            lines.append(f"**执行摘要**\n{result['executive_summary']}\n")
        else:
            lines.append(f"⚠️  该文档尚未生成摘要\n")

        if include_chapters:
            chapters_result = cm.list_chapter_summaries(source)
            if chapters_result.get("chapters"):
                lines.append(f"\n**章节列表**\n")
                lines.extend(f"{idx}. {chapter['title']}\n" for idx, chapter in enumerate(chapters_result['chapters'], 1))

        return "\n".join(lines)

    except Exception as e:
        return format_error("获取文档概览", e)


def get_chapter_content(source: str, chapter_pattern: str, detail_level: str = "medium") -> str:
    """
    获取章节内容（支持三级详情）

    **何时使用：**
    - 了解特定章节内容时
    - 根据信息需求选择合适的详细程度
    - 快速浏览或深度阅读特定章节

    **参数：**
    - source (str | required): 文档名称（文件名）
    - chapter_pattern (str | required): 章节标题关键词（支持部分匹配）
    - detail_level (str | optional): 详细程度
      - "summary": 仅摘要（100-200 字）- 最快
      - "medium": 摘要 + 关键要点（默认）
      - "full": 完整章节内容 - 最详细

    **返回：**
    - 根据 detail_level 返回不同详细程度的章节内容
    """
    try:
        cm = get_context_manager()

        if detail_level == "summary":
            result = cm.get_chapter_summary(source, chapter_pattern)
            if "error" in result:
                return f"❌ {result['error']}"
            return f"【知识片段 1】\n来源: {result['source']}\n位置: 第1 页\n内容:\n{result['summary']}"

        elif detail_level == "medium":
            result = cm.get_chapter_summary(source, chapter_pattern)
            if "error" in result:
                return f"❌ {result['error']}"

            lines = [
                f"【知识片段 1】\n",
                f"来源: {result['source']}\n",
                f"位置: 第1 页\n",
                f"内容:\n**摘要**\n{result['summary']}\n\n",
                f"**关键要点**\n"
            ]
            lines.extend(f"  • {point}" for point in result.get('key_points', []))
            return "\n".join(lines)

        elif detail_level == "full":
            result = cm.get_chapter_by_header(source, chapter_pattern)
            if "error" in result:
                return f"❌ {result['error']}"
            return f"【知识片段 1】\n来源: {result['source']}\n位置: 第1 页\n内容:\n{result['content']}"

        else:
            return f"❌ 无效的 detail_level: {detail_level}。请使用 'summary', 'medium', 或 'full'"

    except Exception as e:
        return format_error("获取章节内容", e)


def search_knowledge(
    query: str,
    top_k: int = 5,
    context_mode: str = "standard",
    dimension: Optional[str] = None,
    terrain: Optional[str] = None,
    doc_type: Optional[str] = None,
    regions: Optional[str] = None,
    task_id: Optional[str] = None,
    include_summaries: bool = False,
) -> str:
    """
    检索知识库（支持多种上下文模式 + 元数据过滤 + 会话隔离）

    **何时使用：**
    - 需要查找特定信息时
    - 获取相关片段的上下文
    - 探索知识库中的相关内容
    - 按地形/文档类型过滤检索
    - 检索摘要索引（Layer间关联检索）

    **参数：**
    - query (str | required): 查询问题或关键词
    - top_k (int | optional): 返回片段数，默认 5，范围 3-10
    - context_mode (str | optional): 上下文模式
      - "minimal": 仅匹配片段（最少 Token）- 最快
      - "standard": 片段 + 短上下文（300 字，默认）
      - "expanded": 片段 + 长上下文（500 字）- 最详细
    - dimension (str | optional): 维度标识（已废弃，ChromaDB 不支持 $regex）
    - terrain (str | optional): 地形类型过滤（"mountain", "plain", "hill", "all"）
    - doc_type (str | optional): 文档类型过滤（"policy", "standard", "case", "dimension_summary"）
    - regions (str | optional): 地区名称（已废弃，ChromaDB 不支持 $regex）
    - task_id (str | optional): 任务ID（会话隔离，检索摘要时必须提供）
    - include_summaries (bool | optional): 是否启用混合检索模式（公共政策 + 本任务摘要）

    **返回：**
    - 匹配的文档片段列表，包含来源、位置、内容
    """
    try:
        # 构建缓存参数（包含过滤条件）
        context_params = {
            "top_k": top_k,
            "context_mode": context_mode,
            "dimension": dimension,
            "terrain": terrain,
            "doc_type": doc_type,
            "regions": regions,
            "task_id": task_id,
            "include_summaries": include_summaries,
        }

        # 尝试从缓存获取
        cache = _get_vector_cache()
        cached = None
        if cache:
            cached = cache.get_cached_query(query, context_params)

        if cached is not None:
            results = cached
        else:
            db = get_vectorstore()

            # 构建 metadata filter（支持会话隔离和混合检索）
            filter_params = MetadataFilterParams(
                dimension=dimension,
                terrain=terrain,
                doc_type=doc_type,
                regions=regions,
                task_id=task_id,
                include_summaries=include_summaries,
            )
            filter_dict = _build_metadata_filter(filter_params)

            # 使用 filter 进行检索
            if filter_dict:
                results: list[Document] = db.similarity_search(
                    query,
                    k=top_k,
                    filter=filter_dict
                )
            else:
                results: list[Document] = db.similarity_search(query, k=top_k)

            # 缓存检索结果
            if results and cache:
                cache.cache_query_result(query, results, context_params)

        if not results:
            return "⚠️  知识库中未找到相关信息。"

        context_chars_map = {"minimal": 0, "standard": 300, "expanded": 500}
        context_chars = context_chars_map.get(context_mode, 300)

        fragments = []

        for idx, doc in enumerate(results, 1):
            source = doc.metadata.get("source", "未知来源")
            page = doc.metadata.get("page", doc.metadata.get("paragraph", "未知"))
            doc_type = doc.metadata.get("type", "未知类型")
            start_index = doc.metadata.get("start_index", 0)

            fragment = [f"【知识片段 {idx}】", f"来源: {source}", f"位置: 第{page} {doc_type}"]

            if context_mode == "minimal":
                fragment.append(f"内容: {doc.page_content}")
            elif context_chars > 0 and start_index > 0:
                try:
                    cm = get_context_manager()
                    ctx = cm.get_context_around_chunk(source, start_index, context_chars)

                    if "error" not in ctx and (ctx.get('before') or ctx.get('after')):
                        if ctx['before']:
                            fragment.append(f"\n前文:\n{ctx['before'][:200]}...")
                        fragment.append(f"\n核心内容:\n{doc.page_content}")
                        if ctx['after']:
                            fragment.append(f"\n后文:\n{ctx['after'][:200]}...")
                    else:
                        fragment.append(f"\n内容:\n{doc.page_content}")
                except Exception:
                    fragment.append(f"\n内容:\n{doc.page_content}")
            else:
                fragment.append(f"\n内容:\n{doc.page_content}")

            fragments.append("\n".join(fragment))

        return "\n\n".join(fragments)

    except Exception as e:
        return format_error("查询知识库", e)


def search_key_points(query: str, sources: Optional[list[str]] = None) -> str:
    """
    搜索关键要点（预先提取的核心信息）

    **何时使用：**
    - 快速查找关键信息（比全文检索更精确）
    - 需要"要点式"答案时
    - 探索文档的核心观点

    **参数：**
    - query (str | required): 搜索关键词
    - sources (list[str] | optional): 限制搜索的文档列表，默认搜索所有文档

    **返回：**
    - 匹配的要点列表，包含来源文档和具体内容
    """
    try:
        # 兼容旧的调用方式
        if isinstance(query, dict):
            query = query.get("query", "")
            sources = query.get("sources")

        cm = get_context_manager()

        sources_list = None
        if sources:
            sources_list = [sources] if isinstance(sources, str) else sources

        result = cm.search_key_points(query, sources_list)

        if result['total_matches'] == 0:
            return f"⚠️  未找到包含 '{query}' 的要点"

        lines = [
            f"【关键要点搜索结果】",
            f"查询: {result['query']}",
            f"匹配数量: {result['total_matches']}\n"
        ]

        for match in result['matches']:
            lines.append(f"📄 {match['source']}\n   {match['point']}\n")

        return "\n".join(lines)

    except Exception as e:
        return format_error("搜索要点", e)


def get_full_document(source: str) -> str:
    """
    获取完整文档内容

    **何时使用：**
    - 需要深度理解完整规划时
    - 需要查看文档的整体结构和全貌
    - 需要引用完整文档内容时

    **参数：**
    - source (str | required): 文档名称（文件名）

    **返回：**
    - 完整文档内容和元数据（类型、切片数、内容长度等）

    **注意：**
    - 文档可能很长（数万字），会消耗大量 Token
    - 谨慎使用，优先考虑 get_document_overview 或 get_chapter_content
    """
    try:
        cm = get_context_manager()
        result = cm.get_full_document(source)

        if "error" in result:
            return f"❌ {result['error']}"

        return (
            f"【完整文档】\n"
            f"来源: {result['source']}\n"
            f"类型: {result['doc_type']}\n"
            f"总切片数: {result['total_chunks']}\n"
            f"内容长度: {len(result['content'])} 字符\n\n"
            f"内容:\n{result['content']}"
        )

    except Exception as e:
        return format_error("获取文档", e)


# ==================== LangChain Tools 定义 ====================

def create_tool(name: str, func, description_template: str) -> Tool:
    """创建工具的辅助函数"""
    return Tool(name=name, func=func, description=description_template)


document_list_tool = Tool(
    name="list_documents",
    func=list_available_documents,
    description="列出知识库中所有可用的文档及其基本信息。在使用其他文档工具前，建议先使用此工具查看有哪些文档可用。",
)


@tool
def document_overview_tool(source: str, include_chapters: bool = True) -> str:
    """
    获取文档概览（执行摘要 + 可选章节列表）。

    快速了解文档核心内容，包含 200 字执行摘要和可选的章节列表。

    Args:
        source: 文档名称（文件名，必需）
        include_chapters: 是否包含章节列表（可选，默认 true）

    Returns:
        执行摘要和可选的章节列表
    """
    return get_document_overview(source, include_chapters)


@tool
def chapter_content_tool(source: str, chapter_pattern: str, detail_level: str = "medium") -> str:
    """
    获取章节内容（支持三级详情）。

    根据需求获取不同详细程度的章节内容，从摘要到完整内容。

    Args:
        source: 文档名称（文件名，必需）
        chapter_pattern: 章节标题关键词（必需，支持部分匹配）
        detail_level: 详细程度（可选，默认 "medium")
            - "summary": 仅摘要（100-200 字）
            - "medium": 摘要 + 关键要点（默认）
            - "full": 完整章节内容

    Returns:
        根据 detail_level 返回不同详细程度的章节内容
    """
    return get_chapter_content(source, chapter_pattern, detail_level)


@tool
def knowledge_search_tool(
    query: str,
    top_k: int = 5,
    context_mode: str = "standard",
    dimension: str = "",
    doc_type: str = "",
    regions: str = "",
) -> str:
    """
    检索知识库（支持多种上下文模式 + 元数据过滤）。

    基于查询检索相关文档片段，支持按维度、文档类型、地区过滤。

    Args:
        query: 查询问题或关键词（必需）
        top_k: 返回片段数（可选，默认 5，范围 3-10）
        context_mode: 上下文模式（可选，默认 "standard")
            - "minimal": 仅匹配片段（最少 Token）
            - "standard": 片段 + 短上下文（300 字，默认）
            - "expanded": 片段 + 长上下文（500 字）
        dimension: 维度标识（可选，如 "traffic", "land_use")
        doc_type: 文档类型（可选，如 "policy", "standard", "case")
        regions: 地区名称（可选，逗号分隔，如 "梅州,广东")

    Returns:
        匹配的文档片段列表，包含来源、位置、内容
    """
    return search_knowledge(
        query=query,
        top_k=top_k,
        context_mode=context_mode,
        dimension=dimension if dimension else None,
        doc_type=doc_type if doc_type else None,
        regions=regions if regions else None,
    )


@tool
def key_points_search_tool(query: str, sources: Optional[str] = None) -> str:
    """
    搜索关键要点（预先提取的核心信息）。

    在所有文档的关键要点中搜索关键词，比全文检索更精确。

    Args:
        query: 搜索关键词（必需）
        sources: 限制搜索的文档列表（可选，可以是单个文档名或用逗号分隔的多个文档名）

    Returns:
        匹配的要点列表，包含来源文档和具体内容
    """
    sources_list = _parse_comma_separated(sources) if sources else None

    cm = get_context_manager()
    result = cm.search_key_points(query, sources_list)

    if result['total_matches'] == 0:
        return f"⚠️  未找到包含 '{query}' 的要点"

    lines = [
        f"【关键要点搜索结果】",
        f"查询: {result['query']}",
        f"匹配数量: {result['total_matches']}\n"
    ]

    for match in result['matches']:
        lines.append(f"📄 {match['source']}\n   {match['point']}\n")

    return "\n".join(lines)


@tool
def full_document_tool(source: str) -> str:
    """
    获取完整文档内容。

    获取文档的完整内容和元数据。

    Args:
        source: 文档名称（文件名，必需）

    Returns:
        完整文档内容和元数据（类型、切片数、内容长度等）

    注意：
        文档可能很长（数万字），会消耗大量 Token。谨慎使用，优先考虑 get_document_overview 或 get_chapter_content。
    """
    return get_full_document(source)


@tool
def check_technical_indicators(
    query: str,
    dimension: str = "",
    terrain: str = "all"
) -> str:
    """
    检索技术指标和规范标准（为未来元数据过滤检索预留）。

    供 Layer 3 Agent 调用，专门用于检索具体的技术参数和硬性标准。
    当前版本：简单封装 knowledge_search_tool
    未来版本：基于 metadata 进行维度和地形过滤

    Args:
        query: 检索查询（如"道路宽度标准"、"绿地率要求")
        dimension: 维度标识（如 "traffic", "land_use", "infrastructure")
        terrain: 地形类型（"mountain", "plain", "hill", "all")

    Returns:
        检索到的技术指标和规范内容

    Example:
        >>> check_technical_indicators("道路红线宽度", dimension="traffic", terrain="mountain")
    """
    enhanced_query = f"{dimension} {query}" if dimension else query

    result = search_knowledge(
        query=enhanced_query,
        top_k=5,
        context_mode="expanded"
    )

    if dimension or terrain != "all":
        result = f"【筛选条件】维度: {dimension or '全部'}, 地形: {terrain}\n\n{result}"

    return result


# ==================== 工具列表 ====================

PLANNING_TOOLS = [
    document_list_tool,
    document_overview_tool,
    key_points_search_tool,
    knowledge_search_tool,
    chapter_content_tool,
    full_document_tool,
    check_technical_indicators,
]

# 向后兼容：别名
planning_knowledge_tool = knowledge_search_tool
executive_summary_tool = document_overview_tool
chapter_summaries_list_tool = document_overview_tool
chapter_summary_tool = chapter_content_tool
chapter_context_tool = chapter_content_tool
context_around_tool = knowledge_search_tool


# ==================== 旧版工具（兼容性）====================

def retrieve_planning_knowledge(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    with_context: bool = True,
    context_chars: int = 300
) -> str:
    """检索乡村规划相关知识（兼容旧版）"""
    if not with_context or context_chars == 0:
        context_mode = "minimal"
    elif context_chars >= 500:
        context_mode = "expanded"
    else:
        context_mode = "standard"

    return search_knowledge(query, top_k, context_mode)


@tool(response_format="content_and_artifact")
def retrieve_knowledge_detailed(query: str) -> tuple[str, list[Document]]:
    """检索知识（Agentic RAG 模式，兼容旧版）"""
    db = get_vectorstore()
    retrieved_docs = db.similarity_search(query, k=DEFAULT_TOP_K)

    serialized = "\n\n".join(
        f"来源: {doc.metadata.get('source', '未知')}\n"
        f"位置: {doc.metadata.get('page', doc.metadata.get('paragraph', '未知'))}\n"
        f"内容: {doc.page_content}"
        for doc in retrieved_docs
    )

    return serialized, retrieved_docs


# ==================== ToolRegistry 注册 ====================

# 注册为 ToolRegistry 工具（供 LangGraph Agent 使用）
@ToolRegistry.register("knowledge_search")
def knowledge_search_registry_wrapper(context: Dict[str, Any]) -> str:
    """
    ToolRegistry 包装版知识检索

    Args:
        context: 包含 query 和可选参数的上下文字典
            - query: 查询字符串（必需）
            - top_k: 返回结果数量（可选，默认 5）
            - context_mode: 上下文模式（可选，默认 "standard")

    Returns:
        格式化的知识检索结果
    """
    query = context.get("query", "")
    top_k = context.get("top_k", 5)
    context_mode = context.get("context_mode", "standard")

    if not query:
        return "## 知识检索错误\n\n错误: 缺少查询参数 'query'"

    return search_knowledge(query, top_k, context_mode)


@ToolRegistry.register("document_overview")
def document_overview_registry_wrapper(context: Dict[str, Any]) -> str:
    """
    ToolRegistry 包装版文档概览

    Args:
        context: 包含 source 和可选参数的上下文字典
            - source: 文档名称（必需）
            - include_chapters: 是否包含章节列表（可选，默认 True）

    Returns:
        文档概览结果
    """
    source = context.get("source", "")
    include_chapters = context.get("include_chapters", True)

    if not source:
        return "## 文档概览错误\n\n错误: 缺少参数 'source'"

    return get_document_overview(source, include_chapters)


@ToolRegistry.register("chapter_content")
def chapter_content_registry_wrapper(context: Dict[str, Any]) -> str:
    """
    ToolRegistry 包装版章节内容

    Args:
        context: 包含参数的上下文字典
            - source: 文档名称（必需）
            - chapter_pattern: 章节标题关键词（必需）
            - detail_level: 详细程度（可选，默认 "medium")

    Returns:
        章节内容结果
    """
    source = context.get("source", "")
    chapter_pattern = context.get("chapter_pattern", "")
    detail_level = context.get("detail_level", "medium")

    if not source or not chapter_pattern:
        return "## 章节内容错误\n\n错误: 缺少参数 'source' 或 'chapter_pattern'"

    return get_chapter_content(source, chapter_pattern, detail_level)


__all__ = [
    "PLANNING_TOOLS",
    "knowledge_search_tool",
    "document_overview_tool",
    "chapter_content_tool",
    "key_points_search_tool",
    "full_document_tool",
    "check_technical_indicators",
    "document_list_tool",
    "retrieve_planning_knowledge",
    "retrieve_knowledge_detailed",
    # ToolRegistry wrappers
    "knowledge_search_registry_wrapper",
    "document_overview_registry_wrapper",
    "chapter_content_registry_wrapper",
]