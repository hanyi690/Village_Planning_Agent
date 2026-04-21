"""
语义维度标注器

使用 Flash 模型进行切片级语义标注，替代关键词匹配，
提供更准确的维度识别能力。
"""
from typing import List, Dict, Optional
from langchain_core.messages import HumanMessage
import asyncio
import json
import hashlib

from ...core.config import LLM_MAX_CONCURRENT
from ...core.llm_factory import create_flash_llm
from .definitions import get_dimension_definitions, DIMENSION_KEYS

# 导入统一定义（向后兼容）
DIMENSION_DEFINITIONS: Dict[str, str] = get_dimension_definitions()


class SemanticDimensionTagger:
    """Flash 模型语义维度标注器"""

    MAX_CACHE_SIZE = 1000  # 缓存上限

    def __init__(self):
        self._llm = None  # 模块级单例缓存
        self._semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENT)
        self._cache: Dict[str, List[str]] = {}  # 简单缓存

    def _evict_if_needed(self):
        """当缓存超过上限时，删除最旧的条目"""
        if len(self._cache) > self.MAX_CACHE_SIZE:
            # 删除最早的 20% 条目
            keys_to_remove = list(self._cache.keys())[:int(self.MAX_CACHE_SIZE * 0.2)]
            for key in keys_to_remove:
                del self._cache[key]

    def _get_llm(self):
        """获取缓存 LLM 实例"""
        if self._llm is None:
            self._llm = create_flash_llm()
        return self._llm

    def _get_content_hash(self, content: str) -> str:
        """计算内容哈希用于缓存"""
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _format_dimensions(self) -> str:
        """格式化维度定义列表"""
        lines = []
        for dim_key, dim_desc in DIMENSION_DEFINITIONS.items():
            lines.append(f"- {dim_key}: {dim_desc}")
        return "\n".join(lines)

    def _parse_response(self, response_text: str) -> List[str]:
        """解析 LLM 响应，提取维度列表"""
        try:
            # 尝试解析 JSON
            # 去除可能的前后标记
            text = response_text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            result = json.loads(text)
            dimensions = result.get("dimensions", [])

            # 验证维度有效性
            valid_dims = [d for d in dimensions if d in DIMENSION_DEFINITIONS]
            return valid_dims if valid_dims else ["general"]
        except (json.JSONDecodeError, KeyError):
            # 降级：尝试提取关键词
            valid_dims = []
            for dim_key in DIMENSION_DEFINITIONS:
                if dim_key in response_text:
                    valid_dims.append(dim_key)
            return valid_dims if valid_dims else ["general"]

    async def tag_chunk_async(self, content: str, top_k: int = 3) -> List[str]:
        """
        异步标注单个切片

        Args:
            content: 切片内容
            top_k: 返回最相关的维度数量

        Returns:
            维度标识列表
        """
        # 检查缓存
        content_hash = self._get_content_hash(content)
        if content_hash in self._cache:
            cached = self._cache[content_hash]
            return cached[:top_k] if len(cached) > top_k else cached

        async with self._semaphore:
            llm = self._get_llm()

            # 截取内容（避免过长）
            truncated_content = content[:800] if len(content) > 800 else content

            prompt = f"""分析以下文本片段，判断它最相关的分析维度（最多返回{top_k}个）。

可选维度：
{self._format_dimensions()}

文本片段：
{truncated_content}

请以 JSON 格式返回，例如：
{{"dimensions": ["traffic", "land_use"]}}

只返回 JSON，不要其他解释。"""

            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                dimensions = self._parse_response(response.content)

                # 缓存结果（带上限保护）
                self._evict_if_needed()
                self._cache[content_hash] = dimensions

                return dimensions[:top_k] if len(dimensions) > top_k else dimensions
            except Exception:
                # 降级：返回 general
                return ["general"]

    async def tag_chunks_batch_async(
        self, contents: List[str], top_k: int = 3
    ) -> List[List[str]]:
        """
        批量异步标注（并行执行）

        Args:
            contents: 切片内容列表
            top_k: 返回最相关的维度数量

        Returns:
            维度标识列表的列表
        """
        tasks = [self.tag_chunk_async(c, top_k) for c in contents]
        results = await asyncio.gather(*tasks)
        return results

    def tag_chunk_sync(self, content: str, top_k: int = 3) -> List[str]:
        """
        同步标注单个切片（用于兼容旧流程）

        Args:
            content: 切片内容
            top_k: 返回最相关的维度数量

        Returns:
            维度标识列表
        """
        try:
            # 在同步上下文中运行异步方法
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在异步上下文，创建新任务
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run, self.tag_chunk_async(content, top_k)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(self.tag_chunk_async(content, top_k))
        except Exception:
            return ["general"]


# 全局单例
_semantic_tagger: Optional[SemanticDimensionTagger] = None


def get_semantic_tagger() -> SemanticDimensionTagger:
    """获取语义标注器单例"""
    if _semantic_tagger is None:
        _semantic_tagger = SemanticDimensionTagger()
    return _semantic_tagger