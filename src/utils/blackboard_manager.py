"""
黑板管理器

实现黑板模式，支持跨层级数据共享。
Layer 3 Agent 可以主动查阅原始档案和工具结果。
"""

from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from collections import OrderedDict
import hashlib
import json

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class RawDataReference:
    """原始档案引用"""
    source: str                           # 数据来源（如"village_data", "gis_data"等）
    file_path: Optional[str] = None       # 文件路径（如果有）
    data_hash: Optional[str] = None       # 数据哈希值（用于检测变化）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "source": self.source,
            "file_path": self.file_path,
            "data_hash": self.data_hash,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


@dataclass
class ToolResult:
    """工具执行结果"""
    tool_id: str                          # 工具ID
    tool_name: str                        # 工具名称
    result: Dict[str, Any]                # 结果数据
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    success: bool = True                  # 执行是否成功
    error: Optional[str] = None           # 错误信息

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "result": self.result,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "success": self.success,
            "error": self.error
        }


@dataclass
class Insight:
    """共享洞察"""
    insight: str                          # 洞察内容
    author: str                           # 作者（哪个Agent/Tool）
    dimension: Optional[str] = None       # 相关维度
    confidence: Optional[float] = None    # 置信度（0-1）
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "insight": self.insight,
            "author": self.author,
            "dimension": self.dimension,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


