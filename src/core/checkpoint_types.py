"""
检查点类型定义

用于区分关键检查点（层级/维度完成）和普通检查点（LangGraph 自动保存）
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class CheckpointType(str, Enum):
    """
    检查点类型
    
    - KEY: 关键检查点，用户可回滚的关键节点（层级完成、维度完成等）
    - REGULAR: 普通检查点，LangGraph 自动保存的中间节点
    """
    KEY = "key"
    REGULAR = "regular"


class PlanningPhase(str, Enum):
    """
    规划阶段枚举
    
    清晰定义规划流程的各个阶段，用于检查点标记和状态判断
    """
    # 初始化阶段
    INIT = "init"
    
    # Layer 1: 现状分析
    LAYER1_ANALYZING = "layer1_analyzing"       # Layer 1 执行中
    LAYER1_COMPLETED = "layer1_completed"       # Layer 1 完成
    
    # Layer 2: 规划思路
    LAYER2_CONCEPTING = "layer2_concepting"     # Layer 2 执行中
    LAYER2_COMPLETED = "layer2_completed"       # Layer 2 完成
    
    # Layer 3: 详细规划
    LAYER3_PLANNING = "layer3_planning"         # Layer 3 执行中
    LAYER3_COMPLETED = "layer3_completed"       # Layer 3 完成

    # 最终输出
    FINAL_OUTPUT = "final_output"               # 最终报告生成完成

    # 维度修复完成
    LAYER1_REVISION_COMPLETED = "layer1_revision_completed"  # Layer 1 维度修复完成
    LAYER2_REVISION_COMPLETED = "layer2_revision_completed"  # Layer 2 维度修复完成
    LAYER3_REVISION_COMPLETED = "layer3_revision_completed"  # Layer 3 维度修复完成
    
    @classmethod
    def get_layer(cls, phase: "PlanningPhase") -> int:
        """根据阶段获取层级编号"""
        phase_layer_map = {
            cls.INIT: 0,
            cls.LAYER1_ANALYZING: 1,
            cls.LAYER1_COMPLETED: 1,
            cls.LAYER1_REVISION_COMPLETED: 1,
            cls.LAYER2_CONCEPTING: 2,
            cls.LAYER2_COMPLETED: 2,
            cls.LAYER2_REVISION_COMPLETED: 2,
            cls.LAYER3_PLANNING: 3,
            cls.LAYER3_COMPLETED: 3,
            cls.LAYER3_REVISION_COMPLETED: 3,
            cls.FINAL_OUTPUT: 4,
        }
        return phase_layer_map.get(phase, 0)
    
    @classmethod
    def is_completed(cls, phase: "PlanningPhase") -> bool:
        """判断是否为完成状态"""
        return phase in [
            cls.LAYER1_COMPLETED,
            cls.LAYER2_COMPLETED,
            cls.LAYER3_COMPLETED,
            cls.LAYER1_REVISION_COMPLETED,
            cls.LAYER2_REVISION_COMPLETED,
            cls.LAYER3_REVISION_COMPLETED,
            cls.FINAL_OUTPUT
        ]
    
    @classmethod
    def get_description(cls, phase: "PlanningPhase") -> str:
        """获取阶段的中文描述"""
        descriptions = {
            cls.INIT: "初始状态",
            cls.LAYER1_ANALYZING: "现状分析中",
            cls.LAYER1_COMPLETED: "现状分析完成",
            cls.LAYER1_REVISION_COMPLETED: "现状分析维度修复完成",
            cls.LAYER2_CONCEPTING: "规划思路中",
            cls.LAYER2_COMPLETED: "规划思路完成",
            cls.LAYER2_REVISION_COMPLETED: "规划思路维度修复完成",
            cls.LAYER3_PLANNING: "详细规划中",
            cls.LAYER3_COMPLETED: "详细规划完成",
            cls.LAYER3_REVISION_COMPLETED: "详细规划维度修复完成",
            cls.FINAL_OUTPUT: "最终报告生成",
        }
        return descriptions.get(phase, "未知状态")


class CheckpointMetadata(BaseModel):
    """
    检查点元数据
    
    存储在状态 metadata 字段中，用于标识检查点类型和阶段
    """
    # 检查点类型
    type: CheckpointType = Field(
        default=CheckpointType.REGULAR,
        description="检查点类型：key=关键检查点，regular=普通检查点"
    )
    
    # 规划阶段
    phase: PlanningPhase = Field(
        default=PlanningPhase.INIT,
        description="规划阶段枚举值"
    )
    
    # 层级编号
    layer: int = Field(
        default=0,
        description="所属层级 (0-4)"
    )
    
    # 维度信息（维度级检查点）
    dimension_key: Optional[str] = Field(
        default=None,
        description="维度 key（维度级检查点时设置）"
    )
    dimension_name: Optional[str] = Field(
        default=None,
        description="维度名称（用于展示）"
    )
    
    # 描述
    description: str = Field(
        default="",
        description="检查点描述"
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，用于存储到状态 metadata"""
        result = {
            "checkpoint_type": self.type.value,
            "checkpoint_phase": self.phase.value,
            "checkpoint_layer": self.layer,
            "checkpoint_description": self.description,
        }
        if self.dimension_key:
            result["checkpoint_dimension_key"] = self.dimension_key
        if self.dimension_name:
            result["checkpoint_dimension_name"] = self.dimension_name
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointMetadata":
        """从字典创建实例"""
        # 处理类型转换
        type_str = data.get("checkpoint_type", data.get("type", "regular"))
        phase_str = data.get("checkpoint_phase", data.get("phase", "init"))
        
        try:
            checkpoint_type = CheckpointType(type_str)
        except ValueError:
            checkpoint_type = CheckpointType.REGULAR
        
        try:
            phase = PlanningPhase(phase_str)
        except ValueError:
            phase = PlanningPhase.INIT
        
        return cls(
            type=checkpoint_type,
            phase=phase,
            layer=data.get("checkpoint_layer", data.get("layer", 0)),
            dimension_key=data.get("checkpoint_dimension_key", data.get("dimension_key")),
            dimension_name=data.get("checkpoint_dimension_name", data.get("dimension_name")),
            description=data.get("checkpoint_description", data.get("description", "")),
        )
    
    @classmethod
    def create_layer_checkpoint(
        cls, 
        layer: int, 
        completed: bool = True
    ) -> "CheckpointMetadata":
        """创建层级完成检查点"""
        phase_map = {
            1: PlanningPhase.LAYER1_COMPLETED,
            2: PlanningPhase.LAYER2_COMPLETED,
            3: PlanningPhase.LAYER3_COMPLETED,
        }
        
        phase = phase_map.get(layer, PlanningPhase.INIT)
        
        return cls(
            type=CheckpointType.KEY,
            phase=phase,
            layer=layer,
            description=PlanningPhase.get_description(phase)
        )
    
    @classmethod
    def create_dimension_checkpoint(
        cls,
        layer: int,
        dimension_key: str,
        dimension_name: str
    ) -> "CheckpointMetadata":
        """创建维度完成检查点"""
        analyzing_phase_map = {
            1: PlanningPhase.LAYER1_ANALYZING,
            2: PlanningPhase.LAYER2_CONCEPTING,
            3: PlanningPhase.LAYER3_PLANNING,
        }
        
        return cls(
            type=CheckpointType.KEY,
            phase=analyzing_phase_map.get(layer, PlanningPhase.INIT),
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            description=f"{dimension_name} 完成"
        )


