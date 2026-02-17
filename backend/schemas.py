"""
Pydantic Schemas for API Request/Response - API请求/响应的Pydantic数据模型
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.core.config import (
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    DEFAULT_ENABLE_REVIEW,
    DEFAULT_STREAM_MODE,
    DEFAULT_STEP_MODE,
)


# ============================================
# Enums
# ============================================

class TaskStatus(str, Enum):
    """任务状态枚举"""
    pending = "pending"
    running = "running"
    paused = "paused"
    reviewing = "reviewing"
    revising = "revising"
    completed = "completed"
    failed = "failed"


# ============================================
# Task Schemas
# ============================================

class PlanningRequest(BaseModel):
    """规划任务请求"""
    project_name: str = Field(..., description="项目名称/村庄名称")
    village_data: str = Field(..., description="村庄现状数据")
    task_description: str = Field(default=DEFAULT_TASK_DESCRIPTION, description="规划任务描述")
    constraints: str = Field(default=DEFAULT_CONSTRAINTS, description="规划约束条件")
    need_human_review: bool = Field(default=DEFAULT_ENABLE_REVIEW, description="是否需要人工审核")
    stream_mode: bool = Field(default=DEFAULT_STREAM_MODE, description="是否使用流式输出")
    step_mode: bool = Field(default=DEFAULT_STEP_MODE, description="是否使用步进模式")


class TaskResponse(BaseModel):
    """任务创建响应"""
    task_id: str = Field(..., description="任务ID")
    status: TaskStatus = Field(..., description="任务状态")
    message: str = Field(..., description="响应消息")


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str = Field(..., description="任务ID")
    status: TaskStatus = Field(..., description="任务状态")
    progress: Optional[float] = Field(None, description="进度百分比 (0-100)")
    current_layer: Optional[str] = Field(None, description="当前层级")
    message: Optional[str] = Field(None, description="状态消息")
    result: Optional[Dict[str, Any]] = Field(None, description="任务结果")
    error: Optional[str] = Field(None, description="错误信息")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


# ============================================
# Review & Revision Schemas
# ============================================

class ReviewRejectRequest(BaseModel):
    """审查驳回请求"""
    feedback: str = Field(..., description="驳回反馈/修改意见", min_length=1)
    target_dimensions: Optional[List[str]] = Field(None, description="目标维度列表（仅Layer 3详细规划需要）")


class RollbackRequest(BaseModel):
    """回退请求"""
    checkpoint_id: str = Field(..., description="检查点ID")


class ReviewDataResponse(BaseModel):
    """审查数据响应"""
    task_id: str = Field(..., description="任务ID")
    current_layer: int = Field(..., description="当前层级 (1/2/3)")
    content: str = Field(..., description="当前层级内容")
    summary: Dict[str, Any] = Field(..., description="内容摘要")
    available_dimensions: List[str] = Field(..., description="可修改的维度列表")
    checkpoints: List[Dict[str, Any]] = Field(..., description="可用检查点列表")


class ReviewActionResponse(BaseModel):
    """审查操作响应"""
    success: bool = Field(..., description="操作是否成功")
    message: str = Field(..., description="响应消息")
    task_status: TaskStatus = Field(..., description="任务当前状态")
    revision_progress: Optional[Dict[str, Any]] = Field(None, description="修复进度信息")


# ============================================
# Session Schemas
# ============================================

class ConversationMessage(BaseModel):
    """会话消息"""
    role: str = Field(..., description="消息角色 (user/assistant/system)")
    content: str = Field(..., description="消息内容")
    message_type: str = Field(default="text", description="消息类型")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    metadata: Optional[Dict[str, Any]] = Field(None, description="额外元数据")


class ConversationState(BaseModel):
    """会话状态"""
    conversation_id: str = Field(..., description="会话ID")
    status: str = Field(default="idle", description="会话状态")
    project_name: Optional[str] = Field(None, description="项目名称")
    task_id: Optional[str] = Field(None, description="关联任务ID")
    messages: List[ConversationMessage] = Field(default_factory=list, description="消息列表")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


# ============================================
# File Schemas
# ============================================

class FileUploadResponse(BaseModel):
    """文件上传响应"""
    success: bool = Field(..., description="是否成功")
    filename: str = Field(..., description="文件名")
    content: str = Field(..., description="文件内容")
    size: int = Field(..., description="文件大小（字节）")
    message: str = Field(..., description="响应消息")


# ============================================
# Village Schemas
# ============================================

class VillageInfo(BaseModel):
    """村庄信息"""
    name: str = Field(..., description="村庄名称")
    session_count: int = Field(..., description="关联会话数")
    last_updated: Optional[datetime] = Field(None, description="最后更新时间")


class VillageDetail(BaseModel):
    """村庄详情"""
    name: str = Field(..., description="村庄名称")
    sessions: List[Dict[str, Any]] = Field(default_factory=list, description="会话列表")
    # Layer outputs (统一命名)
    analysis_reports: Optional[Dict[str, str]] = Field(None, description="Layer 1: 现状分析维度报告")
    concept_reports: Optional[Dict[str, str]] = Field(None, description="Layer 2: 规划思路维度报告")
    detail_reports: Optional[Dict[str, str]] = Field(None, description="Layer 3: 详细规划维度报告")
    final_report: Optional[str] = Field(None, description="最终报告")


# ============================================
# Health Check
# ============================================

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="服务状态")
    version: str = Field(default="1.0.0", description="API版本")
    timestamp: datetime = Field(default_factory=datetime.now, description="检查时间")
