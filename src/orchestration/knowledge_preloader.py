"""
知识预加载器 - 优化Layer 1并行处理

在Layer 1的12维度并行分析前，一次性加载所有文档的章节摘要，
避免各个维度节点重复检索，大幅提升并行性能。

使用场景：
- Layer 1现状分析：预加载所有文档摘要，12维度并行查找
- 性能优化：避免重复检索，提升50%响应速度

核心功能：
- preload_all_knowledge(): 并行获取所有文档摘要
- get_dimension_knowledge(): 按维度快速检索预加载知识
"""

from __future__ import annotations

import asyncio
from typing import Dict, List

from ..core.state_builder import VillagePlanningState
from ..utils.logger import get_logger

# RAG imports (conditional)
try:
    from ..rag.core.summarization import DocumentSummarizer
    from ..rag.core.context_manager import DocumentContextManager
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    DocumentSummarizer = None  # type: ignore
    DocumentContextManager = None  # type: ignore

logger = get_logger(__name__)


class KnowledgePreloader:
    """
    知识预加载器

    在Layer 1的12维度并行分析前，一次性加载所有文档的章节摘要，
    避免各个维度节点重复检索，大幅提升并行性能。

    使用方法：
        preloader = KnowledgePreloader()
        knowledge_map = await preloader.preload_all_knowledge(state)

        # 在各个维度节点中快速查找
        location_knowledge = preloader.get_dimension_knowledge("location")
    """

    def __init__(self):
        """初始化知识预加载器"""
        self.summary_system: DocumentSummarizer | None = None
        self.context_manager: DocumentContextManager | None = None
        self._knowledge_map: Dict[str, List[dict]] = {}

        # 初始化RAG组件
        if RAG_AVAILABLE:
            try:
                self.summary_system = DocumentSummarizer()
                self.context_manager = DocumentContextManager()
                logger.info("[知识预加载] RAG组件初始化成功")
            except Exception as e:
                logger.warning(f"[知识预加载] RAG组件初始化失败: {e}")
        else:
            logger.warning("[知识预加载] RAG系统不可用，预加载功能将被禁用")

    async def preload_all_knowledge(
        self,
        state: VillagePlanningState
    ) -> Dict[str, List[dict]]:
        """
        预加载所有相关知识

        Args:
            state: 当前规划状态

        Returns:
            知识映射字典 {dimension_key: [knowledge_data, ...]}
        """
        if not RAG_AVAILABLE or self.context_manager is None or self.summary_system is None:
            logger.warning("[知识预加载] RAG系统不可用，跳过预加载")
            return {}

        try:
            # 1. 获取所有可用文档
            docs = self.context_manager.list_available_documents()

            if not docs:
                logger.info("[知识预加载] 暂无可用文档")
                return {}

            logger.info(f"[知识预加载] 开始预加载 {len(docs)} 个文档的知识...")

            # 2. 并行获取所有文档的章节摘要
            tasks = [
                self._get_document_summary(doc["source"])
                for doc in docs
            ]

            summaries = await asyncio.gather(*tasks, return_exceptions=True)

            # 3. 构建知识映射
            self._knowledge_map = self._build_knowledge_map(docs, summaries)

            # 4. 存入state，供后续节点使用
            state["knowledge_map"] = self._knowledge_map

            # 5. 记录统计信息
            total_knowledge = sum(len(v) for v in self._knowledge_map.values())
            logger.info(f"[知识预加载] 完成！共 {len(self._knowledge_map)} 个维度，{total_knowledge} 条知识")

            return self._knowledge_map

        except Exception as e:
            logger.error(f"[知识预加载] 预加载失败: {e}")
            return {}

    async def _get_document_summary(self, source: str) -> dict:
        """
        获取单个文档的摘要信息

        Args:
            source: 文档来源标识

        Returns:
            文档摘要字典
        """
        if self.summary_system is None:
            return {"source": source, "error": "RAG系统不可用"}

        try:
            # 获取章节摘要列表
            chapter_summaries = self.summary_system.list_chapter_summaries(source)

            # 获取执行摘要
            executive_summary = self.summary_system.get_executive_summary(source)

            return {
                "source": source,
                "executive_summary": executive_summary.get("executive_summary", ""),
                "chapters": chapter_summaries.get("chapters", []),
                "key_points": executive_summary.get("key_points", [])
            }
        except Exception as e:
            logger.warning(f"[知识预加载] 加载 {source} 摘要失败: {e}")
            return {"source": source, "error": str(e)}

    def _build_knowledge_map(
        self,
        docs: List[dict],
        summaries: List[dict]
    ) -> Dict[str, List[dict]]:
        """
        构建知识映射字典

        将文档摘要按维度分类，方便各个维度节点快速查找

        Args:
            docs: 文档列表
            summaries: 文档摘要列表

        Returns:
            维度 -> 知识列表的映射
        """
        knowledge_map: Dict[str, List[dict]] = {
            "location": [],
            "socio_economic": [],
            "villager_wishes": [],
            "superior_planning": [],
            "natural_environment": [],
            "land_use": [],
            "traffic": [],
            "public_services": [],
            "infrastructure": [],
            "ecological_green": [],
            "architecture": [],
            "historical_culture": [],
        }

        # 维度关键词映射
        dimension_keywords = {
            "location": ["区位", "位置", "地理", "区域"],
            "socio_economic": ["经济", "产业", "人口", "收入"],
            "villager_wishes": ["村民", "意愿", "诉求", "参与"],
            "superior_planning": ["上位", "规划", "政策", "法规"],
            "natural_environment": ["自然", "环境", "地形", "气候"],
            "land_use": ["用地", "土地", "空间", "布局"],
            "traffic": ["交通", "道路", "出行", "运输"],
            "public_services": ["服务", "设施", "配套", "民生"],
            "infrastructure": ["基础设施", "管网", "市政", "水电"],
            "ecological_green": ["生态", "环境", "绿地", "景观"],
            "architecture": ["建筑", "风貌", "风格", "特色"],
            "historical_culture": ["历史", "文化", "遗产", "保护"],
        }

        # 遍历所有文档摘要，按关键词分类
        for doc, summary in zip(docs, summaries):
            if "error" in summary:
                continue

            # 根据章节标题和关键要点，判断属于哪些维度
            relevant_dimensions = self._classify_document_to_dimensions(
                summary,
                dimension_keywords
            )

            for dim in relevant_dimensions:
                if dim in knowledge_map:
                    knowledge_map[dim].append({
                        "source": doc["source"],
                        "summary": summary
                    })

        # 记录分类结果
        for dim, items in knowledge_map.items():
            if items:
                logger.debug(f"[知识预加载] {dim}: {len(items)} 条知识")

        return knowledge_map

    def _classify_document_to_dimensions(
        self,
        summary: dict,
        dimension_keywords: Dict[str, List[str]]
    ) -> List[str]:
        """
        将文档分类到相关维度

        Args:
            summary: 文档摘要
            dimension_keywords: 维度关键词映射

        Returns:
            相关维度列表
        """
        relevant_dimensions: List[str] = []

        # 提取文本内容
        text_content = (
            summary.get("executive_summary", "") + " " +
            " ".join([ch.get("summary", "") for ch in summary.get("chapters", [])]) + " " +
            " ".join(summary.get("key_points", []))
        ).lower()

        # 检查每个维度的关键词
        for dimension, keywords in dimension_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text_content:
                    if dimension not in relevant_dimensions:
                        relevant_dimensions.append(dimension)
                    break

        return relevant_dimensions

    def get_dimension_knowledge(self, dimension: str) -> List[dict]:
        """
        获取特定维度的预加载知识

        Args:
            dimension: 维度标识

        Returns:
            该维度的知识列表
        """
        return self._knowledge_map.get(dimension, [])


# ==========================================
# 辅助函数：格式化知识上下文
# ==========================================

def format_dimension_knowledge(knowledge_list: List[dict]) -> str:
    """
    格式化维度知识为上下文字符串

    Args:
        knowledge_list: 知识列表

    Returns:
        格式化的知识上下文字符串
    """
    if not knowledge_list:
        return "暂无相关知识参考"

    formatted = []
    for i, knowledge in enumerate(knowledge_list, 1):
        source = knowledge.get("source", "未知来源")
        summary = knowledge.get("summary", {})
        executive = summary.get("executive_summary", "")

        formatted.append(f"""
【参考资料 {i}】
来源: {source}
摘要: {executive}
        """.strip())

    return "\n\n".join(formatted)


__all__ = ["KnowledgePreloader", "format_dimension_knowledge"]