class BlackboardManager:
    """
    黑板管理器

    实现黑板模式，支持：
    1. 原始档案引用的注册和查询
    2. 工具结果的发布和订阅
    3. 跨Agent的洞察共享
    4. Planner层主动查询
    """

    def __init__(self, max_insights: int = 1000):
        """
        初始化黑板管理器

        Args:
            max_insights: 最大保存的洞察数量
        """
        self._raw_data_references: Dict[str, RawDataReference] = {}
        self._tool_results: OrderedDict[str, ToolResult] = OrderedDict()
        self._insights: List[Insight] = []
        self._max_insights = max_insights
        self._blackboard_enabled = True

        logger.info("[Blackboard] 黑板管理器已初始化")

    @property
    def is_enabled(self) -> bool:
        """检查黑板是否启用"""
        return self._blackboard_enabled

    def enable(self):
        """启用黑板"""
        self._blackboard_enabled = True
        logger.info("[Blackboard] 黑板已启用")

    def disable(self):
        """禁用黑板"""
        self._blackboard_enabled = False
        logger.info("[Blackboard] 黑板已禁用")

    # ==========================================
    # 原始档案引用管理
    # ==========================================

    def register_raw_data(
        self,
        source: str,
        file_path: Optional[str] = None,
        data: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        注册原始档案引用

        Args:
            source: 数据来源
            file_path: 文件路径（可选）
            data: 原始数据（可选，用于生成哈希）
            metadata: 元数据（可选）

        Returns:
            True if registration successful
        """
        if not self._blackboard_enabled:
            logger.warning("[Blackboard] 黑板已禁用，跳过注册")
            return False

        try:
            # 计算数据哈希
            data_hash = None
            if data is not None:
                data_str = json.dumps(data, ensure_ascii=False, default=str)
                data_hash = hashlib.md5(data_str.encode()).hexdigest()

            ref = RawDataReference(
                source=source,
                file_path=file_path,
                data_hash=data_hash,
                metadata=metadata or {}
            )

            self._raw_data_references[source] = ref
            logger.info(f"[Blackboard] 已注册原始档案引用: {source}")
            return True

        except Exception as e:
            logger.error(f"[Blackboard] 注册原始档案引用失败: {str(e)}")
            return False

    def get_raw_data_reference(self, source: str) -> Optional[RawDataReference]:
        """
        获取原始档案引用

        Args:
            source: 数据来源

        Returns:
            RawDataReference对象，如果不存在则返回None
        """
        return self._raw_data_references.get(source)

    def list_raw_data_references(self) -> Dict[str, RawDataReference]:
        """
        列出所有原始档案引用

        Returns:
            原始档案引用字典
        """
        return self._raw_data_references.copy()

    # ==========================================
    # 工具结果管理
    # ==========================================

    def publish_tool_result(
        self,
        tool_id: str,
        tool_name: str,
        result: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error: Optional[str] = None
    ) -> bool:
        """
        发布工具结果

        Args:
            tool_id: 工具ID
            tool_name: 工具名称
            result: 结果数据
            metadata: 元数据（可选）
            success: 执行是否成功
            error: 错误信息（可选）

        Returns:
            True if publication successful
        """
        if not self._blackboard_enabled:
            logger.warning("[Blackboard] 黑板已禁用，跳过发布")
            return False

        try:
            tool_result = ToolResult(
                tool_id=tool_id,
                tool_name=tool_name,
                result=result,
                metadata=metadata or {},
                success=success,
                error=error
            )

            self._tool_results[tool_id] = tool_result
            logger.info(f"[Blackboard] 已发布工具结果: {tool_name} ({tool_id})")
            return True

        except Exception as e:
            logger.error(f"[Blackboard] 发布工具结果失败: {str(e)}")
            return False

    def get_tool_result(self, tool_id: str) -> Optional[ToolResult]:
        """
        获取工具结果

        Args:
            tool_id: 工具ID

        Returns:
            ToolResult对象，如果不存在则返回None
        """
        return self._tool_results.get(tool_id)

    def get_tool_results_by_prefix(self, prefix: str) -> List[ToolResult]:
        """
        根据前缀获取工具结果

        Args:
            prefix: 工具ID前缀

        Returns:
            匹配的ToolResult列表
        """
        results = []
        for tool_id, tool_result in self._tool_results.items():
            if tool_id.startswith(prefix):
                results.append(tool_result)
        return results

    def list_tool_results(self) -> Dict[str, ToolResult]:
        """
        列出所有工具结果

        Returns:
            工具结果字典
        """
        return self._tool_results.copy()

    # ==========================================
    # 洞察管理
    # ==========================================

    def add_insight(
        self,
        insight: str,
        author: str,
        dimension: Optional[str] = None,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        添加共享洞察

        Args:
            insight: 洞察内容
            author: 作者
            dimension: 相关维度（可选）
            confidence: 置信度（可选）
            metadata: 元数据（可选）

        Returns:
            True if addition successful
        """
        if not self._blackboard_enabled:
            logger.warning("[Blackboard] 黑板已禁用，跳过添加")
            return False

        try:
            insight_obj = Insight(
                insight=insight,
                author=author,
                dimension=dimension,
                confidence=confidence,
                metadata=metadata or {}
            )

            self._insights.append(insight_obj)

            # 限制洞察数量
            if len(self._insights) > self._max_insights:
                self._insights = self._insights[-self._max_insights:]

            logger.debug(f"[Blackboard] 已添加洞察: {author} - {insight[:50]}...")
            return True

        except Exception as e:
            logger.error(f"[Blackboard] 添加洞察失败: {str(e)}")
            return False

    def get_insights(
        self,
        filter_author: Optional[str] = None,
        filter_dimension: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Insight]:
        """
        获取洞察列表

        Args:
            filter_author: 按作者过滤（可选）
            filter_dimension: 按维度过滤（可选）
            limit: 最大返回数量（可选）

        Returns:
            Insight列表
        """
        insights = self._insights

        # 应用过滤器
        if filter_author:
            insights = [i for i in insights if i.author == filter_author]

        if filter_dimension:
            insights = [i for i in insights if i.dimension == filter_dimension]

        # 限制数量
        if limit:
            insights = insights[-limit:]

        return insights

    def get_insights_by_author(self, author: str, limit: Optional[int] = None) -> List[Insight]:
        """
        按作者获取洞察

        Args:
            author: 作者名称
            limit: 最大返回数量（可选）

        Returns:
            Insight列表
        """
        return self.get_insights(filter_author=author, limit=limit)

    def get_insights_by_dimension(self, dimension: str, limit: Optional[int] = None) -> List[Insight]:
        """
        按维度获取洞察

        Args:
            dimension: 维度名称
            limit: 最大返回数量（可选）

        Returns:
            Insight列表
        """
        return self.get_insights(filter_dimension=dimension, limit=limit)

    def list_insights(self, limit: Optional[int] = None) -> List[Insight]:
        """
        列出所有洞察

        Args:
            limit: 最大返回数量（可选）

        Returns:
            Insight列表
        """
        if limit:
            return self._insights[-limit:]
        return self._insights.copy()

    # ==========================================
    # Planner层查询接口
    # ==========================================

    def query_for_planner(
        self,
        dimension: str,
        query_type: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Planner层主动查询接口

        Args:
            dimension: 维度名称
            query_type: 查询类型
                - "raw_data": 查询原始档案
                - "tool_result": 查询工具结果
                - "insights": 查询共享洞察
                - "all": 查询所有相关数据
            **kwargs: 额外查询参数

        Returns:
            查询结果字典
        """
        if not self._blackboard_enabled:
            return {
                "success": False,
                "error": "黑板已禁用",
                "data": {}
            }

        result = {
            "success": True,
            "dimension": dimension,
            "query_type": query_type,
            "data": {}
        }

        try:
            if query_type == "raw_data" or query_type == "all":
                # 查询原始档案引用
                raw_data = {}
                for source, ref in self._raw_data_references.items():
                    raw_data[source] = ref.to_dict()
                result["data"]["raw_data_references"] = raw_data

            if query_type == "tool_result" or query_type == "all":
                # 查询工具结果
                tool_results = {}
                for tool_id, tool_result in self._tool_results.items():
                    tool_results[tool_id] = tool_result.to_dict()
                result["data"]["tool_results"] = tool_results

            if query_type == "insights" or query_type == "all":
                # 查询共享洞察
                if "limit" in kwargs:
                    insights = self.get_insights(limit=kwargs["limit"])
                else:
                    insights = self.get_insights()
                result["data"]["insights"] = [i.to_dict() for i in insights]

            # 特定维度的工具结果
            if "tool_prefix" in kwargs:
                tool_prefix = kwargs["tool_prefix"]
                specific_results = self.get_tool_results_by_prefix(tool_prefix)
                result["data"]["specific_tool_results"] = {
                    r.tool_id: r.to_dict() for r in specific_results
                }

            logger.debug(f"[Blackboard] Planner查询: {dimension} - {query_type}")
            return result

        except Exception as e:
            logger.error(f"[Blackboard] Planner查询失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "dimension": dimension,
                "query_type": query_type,
                "data": {}
            }

    # ==========================================
    # 黑板状态管理
    # ==========================================

    def clear(self):
        """清空黑板数据"""
        self._raw_data_references.clear()
        self._tool_results.clear()
        self._insights.clear()
        logger.info("[Blackboard] 黑板数据已清空")

    def get_status(self) -> Dict[str, Any]:
        """
        获取黑板状态

        Returns:
            状态字典
        """
        return {
            "enabled": self._blackboard_enabled,
            "raw_data_count": len(self._raw_data_references),
            "tool_results_count": len(self._tool_results),
            "insights_count": len(self._insights),
            "max_insights": self._max_insights
        }

    def export_state(self) -> Dict[str, Any]:
        """
        导出黑板状态

        Returns:
            包含所有黑板数据的字典
        """
        return {
            "raw_data_references": {
                k: v.to_dict() for k, v in self._raw_data_references.items()
            },
            "tool_results": {
                k: v.to_dict() for k, v in self._tool_results.items()
            },
            "insights": [i.to_dict() for i in self._insights],
            "status": self.get_status()
        }

    def import_state(self, state: Dict[str, Any]) -> bool:
        """
        导入黑板状态

        Args:
            state: 导入的状态字典

        Returns:
            True if import successful
        """
        try:
            # 导入原始档案引用
            for source, ref_dict in state.get("raw_data_references", {}).items():
                self._raw_data_references[source] = RawDataReference(**ref_dict)

            # 导入工具结果
            for tool_id, result_dict in state.get("tool_results", {}).items():
                self._tool_results[tool_id] = ToolResult(**result_dict)

            # 导入洞察
            for insight_dict in state.get("insights", []):
                self._insights.append(Insight(**insight_dict))

            logger.info("[Blackboard] 黑板状态已导入")
            return True

        except Exception as e:
            logger.error(f"[Blackboard] 导入状态失败: {str(e)}")
            return False


# 全局黑板管理器实例
_global_blackboard: Optional[BlackboardManager] = None


def get_blackboard() -> BlackboardManager:
    """
    获取全局黑板管理器实例

    Returns:
        BlackboardManager实例
    """
    global _global_blackboard
    if _global_blackboard is None:
        _global_blackboard = BlackboardManager()
    return _global_blackboard
