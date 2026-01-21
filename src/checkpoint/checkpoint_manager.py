"""
Checkpoint管理器 - 核心管理逻辑

负责checkpoint的保存、加载、回退等核心功能。
处理状态序列化/反序列化、元数据管理、文件清理等。
"""

import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from .json_storage import JsonCheckpointStorage
from ..utils.logger import get_logger

logger = get_logger(__name__)


class CheckpointManager:
    """
    Checkpoint管理器

    提供checkpoint的完整生命周期管理：
    - 保存checkpoint
    - 加载checkpoint
    - 列出checkpoint
    - 回退到指定checkpoint
    - 文件清理
    """

    # Checkpoint ID格式
    CHECKPOINT_ID_FORMAT = "checkpoint_{layer:03d}_layer{layer}_completed"

    def __init__(
        self,
        project_name: str,
        timestamp: Optional[str] = None,
        storage: Optional[JsonCheckpointStorage] = None
    ):
        """
        初始化CheckpointManager

        Args:
            project_name: 项目名称
            timestamp: 时间戳（可选，如果不提供则使用当前时间）
            storage: 存储后端（可选，默认使用JsonCheckpointStorage）
        """
        self.project_name = self._sanitize_name(project_name)
        self.timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.storage = storage or JsonCheckpointStorage()
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
            logger.info(f"[CheckpointManager] 加载了 {len(self.checkpoint_index)} 个checkpoint索引")
        except Exception as e:
            logger.warning(f"[CheckpointManager] 加载索引失败: {e}")
            self.checkpoint_index = {}

    def save_checkpoint(
        self,
        state: Dict[str, Any],
        layer: int,
        description: str = ""
    ) -> str:
        """
        保存checkpoint

        Args:
            state: 当前状态字典（VillagePlanningState）
            layer: 当前层级 (1/2/3)
            description: 描述信息

        Returns:
            checkpoint ID
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

            # 序列化状态（处理不可序列化的对象）
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

                logger.info(f"[CheckpointManager] Checkpoint已保存: {checkpoint_id}")
                return checkpoint_id
            else:
                logger.error(f"[CheckpointManager] Checkpoint保存失败")
                return ""

        except Exception as e:
            logger.error(f"[CheckpointManager] 保存checkpoint时出错: {e}")
            return ""

    def load_checkpoint(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        """
        加载checkpoint

        Args:
            checkpoint_id: checkpoint ID

        Returns:
            恢复的状态字典，失败时返回None
        """
        try:
            # 从索引中查找
            if checkpoint_id not in self.checkpoint_index:
                logger.error(f"[CheckpointManager] Checkpoint不存在: {checkpoint_id}")
                return None

            file_path = self.checkpoint_index[checkpoint_id]["file_path"]

            # 从存储加载
            data = self.storage.load(file_path)
            if not data:
                return None

            # 反序列化状态
            state = self._deserialize_state(data["state"])

            logger.info(f"[CheckpointManager] Checkpoint已加载: {checkpoint_id}")
            return state

        except Exception as e:
            logger.error(f"[CheckpointManager] 加载checkpoint时出错: {e}")
            return None

    def list_checkpoints(self, include_all_projects: bool = False) -> List[Dict[str, Any]]:
        """
        列出checkpoint

        Args:
            include_all_projects: 是否包含所有项目（False则仅当前项目）

        Returns:
            checkpoint信息列表
        """
        try:
            if include_all_projects:
                # 列出所有项目的checkpoint
                checkpoints = self.storage.list_checkpoints(self.project_name, None)
            else:
                # 仅当前项目
                checkpoints = [
                    cp for cp in self.checkpoint_index.values()
                ]

            # 按层级排序
            return sorted(checkpoints, key=lambda x: x.get("layer", 0))

        except Exception as e:
            logger.error(f"[CheckpointManager] 列出checkpoint时出错: {e}")
            return []

    def get_latest_checkpoint(self) -> Optional[Dict[str, Any]]:
        """
        获取最新的checkpoint

        Returns:
            最新的checkpoint信息，如果没有则返回None
        """
        if not self.checkpoint_index:
            return None

        # 返回层级最大的checkpoint
        latest = max(
            self.checkpoint_index.values(),
            key=lambda x: x.get("layer", 0)
        )
        return latest

    def rollback_to_checkpoint(
        self,
        checkpoint_id: str,
        current_output_dir: Optional[Path] = None,
        dry_run: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        回退到指定checkpoint

        Args:
            checkpoint_id: 目标checkpoint ID
            current_output_dir: 当前输出目录（用于文件清理）
            dry_run: 是否仅预览（不实际删除文件）

        Returns:
            恢复的状态字典，失败时返回None
        """
        try:
            # 加载checkpoint
            state = self.load_checkpoint(checkpoint_id)
            if not state:
                logger.error(f"[CheckpointManager] 无法加载checkpoint: {checkpoint_id}")
                return None

            # 获取目标checkpoint的层级
            target_layer = self.checkpoint_index[checkpoint_id].get("layer", 0)

            # 清理回退点之后的文件
            if current_output_dir:
                files_to_delete = self._identify_files_to_clean(
                    current_output_dir,
                    target_layer
                )

                if dry_run:
                    logger.info(f"[CheckpointManager] 预览：将删除 {len(files_to_delete)} 个文件")
                    for f in files_to_delete:
                        logger.info(f"  - {f}")
                    return state
                else:
                    self._clean_files(files_to_delete)

            # 创建回退记录
            rollback_id = self._create_rollback_record(checkpoint_id, state)

            logger.info(f"[CheckpointManager] 已回退到: {checkpoint_id}")
            return state

        except Exception as e:
            logger.error(f"[CheckpointManager] 回退时出错: {e}")
            return None

    def _serialize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        序列化状态（处理不可序列化的对象）

        Args:
            state: 原始状态

        Returns:
            可序列化的状态
        """
        serialized = {}

        for key, value in state.items():
            if key == "messages":
                # 序列化消息列表
                serialized[key] = self._serialize_messages(value)
            elif key == "output_manager":
                # 保存输出管理器信息（不保存实例）
                if value:
                    serialized[key] = {
                        "_type": "OutputManager",
                        "project_name": getattr(value, "project_name", ""),
                        "timestamp": getattr(value, "timestamp", ""),
                        "output_path": str(getattr(value, "output_path", ""))
                    }
            elif isinstance(value, (str, int, float, bool, type(None), list, dict)):
                serialized[key] = value
            else:
                # 其他类型转为字符串
                serialized[key] = str(value)

        return serialized

    def _deserialize_state(self, serialized_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        反序列化状态

        Args:
            serialized_state: 序列化的状态

        Returns:
            恢复的状态字典
        """
        deserialized = {}

        for key, value in serialized_state.items():
            if key == "messages":
                # 反序列化消息列表
                deserialized[key] = self._deserialize_messages(value)
            elif key == "output_manager":
                # 重建OutputManager（稍后由调用者处理）
                deserialized[key] = None  # 占位符
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
    ) -> List[Path]:
        """
        识别需要清理的文件（回退点之后的文件）

        Args:
            output_dir: 输出目录
            target_layer: 目标层级

        Returns:
            需要删除的文件路径列表
        """
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
            logger.warning(f"[CheckpointManager] 识别清理文件时出错: {e}")

        return files_to_delete

    def _clean_files(self, files: List[Path]) -> int:
        """
        清理文件

        Args:
            files: 文件路径列表

        Returns:
            成功删除的文件数
        """
        deleted_count = 0

        for file_path in files:
            try:
                if file_path.exists():
                    file_path.unlink()
                    deleted_count += 1
                    logger.debug(f"[CheckpointManager] 已删除文件: {file_path}")
            except Exception as e:
                logger.warning(f"[CheckpointManager] 删除文件失败 {file_path}: {e}")

        # 删除空目录
        dirs_to_clean = set()
        for file_path in files:
            if file_path.parent != Path.cwd():
                dirs_to_clean.add(file_path.parent)

        for dir_path in sorted(dirs_to_clean, key=lambda x: len(x.parts), reverse=True):
            try:
                if dir_path.exists() and not any(dir_path.iterdir()):
                    dir_path.rmdir()
                    logger.debug(f"[CheckpointManager] 已删除空目录: {dir_path}")
            except Exception as e:
                pass  # 忽略删除目录失败

        logger.info(f"[CheckpointManager] 清理了 {deleted_count} 个文件")
        return deleted_count

    def _create_rollback_record(
        self,
        original_checkpoint_id: str,
        state: Dict[str, Any]
    ) -> str:
        """
        创建回退记录checkpoint

        Args:
            original_checkpoint_id: 原始checkpoint ID
            state: 当前状态

        Returns:
            新的checkpoint ID
        """
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
            logger.warning(f"[CheckpointManager] 创建回退记录失败: {e}")
            return ""


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    print("=== 测试CheckpointManager ===")

    manager = CheckpointManager("测试项目")

    # 测试保存
    test_state = {
        "project_name": "测试项目",
        "current_layer": 1,
        "analysis_report": "测试报告",
        "messages": []
    }

    checkpoint_id = manager.save_checkpoint(test_state, layer=1, description="Layer 1完成")
    print(f"保存的checkpoint: {checkpoint_id}")

    # 测试列出
    checkpoints = manager.list_checkpoints()
    print(f"\n找到 {len(checkpoints)} 个checkpoint:")
    for cp in checkpoints:
        print(f"  - {cp['checkpoint_id']}: {cp['description']}")

    # 测试加载
    if checkpoint_id:
        loaded_state = manager.load_checkpoint(checkpoint_id)
        if loaded_state:
            print(f"\n加载的状态: {loaded_state['project_name']}")
