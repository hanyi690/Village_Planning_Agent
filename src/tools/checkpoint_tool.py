"""Checkpoint persistence tool.

Provides complete lifecycle management for checkpoints:
1. Save checkpoints
2. Load checkpoints
3. List checkpoints
4. Rollback to specified checkpoint
5. File cleanup

Follows tool pattern: all methods return structured Dict results.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..utils.logger import get_logger
from ..utils.paths import get_project_root

logger = get_logger(__name__)


# ==========================================
# SQLite存储实现（新增）
# ==========================================

class _SqlCheckpointStorage:
    """
    Checkpoint的SQLite存储实现（内部类）

    提供基于数据库的checkpoint持久化功能（异步）。
    """

    def __init__(self) -> None:
        """初始化SQLite存储"""
        pass

    async def save(
        self,
        project_name: str,
        timestamp: str,
        checkpoint_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any]
    ) -> str | None:
        """保存checkpoint到SQLite数据库（异步）"""
        try:
            from backend.database import create_checkpoint_async

            success = await create_checkpoint_async(
                checkpoint_id=checkpoint_id,
                session_id=timestamp,
                layer=metadata.get("layer", 0),
                description=metadata.get("description", ""),
                state_snapshot=state,
                checkpoint_metadata=metadata
            )

            if success:
                logger.info(f"[SqlStorage] Checkpoint已保存: {checkpoint_id}")
                return checkpoint_id
            else:
                logger.error(f"[SqlStorage] 保存checkpoint失败")
                return None

        except Exception as e:
            logger.error(f"[SqlStorage] 保存checkpoint失败: {e}")
            return None

    async def load(self, checkpoint_id: str) -> dict[str, Any] | None:
        """从SQLite数据库加载checkpoint（异步）"""
        try:
            from backend.database import get_checkpoint_async

            data = await get_checkpoint_async(checkpoint_id)

            if data:
                logger.info(f"[SqlStorage] Checkpoint已加载: {checkpoint_id}")
                return {
                    "checkpoint_id": data["checkpoint_id"],
                    "timestamp": data["timestamp"],
                    "metadata": data.get("checkpoint_metadata", {}),
                    "state": data["state_snapshot"]
                }
            else:
                logger.error(f"[SqlStorage] Checkpoint不存在: {checkpoint_id}")
                return None

        except Exception as e:
            logger.error(f"[SqlStorage] 加载checkpoint失败: {e}")
            return None

    async def list_checkpoints(self, project_name: str, timestamp: str | None = None) -> list[dict[str, Any]]:
        """列出项目的所有checkpoint（异步）"""
        try:
            from backend.database import list_checkpoints_async

            if timestamp:
                checkpoints = await list_checkpoints_async(session_id=timestamp)
            else:
                # List all checkpoints (will need to filter by project name later)
                checkpoints = await list_checkpoints_async()

            return checkpoints

        except Exception as e:
            logger.error(f"[SqlStorage] 列出checkpoint失败: {e}")
            return []

    async def delete(self, checkpoint_id: str) -> bool:
        """删除checkpoint（异步）"""
        try:
            from backend.database import delete_checkpoint_async

            success = await delete_checkpoint_async(checkpoint_id)

            if success:
                logger.info(f"[SqlStorage] Checkpoint已删除: {checkpoint_id}")
                return True
            else:
                logger.warning(f"[SqlStorage] Checkpoint不存在: {checkpoint_id}")
                return False

        except Exception as e:
            logger.error(f"[SqlStorage] 删除checkpoint失败: {e}")
            return False


# ==========================================
# JSON存储实现（内部实现）
# ==========================================

class _JsonCheckpointStorage:
    """
    Checkpoint的JSON存储实现（内部类）

    提供基于文件系统的checkpoint持久化功能。
    """

    def __init__(self, base_path: Path | None = None) -> None:
        if base_path is None:
            # 使用统一路径管理获取results目录的绝对路径
            self.base_path = get_project_root() / "results"
        else:
            self.base_path = base_path

    def _get_checkpoint_dir(self, project_name: str, timestamp: str) -> Path:
        """获取checkpoint存储目录"""
        safe_name = self._sanitize_name(project_name)
        checkpoint_dir = self.base_path / safe_name / timestamp / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return checkpoint_dir

    def _sanitize_name(self, name: str) -> str:
        """清理文件名（移除不安全字符）"""
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    def save(
        self,
        project_name: str,
        timestamp: str,
        checkpoint_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any]
    ) -> str | None:
        """保存checkpoint到JSON文件"""
        try:
            checkpoint_dir = self._get_checkpoint_dir(project_name, timestamp)
            file_path = checkpoint_dir / f"{checkpoint_id}.json"

            # 序列化状态
            serializable_data = self._prepare_for_serialization({
                "checkpoint_id": checkpoint_id,
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata,
                "state": state
            })

            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=2)

            logger.info(f"[JsonStorage] Checkpoint已保存: {file_path}")
            return str(file_path)

        except Exception as e:
            logger.error(f"[JsonStorage] 保存checkpoint失败: {e}")
            return None

    def load(self, file_path: str) -> dict[str, Any] | None:
        """从JSON文件加载checkpoint"""
        try:
            path = Path(file_path)
            if not path.exists():
                logger.error(f"[JsonStorage] Checkpoint文件不存在: {file_path}")
                return None

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            logger.info(f"[JsonStorage] Checkpoint已加载: {file_path}")
            return data

        except Exception as e:
            logger.error(f"[JsonStorage] 加载checkpoint失败: {e}")
            return None

    def list_checkpoints(self, project_name: str, timestamp: str | None = None) -> list[dict[str, Any]]:
        """列出项目的所有checkpoint"""
        try:
            safe_name = self._sanitize_name(project_name)

            if timestamp:
                checkpoint_dir = self.base_path / safe_name / timestamp / "checkpoints"
                if not checkpoint_dir.exists():
                    return []

                checkpoints = []
                for checkpoint_file in sorted(checkpoint_dir.glob("*.json")):
                    info = self._get_checkpoint_info(checkpoint_file)
                    if info:
                        checkpoints.append(info)

                return checkpoints
            else:
                project_dir = self.base_path / safe_name
                if not project_dir.exists():
                    return []

                all_checkpoints = []
                for ts_dir in sorted(project_dir.iterdir()):
                    if ts_dir.is_dir():
                        checkpoint_dir = ts_dir / "checkpoints"
                        if checkpoint_dir.exists():
                            for checkpoint_file in sorted(checkpoint_dir.glob("*.json")):
                                info = self._get_checkpoint_info(checkpoint_file)
                                if info:
                                    all_checkpoints.append(info)

                return all_checkpoints

        except Exception as e:
            logger.error(f"[JsonStorage] 列出checkpoint失败: {e}")
            return []

    def delete(self, file_path: str) -> bool:
        """删除checkpoint文件"""
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                logger.info(f"[JsonStorage] Checkpoint已删除: {file_path}")
                return True
            else:
                logger.warning(f"[JsonStorage] Checkpoint文件不存在: {file_path}")
                return False

        except Exception as e:
            logger.error(f"[JsonStorage] 删除checkpoint失败: {e}")
            return False

    def _get_checkpoint_info(self, file_path: Path) -> dict[str, Any] | None:
        """从checkpoint文件中提取元数据信息"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return {
                "checkpoint_id": data.get("checkpoint_id"),
                "file_path": str(file_path),
                "timestamp": data.get("timestamp"),
                "layer": data.get("metadata", {}).get("layer"),
                "description": data.get("metadata", {}).get("description", "")
            }

        except Exception as e:
            logger.warning(f"[JsonStorage] 获取checkpoint信息失败 {file_path}: {e}")
            return None

    def _prepare_for_serialization(self, data: Any) -> Any:
        """准备数据用于序列化（处理不可序列化的对象）"""
        if isinstance(data, dict):
            return {
                k: self._prepare_for_serialization(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [
                self._prepare_for_serialization(item)
                for item in data
            ]
        elif hasattr(data, '__dict__'):
            return {
                k: self._prepare_for_serialization(v)
                for k, v in data.__dict__.items()
                if not k.startswith('_') and not callable(v)
            }
        elif isinstance(data, (str, int, float, bool, type(None))):
            return data
        else:
            return str(data)


# ==========================================
# Checkpoint工具类
# ==========================================

class CheckpointTool:
    """
    Checkpoint工具

    提供checkpoint的完整生命周期管理，遵循tool pattern。
    """

    CHECKPOINT_ID_FORMAT = "checkpoint_{layer:03d}_layer{layer}_completed"

    def __init__(
        self,
        project_name: str,
        timestamp: str | None = None,
        storage: _JsonCheckpointStorage | _SqlCheckpointStorage | None = None,
        use_sqlite: bool = False
    ) -> None:
        """
        初始化CheckpointTool

        Args:
            project_name: 项目名称
            timestamp: 时间戳（可选）
            storage: 存储后端（可选）
            use_sqlite: 是否使用SQLite存储（默认False，使用JSON）
        """
        self.project_name = self._sanitize_name(project_name)
        self.timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")

        # Select storage backend
        if use_sqlite:
            self.storage = storage or _SqlCheckpointStorage()
        else:
            self.storage = storage or _JsonCheckpointStorage()

        self.checkpoint_index: Dict[str, Dict[str, Any]] = {}
        self._load_index()

    def _sanitize_name(self, name: str) -> str:
        """清理项目名称"""
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    def _load_index(self):
        """加载checkpoint索引"""
        try:
            checkpoints = self.storage.list_checkpoints(self.project_name, self.timestamp)
            self.checkpoint_index = {
                cp["checkpoint_id"]: cp
                for cp in checkpoints
            }
            logger.info(f"[CheckpointTool] 加载了 {len(self.checkpoint_index)} 个checkpoint索引")
        except Exception as e:
            logger.warning(f"[CheckpointTool] 加载索引失败: {e}")
            self.checkpoint_index = {}

    def save(
        self,
        state: dict[str, Any],
        layer: int,
        description: str = ""
    ) -> dict[str, Any]:
        """
        保存checkpoint

        Args:
            state: 当前状态字典
            layer: 当前层级 (1/2/3)
            description: 描述信息

        Returns:
            结构化结果字典 {
                "success": bool,
                "checkpoint_id": str,
                "metadata": dict,
                "error": str
            }
        """
        try:
            # 生成checkpoint ID
            checkpoint_id = self.CHECKPOINT_ID_FORMAT.format(layer=layer)
            if not description:
                description = f"Layer {layer} completed"

            # 准备元数据
            metadata = {
                "layer": layer,
                "description": description,
                "project_name": self.project_name,
                "timestamp": self.timestamp
            }

            # 序列化状态
            serializable_state = self._serialize_state(state)

            # 保存到存储
            file_path = self.storage.save(
                project_name=self.project_name,
                timestamp=self.timestamp,
                checkpoint_id=checkpoint_id,
                state=serializable_state,
                metadata=metadata
            )

            if file_path:
                # 更新索引
                self.checkpoint_index[checkpoint_id] = {
                    "checkpoint_id": checkpoint_id,
                    "file_path": file_path,
                    "timestamp": datetime.now().isoformat(),
                    "layer": layer,
                    "description": description
                }

                logger.info(f"[CheckpointTool] Checkpoint已保存: {checkpoint_id}")
                return {
                    "success": True,
                    "checkpoint_id": checkpoint_id,
                    "metadata": {
                        "layer": layer,
                        "description": description,
                        "file_path": file_path
                    },
                    "error": ""
                }
            else:
                logger.error(f"[CheckpointTool] Checkpoint保存失败")
                return {
                    "success": False,
                    "checkpoint_id": "",
                    "metadata": {},
                    "error": "保存失败"
                }

        except Exception as e:
            logger.error(f"[CheckpointTool] 保存checkpoint时出错: {e}")
            return {
                "success": False,
                "checkpoint_id": "",
                "metadata": {},
                "error": str(e)
            }

    def load(self, checkpoint_id: str) -> dict[str, Any]:
        """
        加载checkpoint

        Args:
            checkpoint_id: checkpoint ID

        Returns:
            结构化结果字典 {
                "success": bool,
                "state": dict,
                "metadata": dict,
                "error": str
            }
        """
        try:
            # 从索引中查找
            if checkpoint_id not in self.checkpoint_index:
                logger.error(f"[CheckpointTool] Checkpoint不存在: {checkpoint_id}")
                return {
                    "success": False,
                    "state": None,
                    "metadata": {},
                    "error": f"Checkpoint不存在: {checkpoint_id}"
                }

            file_path = self.checkpoint_index[checkpoint_id]["file_path"]

            # 从存储加载
            data = self.storage.load(file_path)
            if not data:
                return {
                    "success": False,
                    "state": None,
                    "metadata": {},
                    "error": "加载失败"
                }

            # 反序列化状态
            state = self._deserialize_state(data["state"])

            # 移除 checkpoint_manager 字段（如果存在），避免序列化错误
            if "checkpoint_manager" in state:
                del state["checkpoint_manager"]
                logger.info(f"[CheckpointTool] 已从加载的状态中移除 checkpoint_manager")

            logger.info(f"[CheckpointTool] Checkpoint已加载: {checkpoint_id}")
            return {
                "success": True,
                "state": state,
                "metadata": data.get("metadata", {}),
                "error": ""
            }

        except Exception as e:
            logger.error(f"[CheckpointTool] 加载checkpoint时出错: {e}")
            return {
                "success": False,
                "state": None,
                "metadata": {},
                "error": str(e)
            }

    def list(self, include_all: bool = False) -> dict[str, Any]:
        """
        列出checkpoint

        Args:
            include_all: 是否包含所有项目（False则仅当前项目）

        Returns:
            结构化结果字典 {
                "success": bool,
                "checkpoints": list,
                "count": int,
                "error": str
            }
        """
        try:
            if include_all:
                checkpoints = self.storage.list_checkpoints(self.project_name, None)
            else:
                checkpoints = [
                    cp for cp in self.checkpoint_index.values()
                ]

            # 按层级排序
            checkpoints = sorted(checkpoints, key=lambda x: x.get("layer", 0))

            logger.info(f"[CheckpointTool] 列出 {len(checkpoints)} 个checkpoint")
            return {
                "success": True,
                "checkpoints": checkpoints,
                "count": len(checkpoints),
                "error": ""
            }

        except Exception as e:
            logger.error(f"[CheckpointTool] 列出checkpoint时出错: {e}")
            return {
                "success": False,
                "checkpoints": [],
                "count": 0,
                "error": str(e)
            }

    def get_latest(self) -> dict[str, Any]:
        """
        获取最新的checkpoint

        Returns:
            结构化结果字典 {
                "success": bool,
                "checkpoint": dict,
                "error": str
            }
        """
        try:
            if not self.checkpoint_index:
                return {
                    "success": False,
                    "checkpoint": None,
                    "error": "没有可用的checkpoint"
                }

            # 返回层级最大的checkpoint
            latest = max(
                self.checkpoint_index.values(),
                key=lambda x: x.get("layer", 0)
            )

            return {
                "success": True,
                "checkpoint": latest,
                "error": ""
            }

        except Exception as e:
            logger.error(f"[CheckpointTool] 获取最新checkpoint时出错: {e}")
            return {
                "success": False,
                "checkpoint": None,
                "error": str(e)
            }

    def resume_from_checkpoint(
        self,
        checkpoint_id: str,
        updates: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        从checkpoint恢复执行（准备状态用于继续）

        Args:
            checkpoint_id: checkpoint ID
            updates: 可选的状态更新（例如重置pause_after_step）

        Returns:
            结构化结果字典 {
                "success": bool,
                "state": dict,
                "metadata": dict,
                "error": str
            }
        """
        try:
            # 加载checkpoint
            load_result = self.load(checkpoint_id)
            if not load_result["success"]:
                logger.error(f"[CheckpointTool] 无法加载checkpoint: {checkpoint_id}")
                return {
                    "success": False,
                    "state": None,
                    "metadata": {},
                    "error": load_result["error"]
                }

            state = load_result["state"]
            metadata = load_result["metadata"]

            # 应用状态更新
            if updates:
                state.update(updates)

            logger.info(f"[CheckpointTool] 已从checkpoint恢复: {checkpoint_id}")
            return {
                "success": True,
                "state": state,
                "metadata": metadata,
                "error": ""
            }

        except Exception as e:
            logger.error(f"[CheckpointTool] 恢复checkpoint时出错: {e}")
            return {
                "success": False,
                "state": None,
                "metadata": {},
                "error": str(e)
            }

    def get_checkpoint_state(
        self,
        checkpoint_id: str
    ) -> dict[str, Any]:
        """
        获取checkpoint的完整状态（便捷方法）

        Args:
            checkpoint_id: checkpoint ID

        Returns:
            结构化结果字典 {
                "success": bool,
                "state": dict,
                "metadata": dict,
                "error": str
            }
        """
        return self.resume_from_checkpoint(checkpoint_id)

    def rollback(
        self,
        checkpoint_id: str,
        current_output_dir: Path | None = None,
        dry_run: bool = False
    ) -> dict[str, Any]:
        """
        回退到指定checkpoint

        Args:
            checkpoint_id: 目标checkpoint ID
            current_output_dir: 当前输出目录（用于文件清理）
            dry_run: 是否仅预览（不实际删除文件）

        Returns:
            结构化结果字典 {
                "success": bool,
                "state": dict,
                "files_deleted": int,
                "error": str
            }
        """
        try:
            # 加载checkpoint
            load_result = self.load(checkpoint_id)
            if not load_result["success"]:
                logger.error(f"[CheckpointTool] 无法加载checkpoint: {checkpoint_id}")
                return {
                    "success": False,
                    "state": None,
                    "files_deleted": 0,
                    "error": load_result["error"]
                }

            state = load_result["state"]

            # 获取目标checkpoint的层级
            target_layer = self.checkpoint_index[checkpoint_id].get("layer", 0)

            # 清理回退点之后的文件
            files_deleted = 0
            if current_output_dir:
                files_to_delete = self._identify_files_to_clean(
                    current_output_dir,
                    target_layer
                )

                if dry_run:
                    logger.info(f"[CheckpointTool] 预览：将删除 {len(files_to_delete)} 个文件")
                    for f in files_to_delete:
                        logger.info(f"  - {f}")
                else:
                    files_deleted = self._clean_files(files_to_delete)

            # 创建回退记录
            self._create_rollback_record(checkpoint_id, state)

            logger.info(f"[CheckpointTool] 已回退到: {checkpoint_id}")
            return {
                "success": True,
                "state": state,
                "files_deleted": files_deleted,
                "error": ""
            }

        except Exception as e:
            logger.error(f"[CheckpointTool] 回退时出错: {e}")
            return {
                "success": False,
                "state": None,
                "files_deleted": 0,
                "error": str(e)
            }

    def _serialize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """序列化状态（处理不可序列化的对象）"""
        serialized = {}

        for key, value in state.items():
            if key == "messages":
                serialized[key] = self._serialize_messages(value)
            elif key == "output_manager":
                # Skip - output_manager is no longer in state, managed by registry
                continue
            elif isinstance(value, (str, int, float, bool, type(None), list, dict)):
                serialized[key] = value
            else:
                serialized[key] = str(value)

        return serialized

    def _deserialize_state(self, serialized_state: dict[str, Any]) -> dict[str, Any]:
        """反序列化状态"""
        deserialized = {}

        for key, value in serialized_state.items():
            if key == "messages":
                deserialized[key] = self._deserialize_messages(value)
            elif key == "output_manager":
                # Skip - output_manager is managed by registry
                continue
            else:
                deserialized[key] = value

        return deserialized

    def _serialize_messages(self, messages: list) -> list:
        """序列化消息列表"""
        serialized = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                serialized.append({
                    "type": "human",
                    "content": msg.content
                })
            elif isinstance(msg, AIMessage):
                serialized.append({
                    "type": "ai",
                    "content": msg.content
                })
            elif isinstance(msg, SystemMessage):
                serialized.append({
                    "type": "system",
                    "content": msg.content
                })
            elif isinstance(msg, dict):
                serialized.append(msg)
            else:
                serialized.append({
                    "type": "unknown",
                    "content": str(msg)
                })
        return serialized

    def _deserialize_messages(self, serialized: list) -> list:
        """反序列化消息列表"""
        messages = []
        for msg in serialized:
            msg_type = msg.get("type", "unknown")
            content = msg.get("content", "")

            if msg_type == "human":
                messages.append(HumanMessage(content=content))
            elif msg_type == "ai":
                messages.append(AIMessage(content=content))
            elif msg_type == "system":
                messages.append(SystemMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        return messages

    def _identify_files_to_clean(
        self,
        output_dir: Path,
        target_layer: int
    ) -> list[Path]:
        """识别需要清理的文件（回退点之后的文件）"""
        files_to_delete = []

        try:
            # 识别需要清理的layer目录
            if target_layer < 3:
                layer3_dir = output_dir / "layer_3_detailed"
                if layer3_dir.exists():
                    files_to_delete.extend(layer3_dir.rglob("*"))

            if target_layer < 2:
                layer2_dir = output_dir / "layer_2_concept"
                if layer2_dir.exists():
                    files_to_delete.extend(layer2_dir.rglob("*"))

            # 过滤出文件（不包括目录）
            files_to_delete = [f for f in files_to_delete if f.is_file()]

            # 按路径倒序排列（先删除深层文件）
            files_to_delete.sort(key=lambda x: x.as_posix(), reverse=True)

        except Exception as e:
            logger.warning(f"[CheckpointTool] 识别清理文件时出错: {e}")

        return files_to_delete

    def _clean_files(self, files: list[Path]) -> int:
        """清理文件"""
        deleted_count = 0

        for file_path in files:
            try:
                if file_path.exists():
                    file_path.unlink()
                    deleted_count += 1
                    logger.debug(f"[CheckpointTool] 已删除文件: {file_path}")
            except Exception as e:
                logger.warning(f"[CheckpointTool] 删除文件失败 {file_path}: {e}")

        # 删除空目录
        dirs_to_clean = set()
        for file_path in files:
            if file_path.parent != Path.cwd():
                dirs_to_clean.add(file_path.parent)

        for dir_path in sorted(dirs_to_clean, key=lambda x: len(x.parts), reverse=True):
            try:
                if dir_path.exists() and not any(dir_path.iterdir()):
                    dir_path.rmdir()
                    logger.debug(f"[CheckpointTool] 已删除空目录: {dir_path}")
            except Exception as e:
                pass

        logger.info(f"[CheckpointTool] 清理了 {deleted_count} 个文件")
        return deleted_count

    def _create_rollback_record(
        self,
        original_checkpoint_id: str,
        state: Dict[str, Any]
    ) -> str:
        """创建回退记录checkpoint"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            rollback_id = f"rollback_{timestamp}_to_{original_checkpoint_id}"

            metadata = {
                "layer": state.get("current_layer", 0),
                "description": f"Rollback to {original_checkpoint_id}",
                "original_checkpoint": original_checkpoint_id,
                "is_rollback": True
            }

            serializable_state = self._serialize_state(state)

            self.storage.save(
                project_name=self.project_name,
                timestamp=self.timestamp,
                checkpoint_id=rollback_id,
                state=serializable_state,
                metadata=metadata
            )

            return rollback_id

        except Exception as e:
            logger.warning(f"[CheckpointTool] 创建回退记录失败: {e}")
            return ""


# ==========================================
# 便捷函数
# ==========================================

def save_checkpoint(
    project_name: str,
    state: dict[str, Any],
    layer: int,
    description: str = ""
) -> str:
    """
    便捷函数：保存checkpoint

    Args:
        project_name: 项目名称
        state: 状态字典
        layer: 当前层级
        description: 描述信息

    Returns:
        checkpoint ID，失败时返回空字符串
    """
    tool = CheckpointTool(project_name)
    result = tool.save(state, layer, description)
    return result["checkpoint_id"] if result["success"] else ""


def load_checkpoint(
    project_name: str,
    checkpoint_id: str
) -> dict[str, Any] | None:
    """
    便捷函数：加载checkpoint

    Args:
        project_name: 项目名称
        checkpoint_id: checkpoint ID

    Returns:
        状态字典，失败时返回None
    """
    tool = CheckpointTool(project_name)
    result = tool.load(checkpoint_id)
    return result["state"] if result["success"] else None


def list_checkpoints(
    project_name: str,
    include_all: bool = False
) -> list[dict[str, Any]]:
    """
    便捷函数：列出checkpoint

    Args:
        project_name: 项目名称
        include_all: 是否包含所有项目

    Returns:
        checkpoint列表
    """
    tool = CheckpointTool(project_name)
    result = tool.list(include_all)
    return result["checkpoints"] if result["success"] else []


__all__ = [
    "CheckpointTool",
    "save_checkpoint",
    "load_checkpoint",
    "list_checkpoints",
]