# 便捷函数
def create_key_checkpoint_metadata(
    layer: int,
    phase: Optional[PlanningPhase] = None,
    dimension_key: Optional[str] = None,
    dimension_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    创建关键检查点元数据
    
    Args:
        layer: 层级编号
        phase: 规划阶段（可选，自动推断）
        dimension_key: 维度 key（可选）
        dimension_name: 维度名称（可选）
    
    Returns:
        元数据字典，用于合并到状态 metadata 中
    """
    if phase is None:
        phase_map = {
            1: PlanningPhase.LAYER1_COMPLETED,
            2: PlanningPhase.LAYER2_COMPLETED,
            3: PlanningPhase.LAYER3_COMPLETED,
        }
        phase = phase_map.get(layer, PlanningPhase.INIT)
    
    metadata = CheckpointMetadata(
        type=CheckpointType.KEY,
        phase=phase,
        layer=layer,
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        description=PlanningPhase.get_description(phase)
    )
    
    return metadata.to_dict()


def parse_checkpoint_metadata(metadata: Dict[str, Any]) -> CheckpointMetadata:
    """
    从状态 metadata 解析检查点元数据
    
    Args:
        metadata: 状态 metadata 字典
    
    Returns:
        CheckpointMetadata 实例
    """
    return CheckpointMetadata.from_dict(metadata)


__all__ = [
    "CheckpointType",
    "PlanningPhase",
    "CheckpointMetadata",
    "create_key_checkpoint_metadata",
    "parse_checkpoint_metadata",
]
