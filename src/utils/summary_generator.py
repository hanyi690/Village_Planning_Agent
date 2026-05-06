"""
维度报告摘要生成器

用于多轮对话场景，压缩长维度报告以减少 LLM token 消耗。

用途区分：
- 维度分析（Layer 2/3）：使用完整报告（reports）- 后续维度依赖需要准确分析
- 审查反馈/用户追问：使用摘要（dimension_summaries）- 不需要完整内容，减少 token
"""

import json
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    from langchain_community.chat_models import ChatOpenAI

from ..core.config import (
    FLASH_MODEL_NAME,
    FLASH_MODEL_MAX_TOKENS,
    FLASH_MODEL_TEMPERATURE,
    DASHSCOPE_API_KEY,
    DASHSCOPE_API_BASE,
    LLM_REQUEST_TIMEOUT,
    LLM_MAX_CONCURRENT,
)
from ..orchestration.state import DimensionSummary
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# Module-level constants (avoid per-call creation)
# ==========================================

# Semaphore for concurrent LLM calls (shared across all invocations)
_SUMMARY_SEMAPHORE = asyncio.Semaphore(LLM_MAX_CONCURRENT)

# Content length limit for Flash model (conservative)
_MAX_CONTENT_LENGTH = 4000


# ==========================================
# LLM instance caching (reuse across calls)
# ==========================================

_flash_llm_instance: Optional[ChatOpenAI] = None


def _get_flash_llm() -> ChatOpenAI:
    """Get cached Flash LLM instance (reuse across calls)."""
    global _flash_llm_instance
    if _flash_llm_instance is None:
        if not DASHSCOPE_API_KEY:
            raise ValueError("DASHSCOPE_API_KEY not found")
        _flash_llm_instance = ChatOpenAI(
            model=FLASH_MODEL_NAME,
            temperature=FLASH_MODEL_TEMPERATURE,
            # max_tokens is disabled to prevent incomplete JSON output
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_API_BASE,
            request_timeout=LLM_REQUEST_TIMEOUT,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        logger.debug(f"[摘要生成] Flash LLM 实例创建: model={FLASH_MODEL_NAME}, json_mode=True")
    return _flash_llm_instance


# ==========================================
# Prompt Templates
# ==========================================

DIMENSION_SUMMARY_PROMPT = """你是规划报告摘要专家。请将以下维度报告压缩为结构化摘要。

## 维度名称：{dimension_name}

## 原始报告：
{content}

## 输出要求（JSON格式）：
请严格按以下格式输出，不要添加任何其他内容：
```json
{{"summary": "核心结论和建议（200字内）", "key_points": ["要点1", "要点2", "要点3"], "metrics": {{}}}}
```

注意：
- summary: 简洁概括报告核心内容，不超过200字
- key_points: 提取3-5个关键要点，每个不超过50字
- metrics: 提取量化数据（如面积、人口、覆盖率等），无则返回空对象
- tags: 生成3-5个检索标签，便于关键词匹配

请直接输出JSON，不要添加解释。"""


# ==========================================
# Summary Generation Functions
# ==========================================

async def generate_dimension_summary(
    dimension_key: str,
    dimension_name: str,
    full_content: str,
    layer: int,
    max_retries: int = 2
) -> Optional[DimensionSummary]:
    """
    Generate a structured summary for a dimension report.

    Uses Flash model (qwen-flash) for fast, low-cost summarization.

    Args:
        dimension_key: Dimension identifier (e.g., "population_scale")
        dimension_name: Dimension display name (e.g., "人口规模分析")
        full_content: Complete dimension report content
        layer: Layer number (1-3)
        max_retries: Maximum retry attempts for JSON parsing

    Returns:
        DimensionSummary dict or None if generation fails
    """
    if not full_content or len(full_content) < 100:
        logger.debug(f"[摘要生成] {dimension_key} 内容过短，跳过摘要")
        return None

    # Truncate content if too long (Flash model has limited context)
    if len(full_content) > _MAX_CONTENT_LENGTH:
        content = full_content[:_MAX_CONTENT_LENGTH] + "\n...(内容过长已截断)"
        logger.debug(f"[摘要生成] {dimension_key} 内容截断: {len(full_content)} -> {_MAX_CONTENT_LENGTH}")
    else:
        content = full_content

    prompt = DIMENSION_SUMMARY_PROMPT.format(
        dimension_name=dimension_name,
        content=content
    )

    llm = _get_flash_llm()  # Use cached instance

    for attempt in range(max_retries):
        try:
            response = await llm.ainvoke(prompt)
            raw_output = response.content.strip()

            # Debug: log raw LLM output
            logger.debug(f"[摘要生成] {dimension_key} LLM原始输出 (长度={len(raw_output)}): {raw_output[:500]}...")

            # Extract JSON from response (handle markdown code blocks)
            json_str = _extract_json(raw_output)

            # Debug: log extraction result
            if json_str:
                logger.debug(f"[摘要生成] {dimension_key} 提取的JSON (长度={len(json_str)}): {json_str[:300]}...")
            else:
                logger.warning(f"[摘要生成] {dimension_key} _extract_json返回None, attempt={attempt + 1}")
                if attempt < max_retries - 1:
                    prompt = DIMENSION_SUMMARY_PROMPT.format(
                        dimension_name=dimension_name,
                        content=content
                    ) + "\n\n上次输出格式错误，请确保输出纯JSON格式。"
                    continue
                break

            data = json.loads(json_str)

            # Validate required fields
            if "summary" not in data:
                data["summary"] = full_content[:200] + "..."

            return DimensionSummary(
                dimension_key=dimension_key,
                dimension_name=dimension_name,
                layer=layer,
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []),
                metrics=data.get("metrics", {}),
                tags=data.get("tags", []),
                created_at=datetime.now().isoformat()
            )

        except json.JSONDecodeError as e:
            logger.warning(f"[摘要生成] {dimension_key} JSON解析失败 (attempt {attempt + 1}): {e}")
            logger.debug(f"[摘要生成] {dimension_key} JSON解析失败位置: line={e.lineno}, col={e.colno}")
            if attempt < max_retries - 1:
                # Add JSON hint for retry
                prompt = DIMENSION_SUMMARY_PROMPT.format(
                    dimension_name=dimension_name,
                    content=content
                ) + "\n\n上次输出格式错误，请确保输出纯JSON格式。"
                continue

        except KeyError as e:
            logger.error(f"[摘要生成] {dimension_key} 字段访问错误: {e}")
            break

        except Exception as e:
            logger.error(f"[摘要生成] {dimension_key} 生成失败 (type={type(e).__name__}): {e}")
            break

    # Fallback: Create basic summary from content
    logger.warning(f"[摘要生成] {dimension_key} 使用降级摘要")
    return DimensionSummary(
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        layer=layer,
        summary=full_content[:200] + "...",
        key_points=[],
        metrics={},
        tags=[dimension_name, f"Layer{layer}"],
        created_at=datetime.now().isoformat()
    )


