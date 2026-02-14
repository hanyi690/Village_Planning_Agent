"""
异步存储管道 (Async Storage Pipeline)

功能：
- 维度完成时立即写入Redis（流式缓存）
- 整个层级完成后批量写入SQLite
- 文件输出使用后台任务

设计目标：
- 非阻塞存储，不影响流式传输性能
- 数据最终一致性
- Redis作为热缓存，SQLite作为持久化存储

Example:
    pipeline = AsyncStoragePipeline(
        session_id="20240101_120000",
        project_name="示例村庄"
    )
    await pipeline.init_redis()

    # 存储单个维度（立即写入Redis）
    await pipeline.store_dimension(
        layer=1,
        dimension_key="economic",
        dimension_name="经济发展",
        content="..."
    )

    # 提交整个层级（批量写入SQLite和文件）
    await pipeline.commit_layer(
        layer=1,
        combined_report="完整报告",
        dimension_reports={"economic": "...", "social": "..."}
    )
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AsyncStoragePipeline:
    """异步存储管道

    管理规划内容的异步存储，支持Redis缓存、SQLite持久化和文件输出。

    流程：
    1. store_dimension() - 维度完成时立即写入Redis（非阻塞）
    2. commit_layer() - 层级完成时批量写入SQLite（非阻塞）
    3. _write_layer_file() - 后台任务写入文件（完全异步）

    Attributes:
        session_id: 会话ID
        project_name: 项目名称
        pending_writes: 待写入的内容字典
        _redis_client: Redis客户端（延迟初始化）
        _lock: 异步锁，保护pending_writes
    """

    def __init__(self, session_id: str, project_name: str):
        """初始化存储管道

        Args:
            session_id: 会话ID
            project_name: 项目名称
        """
        self.session_id = session_id
        self.project_name = project_name
        self.pending_writes: Dict[str, str] = {}
        self._redis_client = None
        self._lock = asyncio.Lock()
        self._enabled = True

    async def init_redis(self) -> bool:
        """延迟初始化Redis客户端

        Returns:
            bool: 初始化是否成功
        """
        try:
            from backend.services.redis_client import get_redis_client
            self._redis_client = get_redis_client()

            # 检查Redis是否可用
            if self._redis_client and hasattr(self._redis_client, 'enabled'):
                if not self._redis_client.enabled:
                    logger.warning(f"[StoragePipeline] Redis is disabled, using memory only")
                    self._redis_client = None
                    return False

            logger.info(f"[StoragePipeline] Redis initialized for session {self.session_id}")
            return True

        except Exception as e:
            logger.warning(f"[StoragePipeline] Redis初始化失败: {e}")
            self._redis_client = None
            return False

    async def store_dimension(
        self,
        layer: int,
        dimension_key: str,
        dimension_name: str,
        content: str
    ) -> bool:
        """存储单个维度报告（异步，非阻塞）

        1. 立即写入Redis（如果可用）
        2. 记录到pending_writes等待批量写入

        Args:
            layer: 层级号（1=分析, 2=概念, 3=详细）
            dimension_key: 维度键（如 "economic", "social"）
            dimension_name: 维度显示名称（如 "经济发展"）
            content: 维度完整内容

        Returns:
            bool: 存储是否成功
        """
        if not self._enabled:
            return False

        try:
            # 1. 立即写入Redis（非阻塞）
            if self._redis_client:
                try:
                    # 假设Redis客户端有save_dimension_report方法
                    if hasattr(self._redis_client, 'save_dimension_report'):
                        await self._redis_client.save_dimension_report(
                            session_id=self.session_id,
                            layer=layer,
                            dimension_key=dimension_key,
                            dimension_name=dimension_name,
                            content=content
                        )
                        logger.debug(
                            f"[StoragePipeline] Redis写入成功: L{layer}/{dimension_key} "
                            f"({len(content)} chars)"
                        )
                    else:
                        # 备用方案：使用通用set方法
                        key = f"dimension:{self.session_id}:l{layer}:{dimension_key}"
                        if asyncio.iscoroutinefunction(self._redis_client.set):
                            await self._redis_client.set(key, content, ex=3600)
                        else:
                            self._redis_client.set(key, content, ex=3600)
                        logger.debug(f"[StoragePipeline] Redis set成功: {key}")

                except Exception as e:
                    logger.warning(f"[StoragePipeline] Redis写入失败: {e}")

            # 2. 记录待写入列表
            async with self._lock:
                key = f"l{layer}_{dimension_key}"
                self.pending_writes[key] = content

            return True

        except Exception as e:
            logger.error(f"[StoragePipeline] store_dimension error: {e}", exc_info=True)
            return False

    async def commit_layer(
        self,
        layer: int,
        combined_report: str,
        dimension_reports: Dict[str, str]
    ) -> None:
        """提交整个层级（批量写入SQLite和文件）

        1. 写入SQLite（批量）
        2. 写入文件（后台任务）
        3. 清空pending

        Args:
            layer: 层级号
            combined_report: 完整层级报告
            dimension_reports: 各维度报告字典 {dimension_key: content}
        """
        if not self._enabled:
            return

        try:
            # 1. 写入SQLite（批量）
            await self._write_to_sqlite(layer, dimension_reports)

            # 2. 写入文件（后台任务，不等待）
            asyncio.create_task(self._write_layer_file(layer, combined_report))

            # 3. 更新Redis中的完整报告
            if self._redis_client:
                try:
                    key = f"layer:{self.session_id}:l{layer}"
                    if asyncio.iscoroutinefunction(self._redis_client.set):
                        await self._redis_client.set(key, combined_report, ex=86400)
                    else:
                        self._redis_client.set(key, combined_report, ex=86400)
                except Exception as e:
                    logger.warning(f"[StoragePipeline] Redis写入完整报告失败: {e}")

            # 4. 清空pending
            async with self._lock:
                # 只清空当前层级的pending
                layer_prefix = f"l{layer}_"
                keys_to_remove = [
                    k for k in self.pending_writes.keys()
                    if k.startswith(layer_prefix)
                ]
                for key in keys_to_remove:
                    del self.pending_writes[key]

            logger.info(
                f"[StoragePipeline] Layer {layer} committed: "
                f"{len(dimension_reports)} dimensions, "
                f"{len(combined_report)} chars total"
            )

        except Exception as e:
            logger.error(f"[StoragePipeline] commit_layer error: {e}", exc_info=True)

    async def _write_to_sqlite(
        self,
        layer: int,
        dimension_reports: Dict[str, str]
    ) -> None:
        """写入SQLite（批量）"""
        try:
            from backend.database import update_session_state_async

            # 确定state_key
            state_key = {
                1: "analysis_dimension_reports",
                2: "concept_dimension_reports",
                3: "detailed_dimension_reports"
            }.get(layer)

            if not state_key:
                logger.warning(f"[StoragePipeline] Unknown layer: {layer}")
                return

            # 更新数据库（异步）
            update_data = {
                state_key: dimension_reports,
                f"layer_{layer}_completed": True,
                "updated_at": datetime.now().isoformat()
            }

            await update_session_state_async(self.session_id, update_data)

            logger.info(
                f"[StoragePipeline] SQLite批量写入成功: Layer {layer}, "
                f"{len(dimension_reports)} dimensions"
            )

        except Exception as e:
            logger.error(f"[StoragePipeline] SQLite写入失败: {e}", exc_info=True)

    async def _write_layer_file(self, layer: int, content: str) -> None:
        """后台任务：写入文件

        Args:
            layer: 层级号
            content: 要写入的内容
        """
        try:
            from src.utils.output_manager import get_output_manager_registry

            registry = get_output_manager_registry()
            output_manager = registry.get(self.session_id)

            if output_manager:
                layer_names = {
                    1: "layer_1_analysis",
                    2: "layer_2_concept",
                    3: "layer_3_detailed"
                }

                output_manager.write_layer_content(
                    layer=layer,
                    layer_name=layer_names.get(layer, f"layer_{layer}"),
                    content=content
                )

                logger.info(
                    f"[StoragePipeline] 文件写入成功: Layer {layer}, "
                    f"{len(content)} chars"
                )
            else:
                logger.warning(
                    f"[StoragePipeline] No output_manager found for {self.session_id}"
                )

        except Exception as e:
            logger.error(f"[StoragePipeline] 文件写入失败: {e}", exc_info=True)

    async def get_pending_content(self, layer: int, dimension_key: str) -> Optional[str]:
        """获取待写入的内容

        Args:
            layer: 层级号
            dimension_key: 维度键

        Returns:
            Optional[str]: 待写入的内容，如果不存在则返回None
        """
        async with self._lock:
            key = f"l{layer}_{dimension_key}"
            return self.pending_writes.get(key)

    async def clear_pending(self) -> None:
        """清空所有待写入内容"""
        async with self._lock:
            self.pending_writes.clear()
        logger.debug(f"[StoragePipeline] Cleared pending writes for {self.session_id}")

    def get_stats(self) -> Dict:
        """获取统计信息

        Returns:
            Dict: 包含 pending_count, redis_enabled 的统计
        """
        return {
            "session_id": self.session_id,
            "project_name": self.project_name,
            "pending_count": len(self.pending_writes),
            "redis_enabled": self._redis_client is not None,
            "enabled": self._enabled
        }


# ============================================
# Factory Function
# ============================================

async def create_storage_pipeline(
    session_id: str,
    project_name: str,
    enable_redis: bool = True
) -> AsyncStoragePipeline:
    """创建并初始化存储管道

    Args:
        session_id: 会话ID
        project_name: 项目名称
        enable_redis: 是否启用Redis

    Returns:
        AsyncStoragePipeline: 已初始化的存储管道
    """
    pipeline = AsyncStoragePipeline(session_id, project_name)

    if enable_redis:
        await pipeline.init_redis()

    return pipeline
