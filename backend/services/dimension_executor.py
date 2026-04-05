"""
DimensionExecutor - 维度执行服务

提供并行维度分析能力：
1. 被 API 层直接调用（/dimensions/run 端点）
2. 被 ReviewService 调用（驳回后重新生成）

Architecture:
    API Layer → DimensionExecutor → analyze_dimension_for_send
    ReviewService → DimensionExecutor → analyze_dimension_for_send
"""

import asyncio
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


class DimensionExecutor:
    """
    维度执行服务 - 简化版

    直接驱动维度分析，无需后台任务。
    """

    @staticmethod
    async def execute_dimensions(
        session_id: str,
        layer: int,
        dimension_keys: List[str],
        state: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        并行执行指定维度的分析。

        Args:
            session_id: 会话 ID
            layer: 层级（1, 2, 3）
            dimension_keys: 维度键名列表
            state: 当前状态（包含 config, reports 等）

        Returns:
            Dict[dimension_key, content] 结果映射
        """
        from src.orchestration.nodes.dimension_node import (
            analyze_dimension_for_send,
            create_dimension_state,
            DIMENSION_NAMES,
            get_layer_from_dimension,
        )
        from src.utils.sse_publisher import SSEPublisher

        async def run_one(dim_key: str) -> Tuple[str, str]:
            """执行单个维度分析"""
            dim_name = DIMENSION_NAMES.get(dim_key, dim_key)

            # 发送 dimension_start 事件
            SSEPublisher.send_dimension_start(
                session_id=session_id,
                layer=layer,
                dimension_key=dim_key,
                dimension_name=dim_name
            )

            # 使用共享函数构建维度状态
            dim_state = create_dimension_state(dim_key, state)
            dim_state["layer"] = layer

            # 执行维度分析
            result = await analyze_dimension_for_send(dim_state)

            # 提取结果
            dim_results = result.get("dimension_results", [])
            content = ""
            for dr in dim_results:
                if dr.get("dimension_key") == dim_key and dr.get("success"):
                    content = dr.get("result", "")
                    break

            # 发送 dimension_complete 事件
            SSEPublisher.send_dimension_complete(
                session_id=session_id,
                layer=layer,
                dimension_key=dim_key,
                dimension_name=dim_name,
                full_content=content
            )

            return dim_key, content

        # 并行执行所有维度
        logger.info(f"[DimensionExecutor] [{session_id}] 开始执行 {len(dimension_keys)} 个维度: {dimension_keys}")

        results = await asyncio.gather(*[run_one(dim) for dim in dimension_keys])

        result_dict = {dim: content for dim, content in results}
        logger.info(f"[DimensionExecutor] [{session_id}] 完成，成功: {len([c for c in result_dict.values() if c])} 个")

        return result_dict

    @staticmethod
    async def execute_single_dimension(
        session_id: str,
        dimension_key: str,
        state: Dict[str, Any]
    ) -> str:
        """
        执行单个维度分析（用于 revision 流程）

        Args:
            session_id: 会话 ID
            dimension_key: 维度键名
            state: 当前状态

        Returns:
            分析内容字符串
        """
        from src.orchestration.nodes.dimension_node import (
            analyze_dimension_for_send,
            create_dimension_state,
            DIMENSION_NAMES,
            get_layer_from_dimension,
        )
        from src.utils.sse_publisher import SSEPublisher

        layer = get_layer_from_dimension(dimension_key)
        dim_name = DIMENSION_NAMES.get(dimension_key, dimension_key)

        logger.info(f"[DimensionExecutor] [{session_id}] 开始执行单维度: {dim_name}")

        # 发送开始事件
        SSEPublisher.send_dimension_start(
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dim_name
        )

        # 使用共享函数构建维度状态
        dim_state = create_dimension_state(dimension_key, state)
        dim_state["layer"] = layer

        # 执行分析
        result = await analyze_dimension_for_send(dim_state)

        # 提取内容
        dim_results = result.get("dimension_results", [])
        content = ""
        for dr in dim_results:
            if dr.get("dimension_key") == dimension_key and dr.get("success"):
                content = dr.get("result", "")
                break

        # 发送完成事件
        SSEPublisher.send_dimension_complete(
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dim_name,
            full_content=content
        )

        logger.info(f"[DimensionExecutor] [{session_id}] 单维度完成: {dim_name}, 长度: {len(content)}")

        return content

    @staticmethod
    async def update_reports(
        session_id: str,
        layer: int,
        results: Dict[str, str]
    ) -> bool:
        """
        更新状态中的 reports

        Args:
            session_id: 会话 ID
            layer: 层级
            results: 维度结果映射

        Returns:
            是否成功
        """
        from backend.services.planning_runtime_service import PlanningRuntimeService

        layer_key = f"layer{layer}"

        # 获取当前状态
        current_state = await PlanningRuntimeService.aget_state_values(session_id)
        if not current_state:
            logger.error(f"[DimensionExecutor] [{session_id}] 无法获取状态")
            return False

        # 合并到 reports
        reports = dict(current_state.get("reports", {}))
        if layer_key not in reports:
            reports[layer_key] = {}

        for dim_key, content in results.items():
            if content:
                reports[layer_key][dim_key] = content

        # 更新状态
        await PlanningRuntimeService.aupdate_state(session_id, {
            "reports": reports
        })

        logger.info(f"[DimensionExecutor] [{session_id}] 更新 reports: Layer {layer}, {len(results)} 个维度")

        return True


# Singleton instance
dimension_executor = DimensionExecutor()


__all__ = ["DimensionExecutor", "dimension_executor"]