async def generate_layer_summaries(
    reports: Dict[str, Dict[str, str]],
    layer: int,
    dimension_names: Dict[str, str]
) -> Dict[str, DimensionSummary]:
    """
    Batch generate summaries for all dimensions in a layer.

    Args:
        reports: Complete reports dict {"layer1": {...}, "layer2": {...}, "layer3": {...}}
        layer: Target layer number (1-3)
        dimension_names: Dimension key to name mapping

    Returns:
        Dict of {dimension_key: DimensionSummary}
    """
    layer_key = f"layer{layer}"
    layer_reports = reports.get(layer_key, {})

    if not layer_reports:
        logger.info(f"[摘要生成] Layer {layer} 无报告，跳过批量摘要")
        return {}

    logger.info(f"[摘要生成] 开始批量生成 Layer {layer} 摘要，维度数: {len(layer_reports)}")

    # Use module-level semaphore for global concurrency control
    async def generate_one(dim_key: str) -> tuple:
        async with _SUMMARY_SEMAPHORE:  # Shared semaphore
            content = layer_reports.get(dim_key, "")
            dim_name = dimension_names.get(dim_key, dim_key)
            summary = await generate_dimension_summary(
                dimension_key=dim_key,
                dimension_name=dim_name,
                full_content=content,
                layer=layer
            )
            return (dim_key, summary)

    tasks = [generate_one(dim_key) for dim_key in layer_reports.keys()]
    results = await asyncio.gather(*tasks)

    summaries = {dim_key: summary for dim_key, summary in results if summary}

    logger.info(f"[摘要生成] Layer {layer} 摘要生成完成: {len(summaries)}/{len(layer_reports)}")

    return summaries


