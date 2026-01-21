"""
Checkpoint JSON存储实现

负责checkpoint的JSON格式持久化，支持保存、加载、列出、删除操作。
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class JsonCheckpointStorage:
    """
    Checkpoint的JSON存储实现

    提供基于文件系统的checkpoint持久化功能。
    文件格式：results/{project_name}/{timestamp}/checkpoints/checkpoint_XXX_layerY_completed.json
    """

    def __init__(self, base_path: Optional[Path] = None):
        """
        初始化JSON存储

        Args:
            base_path: 基础路径，默认为 results/
        """
        self.base_path = base_path or Path("results")

    def _get_checkpoint_dir(self, project_name: str, timestamp: str) -> Path:
        """
        获取checkpoint存储目录

        Args:
            project_name: 项目名称
            timestamp: 时间戳

        Returns:
            checkpoint目录路径
        """
        # 清理项目名称（移除特殊字符）
        safe_name = self._sanitize_name(project_name)
        checkpoint_dir = self.base_path / safe_name / timestamp / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return checkpoint_dir

    def _sanitize_name(self, name: str) -> str:
        """
        清理文件名（移除不安全字符）

        Args:
            name: 原始名称

        Returns:
            清理后的名称
        """
        import re
        # 替换不安全的文件名字符
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

    def save(
        self,
        project_name: str,
        timestamp: str,
        checkpoint_id: str,
        state: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> Optional[str]:
        """
        保存checkpoint到JSON文件

        Args:
            project_name: 项目名称
            timestamp: 时间戳
            checkpoint_id: checkpoint ID
            state: 状态字典（会被序列化）
            metadata: 元数据字典

        Returns:
            保存的文件路径，失败时返回None
        """
        try:
            checkpoint_dir = self._get_checkpoint_dir(project_name, timestamp)
            file_path = checkpoint_dir / f"{checkpoint_id}.json"

            # 序列化状态（处理不可序列化的对象）
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

    def load(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        从JSON文件加载checkpoint

        Args:
            file_path: checkpoint文件路径

        Returns:
            包含state和metadata的字典，失败时返回None
        """
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

    def list_checkpoints(self, project_name: str, timestamp: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出项目的所有checkpoint

        Args:
            project_name: 项目名称
            timestamp: 时间戳（可选，如果不提供则列出所有时间戳的checkpoint）

        Returns:
            checkpoint信息列表
        """
        try:
            safe_name = self._sanitize_name(project_name)

            if timestamp:
                # 列出指定时间戳的checkpoint
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
                # 列出所有时间戳的checkpoint
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
        """
        删除checkpoint文件

        Args:
            file_path: checkpoint文件路径

        Returns:
            是否成功删除
        """
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

    def _get_checkpoint_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        从checkpoint文件中提取元数据信息

        Args:
            file_path: checkpoint文件路径

        Returns:
            checkpoint信息字典
        """
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
        """
        准备数据用于序列化（处理不可序列化的对象）

        Args:
            data: 原始数据

        Returns:
            可序列化的数据
        """
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
            # 对象：转换为字典（仅包含基本属性）
            return {
                k: self._prepare_for_serialization(v)
                for k, v in data.__dict__.items()
                if not k.startswith('_') and not callable(v)
            }
        elif isinstance(data, (str, int, float, bool, type(None))):
            return data
        else:
            # 其他类型：转换为字符串
            return str(data)


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    # 测试JSON存储
    print("=== 测试JsonCheckpointStorage ===")

    storage = JsonCheckpointStorage()

    # 测试保存
    test_state = {
        "project_name": "测试项目",
        "current_layer": 1,
        "analysis_report": "这是一个测试报告",
        "messages": ["消息1", "消息2"]
    }

    test_metadata = {
        "layer": 1,
        "description": "Layer 1完成"
    }

    file_path = storage.save(
        project_name="测试项目",
        timestamp="20240101_120000",
        checkpoint_id="checkpoint_001_layer1_completed",
        state=test_state,
        metadata=test_metadata
    )

    print(f"保存的文件路径: {file_path}")

    # 测试列出
    checkpoints = storage.list_checkpoints("测试项目")
    print(f"\n找到 {len(checkpoints)} 个checkpoint:")
    for cp in checkpoints:
        print(f"  - {cp['checkpoint_id']}: {cp['description']}")

    # 测试加载
    if file_path:
        loaded = storage.load(file_path)
        if loaded:
            print(f"\n加载的checkpoint: {loaded['checkpoint_id']}")
            print(f"状态: {loaded['state']}")
