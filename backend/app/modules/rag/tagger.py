"""
语义维度标注器

使用 Flash 模型进行切片级语义标注，替代关键词匹配，
提供更准确的维度识别能力。

来源：src/rag/metadata/semantic_tagger.py
"""
from typing import List, Dict, Optional
from langchain_core.messages import HumanMessage
import asyncio
import json
import hashlib

from ..config.document_types import get_dimension_definitions, DIMENSION_KEYS
from app.core.settings import LLM_MAX_CONCURRENT

DIMENSION_DEFINITIONS: Dict[str, str] = get_dimension_definitions()


class SemanticDimensionTagger:
    """Flash 模型语义维度标注器"""

    MAX_CACHE_SIZE = 1000

    def __init__(self):
        self._llm = None
        self._semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENT)
        self._cache: Dict[str, List[str]] = {}

    def _evict_if_needed(self):
        if len(self._cache) > self.MAX_CACHE_SIZE:
            keys_to_remove = list(self._cache.keys())[:int(self.MAX_CACHE_SIZE * 0.2)]
            for key in keys_to_remove:
                del self._cache[key]

    def _get_llm(self):
        if self._llm is None:
            from app.core.llm_factory import create_flash_llm
            self._llm = create_flash_llm()
        return self._llm

    def _get_content_hash(self, content: str) -> str:
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _format_dimensions(self) -> str:
        lines = [f"- {k}: {v}" for k, v in DIMENSION_DEFINITIONS.items()]
        return "\n".join(lines)

    def _parse_response(self, response_text: str) -> List[str]:
        try:
            text = response_text.strip()
            if text.startswith("```json"): text = text[7:]
            if text.startswith("```"): text = text[3:]
            if text.endswith("```"): text = text[:-3]
            text = text.strip()
            result = json.loads(text)
            dimensions = result.get("dimensions", [])
            valid_dims = [d for d in dimensions if d in DIMENSION_DEFINITIONS]
            return valid_dims if valid_dims else ["general"]
        except (json.JSONDecodeError, KeyError):
            valid_dims = [d for d in DIMENSION_DEFINITIONS if d in response_text]
            return valid_dims if valid_dims else ["general"]

    async def tag_chunk_async(self, content: str, top_k: int = 3) -> List[str]:
        content_hash = self._get_content_hash(content)
        if content_hash in self._cache:
            cached = self._cache[content_hash]
            return cached[:top_k] if len(cached) > top_k else cached

        async with self._semaphore:
            llm = self._get_llm()
            truncated = content[:800] if len(content) > 800 else content
            prompt = f"""分析以下文本片段，判断它最相关的分析维度（最多返回{top_k}个）。

可选维度：
{self._format_dimensions()}

文本片段：
{truncated}

请以 JSON 格式返回，例如：
{{"dimensions": ["traffic", "land_use"]}}

只返回 JSON，不要其他解释。"""
            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                dimensions = self._parse_response(response.content)
                self._evict_if_needed()
                self._cache[content_hash] = dimensions
                return dimensions[:top_k] if len(dimensions) > top_k else dimensions
            except Exception:
                return ["general"]

    async def tag_chunks_batch_async(self, contents: List[str], top_k: int = 3) -> List[List[str]]:
        tasks = [self.tag_chunk_async(c, top_k) for c in contents]
        return await asyncio.gather(*tasks)

    def tag_chunk_sync(self, content: str, top_k: int = 3) -> List[str]:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.tag_chunk_async(content, top_k))
                    return future.result()
            else:
                return loop.run_until_complete(self.tag_chunk_async(content, top_k))
        except Exception:
            return ["general"]


_semantic_tagger: Optional[SemanticDimensionTagger] = None


def get_semantic_tagger() -> SemanticDimensionTagger:
    if _semantic_tagger is None:
        _semantic_tagger = SemanticDimensionTagger()
    return _semantic_tagger


__all__ = ["SemanticDimensionTagger", "get_semantic_tagger"]