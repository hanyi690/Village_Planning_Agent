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

class StartPlanningRequest(BaseModel):
    """启动规划会话请求"""
    project_name: str = Field(..., description="项目/村庄名称")
    village_data: str = Field(..., description="村庄基础数据")
    village_name: str = Field("", description="村庄名称（用于提示词约束）")
    task_description: str = Field(default=DEFAULT_TASK_DESCRIPTION, description="规划任务描述")
    constraints: str = Field(default=DEFAULT_CONSTRAINTS, description="规划约束条件")
    enable_review: bool = Field(default=DEFAULT_ENABLE_REVIEW, description="启用交互式审查")
    stream_mode: bool = Field(default=DEFAULT_STREAM_MODE, description="启用流式输出")
    step_mode: bool = Field(default=DEFAULT_STEP_MODE, description="启用分步执行模式")


# ============================================
# Review & Revision Schemas
# ============================================

class ReviewActionRequest(BaseModel):
    """审查操作请求"""
    action: str = Field(..., description="操作类型: approve, reject, rollback")
    feedback: str = Field("", description="驳回反馈（reject 时必填）")
    dimensions: Optional[List[str]] = Field(None, description="需要修订的维度列表")
    checkpoint_id: Optional[str] = Field(None, description="回滚目标检查点（rollback 时必填）")


class ResumeRequest(BaseModel):
    """恢复执行请求"""
    checkpoint_id: str = Field(..., description="目标检查点 ID")
    project_name: str = Field(..., description="项目名称")


# ============================================
# Session Schemas
# ============================================

class SessionStatusResponse(BaseModel):
    """会话状态响应"""
    session_id: str = Field(..., description="会话ID")
    status: str = Field(..., description="会话状态")
    current_layer: Optional[int] = Field(None, description="当前层级")
    previous_layer: Optional[int] = Field(None, description="前一个层级")
    created_at: Optional[str] = Field(None, description="创建时间")
    progress: Optional[float] = Field(None, description="进度百分比")
    layer_1_completed: bool = Field(False, description="Layer 1 是否完成")
    layer_2_completed: bool = Field(False, description="Layer 2 是否完成")
    layer_3_completed: bool = Field(False, description="Layer 3 是否完成")
    pause_after_step: bool = Field(False, description="是否处于暂停状态")
    execution_complete: bool = Field(False, description="执行是否完成")
    execution_error: Optional[str] = Field(None, description="执行错误信息")
    messages: List[Dict[str, Any]] = Field(default_factory=list, description="消息列表")
    ui_messages: List[Dict[str, Any]] = Field(default_factory=list, description="UI消息列表")
    revision_history: List[Dict[str, Any]] = Field(default_factory=list, description="修订历史")
    last_checkpoint_id: str = Field("", description="最后一个检查点ID")


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


# ============================================
# UI Message Schemas
# ============================================

class CreateUIMessageRequest(BaseModel):
    """创建 UI 消息请求"""
    message_id: str = Field(..., description="前端消息ID（唯一标识，用于 upsert）")
    role: str = Field(..., description="消息角色: user, assistant, system")
    content: str = Field(..., description="消息内容")
    message_type: str = Field("text", description="消息类型: text, markdown, status")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class ChatMessageRequest(BaseModel):
    """对话消息请求"""
    message: str = Field(..., description="用户消息内容")


class RunDimensionsRequest(BaseModel):
    """运行维度分析请求"""
    layer: int = Field(..., description="层级 (1, 2, 或 3)")
    dimension_keys: List[str] = Field(..., description="要分析的维度键列表")