def format_summary_for_llm(summary: DimensionSummary) -> str:
    """
    Format a DimensionSummary for LLM input (reduced token consumption).

    Args:
        summary: DimensionSummary dict

    Returns:
        Formatted string suitable for LLM prompt injection
    """
    parts = [f"## {summary['dimension_name']}（摘要）"]
    parts.append(summary['summary'])

    if summary.get('key_points'):
        parts.append("\n关键要点:")
        for point in summary['key_points']:
            parts.append(f"- {point}")

    if summary.get('metrics'):
        parts.append("\n数据指标:")
        for key, value in summary['metrics'].items():
            parts.append(f"- {key}: {value}")

    return "\n".join(parts)


def format_summaries_for_review(
    summaries: Dict[str, DimensionSummary],
    target_dimensions: Optional[List[str]] = None
) -> str:
    """
    Format multiple summaries for review/revision prompt.

    Args:
        summaries: Dict of {dimension_key: DimensionSummary}
        target_dimensions: Optional filter for specific dimensions

    Returns:
        Formatted string for review prompt
    """
    if target_dimensions:
        filtered = {k: summaries[k] for k in target_dimensions if k in summaries}
    else:
        filtered = summaries

    if not filtered:
        return "暂无维度摘要"

    parts = ["# 维度摘要汇总\n"]
    for dim_key, summary in filtered.items():
        parts.append(format_summary_for_llm(summary))
        parts.append("\n---\n")

    return "\n".join(parts)


def _validate_json_structure(text: str) -> bool:
    """Validate if string is a valid JSON structure."""
    if not text:
        return False
    try:
        json.loads(text)
        return True
    except json.JSONDecodeError:
        return False


def _extract_json(text: str) -> Optional[str]:
    """
    Extract JSON string from text (handles markdown code blocks and nested JSON).

    Args:
        text: Raw text potentially containing JSON

    Returns:
        Clean JSON string or None
    """
    # Handle markdown code block
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            candidate = text[start:end].strip()
            if _validate_json_structure(candidate):
                return candidate

    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            candidate = text[start:end].strip()
            if _validate_json_structure(candidate):
                return candidate

    # Try direct JSON parsing - with validation
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        if _validate_json_structure(text):
            return text

    # Extract nested JSON using brace counting
    start = text.find("{")
    if start == -1:
        return None

    brace_count = 0
    end = start
    for i, char in enumerate(text[start:], start):
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                break

    if end > start:
        candidate = text[start:end]
        if _validate_json_structure(candidate):
            return candidate

    return None


# ==========================================
# Utility Functions
# ==========================================

def get_or_generate_summary(
    state: Dict[str, Any],
    dimension_key: str
) -> Optional[DimensionSummary]:
    """
    Get existing summary or trigger generation (non-blocking).

    For synchronous contexts, returns cached summary only.
    For async contexts, use generate_dimension_summary directly.

    Args:
        state: Current state containing dimension_summaries and reports
        dimension_key: Target dimension

    Returns:
        Cached DimensionSummary or None
    """
    summaries = state.get("dimension_summaries", {})
    return summaries.get(dimension_key)


# ==========================================
# Summary Indexing Functions (Phase 1)
# ==========================================

async def index_dimension_summary(
    summary: DimensionSummary,
    task_id: str,
) -> bool:
    """
    Index a single dimension summary to ChromaDB.

    Stores summary in the same collection with doc_type="dimension_summary"
    for semantic retrieval across layers.

    Args:
        summary: DimensionSummary to index
        task_id: Task ID for session isolation

    Returns:
        True if indexed successfully, False otherwise
    """
    if not summary:
        logger.warning(f"[摘要索引] 空摘要，跳过索引")
        return False

    try:
        from ..rag.core.cache import get_vector_cache
        from langchain_core.documents import Document

        vectorstore = get_vector_cache().get_vectorstore()

        # Build content: summary + key_points + tags (for semantic search)
        content_parts = [
            f"【{summary['dimension_name']}】Layer {summary['layer']} 摘要",
            summary.get("summary", ""),
        ]
        if summary.get("key_points"):
            content_parts.append("关键要点: " + ", ".join(summary["key_points"]))
        if summary.get("tags"):
            content_parts.append("标签: " + ", ".join(summary["tags"]))

        content = "\n".join(content_parts)

        # Build metadata for filtering
        metadata = {
            "doc_type": "dimension_summary",
            "task_id": task_id,
            "layer": summary["layer"],
            "dimension": summary["dimension_key"],
            "dimension_name": summary["dimension_name"],
            "tags": summary.get("tags", []),
            "created_at": summary.get("created_at", datetime.now().isoformat()),
        }

        # Create Document and add to vectorstore
        doc = Document(page_content=content, metadata=metadata)
        vectorstore.add_documents([doc])

        logger.info(f"[摘要索引] {summary['dimension_key']} 已索引到向量库, task_id={task_id}")
        return True

    except Exception as e:
        logger.error(f"[摘要索引] {summary['dimension_key']} 索引失败: {e}")
        return False


async def index_layer_summaries_to_vectorstore(
    summaries: Dict[str, DimensionSummary],
    task_id: str,
) -> int:
    """
    Batch index all summaries from a layer to ChromaDB.

    Uses single batch add_texts call for efficiency.

    Args:
        summaries: Dict of {dimension_key: DimensionSummary}
        task_id: Task ID for session isolation

    Returns:
        Number of successfully indexed summaries
    """
    if not summaries:
        logger.info(f"[摘要索引] 无摘要需要索引")
        return 0

    logger.info(f"[摘要索引] 开始批量索引 {len(summaries)} 个摘要")

    try:
        from ..rag.core.cache import get_vector_cache

        vectorstore = get_vector_cache().get_vectorstore()

        # Build all documents in batch
        texts = []
        metadatas = []

        for dim_key, summary in summaries.items():
            if not summary:
                continue

            # Build content
            content_parts = [
                f"【{summary['dimension_name']}】Layer {summary['layer']} 摘要",
                summary.get("summary", ""),
            ]
            if summary.get("key_points"):
                content_parts.append("关键要点: " + ", ".join(summary["key_points"]))
            if summary.get("tags"):
                content_parts.append("标签: " + ", ".join(summary["tags"]))

            texts.append("\n".join(content_parts))

            # Build metadata
            metadatas.append({
                "doc_type": "dimension_summary",
                "task_id": task_id,
                "layer": summary["layer"],
                "dimension": summary["dimension_key"],
                "dimension_name": summary["dimension_name"],
                "tags": summary.get("tags", []),
                "created_at": summary.get("created_at", datetime.now().isoformat()),
            })

        # Single batch add for efficiency
        if texts:
            vectorstore.add_texts(texts=texts, metadatas=metadatas)
            logger.info(f"[摘要索引] 批量索引完成: {len(texts)}/{len(summaries)}")
            return len(texts)

        return 0

    except Exception as e:
        logger.error(f"[摘要索引] 批量索引失败: {e}")
        return 0


def build_dynamic_query(
    dim_key: str,
    layer: int,
    state: Dict[str, Any],
) -> str:
    """
    Build dynamic RAG query using summary tags from dependent dimensions.

    Args:
        dim_key: Target dimension key
        layer: Target layer (2 or 3)
        state: Current state containing dimension_summaries

    Returns:
        Enhanced query string with tags context
    """
    from ..config.dimension_metadata import get_full_dependency_chain_func, get_dimension_config

    # Get dimension name
    dim_config = get_dimension_config(dim_key)
    dim_name = dim_config.get("name", dim_key) if dim_config else dim_key

    # Get dependencies
    chain = get_full_dependency_chain_func(dim_key)
    layer1_deps = chain.get("layer1_analyses", [])
    layer2_deps = chain.get("layer2_concepts", [])

    # Collect tags from dependent summaries using set for deduplication
    summary_tags: set = set()
    dimension_summaries = state.get("dimension_summaries", {})

    for dep in layer1_deps:
        if dep in dimension_summaries:
            tags = dimension_summaries[dep].get("tags", [])
            summary_tags.update(tags)

    for dep in layer2_deps:
        if dep in dimension_summaries:
            tags = dimension_summaries[dep].get("tags", [])
            summary_tags.update(tags)

    # Limit to 5 tags
    unique_tags = list(summary_tags)[:5]

    if unique_tags:
        # Enhanced query: use tags to contextualize the search
        enhanced_query = f"针对[{','.join(unique_tags)}]特征的村庄，关于[{dim_name}]的规划标准和规范要求"
        logger.info(f"[动态Query] {dim_key}: 使用tags增强查询, tags={unique_tags}")
        return enhanced_query
    else:
        # Fallback: traditional query
        fallback_query = f"{dim_name} 规划标准 技术指标"
        logger.info(f"[动态Query] {dim_key}: 无tags，使用降级查询")
        return fallback_query


__all__ = [
    "generate_dimension_summary",
    "generate_layer_summaries",
    "format_summary_for_llm",
    "format_summaries_for_review",
    "get_or_generate_summary",
    "index_dimension_summary",
    "index_layer_summaries_to_vectorstore",
    "build_dynamic_query",
    "DimensionSummary",
]