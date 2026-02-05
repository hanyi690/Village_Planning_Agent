"""
Tasks API endpoints - Unified task management
任务API端点 - 统一任务管理
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Body
from fastapi.responses import StreamingResponse
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
import uuid
import asyncio
import json
from datetime import datetime
from pathlib import Path
import sys
import logging

# Add parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from schemas import (
    TaskStatus,
    TaskResponse,
    TaskStatusResponse,
    ReviewRejectRequest,
    RollbackRequest,
    ReviewDataResponse,
    ReviewActionResponse,
)
from services.shared_task_manager import task_manager

router = APIRouter()

# Setup logger
logger = logging.getLogger(__name__)


# ============================================
# Request Schemas
# ============================================

class CreateTaskRequest(BaseModel):
    """Unified task creation request"""
    project_name: str = Field(..., description="项目名称/村庄名称", min_length=1)
    village_data: str = Field(..., description="村庄现状数据（文件内容或直接文本）")
    task_description: str = Field(default="制定村庄总体规划方案", description="规划任务描述")
    constraints: str = Field(default="无特殊约束", description="规划约束条件")
    need_human_review: bool = Field(default=False, description="是否需要人工审核")
    stream_mode: bool = Field(default=False, description="是否使用流式输出")
    step_mode: bool = Field(default=False, description="是否使用步进模式")
    input_mode: str = Field(default="text", description="输入模式: text | file-base64")


# ============================================
# Core Task Endpoints
# ============================================

@router.post("", response_model=TaskResponse)
async def create_task(
    background_tasks: BackgroundTasks,
    request: CreateTaskRequest
):
    """
    Create a new planning task (unified endpoint)
    创建新的规划任务（统一入口）
    """
    try:
        # Validate input
        if not request.project_name or not request.project_name.strip():
            logger.error(f"[Task] Empty project_name: '{request.project_name}'")
            raise HTTPException(status_code=400, detail="项目名称不能为空")

        if not request.village_data or len(request.village_data.strip()) < 10:
            logger.error(f"[Task] Invalid village_data: length={len(request.village_data) if request.village_data else 0}")
            raise HTTPException(status_code=400, detail="村庄数据不能为空或过短（至少需要10个字符）")

        # Log received data
        logger.info(f"[Task] Request validated: project={request.project_name}, data_length={len(request.village_data)}")
        logger.debug(f"[Task] village_data preview: {request.village_data[:100]}...")

        # Generate task ID
        task_id = str(uuid.uuid4())

        # Create planning request
        from schemas import PlanningRequest
        planning_request = PlanningRequest(
            project_name=request.project_name,
            village_data=request.village_data,
            task_description=request.task_description,
            constraints=request.constraints,
            need_human_review=request.need_human_review,
            stream_mode=request.stream_mode,
            step_mode=request.step_mode
        )

        # Initialize task
        task_manager.create_task(task_id, planning_request)

        # Add background task
        background_tasks.add_task(
            task_manager.run_planning_task,
            task_id,
            planning_request
        )

        logger.info(f"[Task] Task {task_id} created successfully for project: {request.project_name}")
        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.pending,
            message=f"规划任务已创建，正在处理村庄: {request.project_name}"
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[Task] Failed to create task: {str(e)}")
        logger.error(f"[Task] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Get task status and results
    获取任务状态和结果
    """
    task_info = task_manager.get_task(task_id)

    if not task_info:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    return TaskStatusResponse(
        task_id=task_id,
        status=task_info["status"],
        progress=task_info.get("progress"),
        current_layer=task_info.get("current_layer"),
        message=task_info.get("message"),
        result=task_info.get("result"),
        error=task_info.get("error"),
        created_at=task_info["created_at"],
        updated_at=task_info["updated_at"]
    )


@router.get("/{task_id}/stream")
async def stream_task_status(task_id: str):
    """
    Stream task status using Server-Sent Events
    使用SSE流式传输任务状态
    """
    task_info = task_manager.get_task(task_id)

    if not task_info:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    async def event_generator():
        """Generate SSE events"""
        while True:
            task_info = task_manager.get_task(task_id)
            if not task_info:
                yield f": {'error': 'Task not found'}\n\n"
                break

            # Build event data
            event_data = {
                "type": "status",
                "task_id": task_id,
                "data": {
                    "status": task_info["status"],
                    "progress": task_info.get("progress", 0),
                    "current_layer": task_info.get("current_layer"),
                    "message": task_info.get("message", ""),
                    "updated_at": task_info["updated_at"].isoformat()
                }
            }

            # Include result if completed
            if task_info["status"] == TaskStatus.completed:
                event_data["type"] = "complete"
                event_data["data"]["result"] = task_info.get("result")
                yield f"data: {json.dumps(event_data)}\n\n"
                break

            # Include error if failed
            if task_info["status"] == TaskStatus.failed:
                event_data["type"] = "failed"
                event_data["data"]["error"] = task_info.get("error")
                yield f"data: {json.dumps(event_data)}\n\n"
                break

            yield f"data: {json.dumps(event_data)}\n\n"

            # Wait before next update
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    """
    Delete a task (only completed or failed tasks)
    删除任务（仅已完成或失败的任务）
    """
    task_info = task_manager.get_task(task_id)

    if not task_info:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    if task_info["status"] not in [TaskStatus.completed, TaskStatus.failed]:
        raise HTTPException(
            status_code=400,
            detail="只能删除已完成或失败的任务"
        )

    task_manager.delete_task(task_id)
    return {"message": f"任务已删除: {task_id}"}


@router.get("")
async def list_tasks():
    """
    List all tasks
    列出所有任务
    """
    tasks = task_manager.list_tasks()
    return {
        "total": len(tasks),
        "tasks": [
            {
                "task_id": task_id,
                "status": task["status"],
                "project_name": task.get("request", {}).get("project_name"),
                "created_at": task["created_at"].isoformat()
            }
            for task_id, task in tasks.items()
        ]
    }


# ============================================
# Review & Revision Endpoints
# ============================================

@router.get("/{task_id}/review-data", response_model=ReviewDataResponse)
async def get_review_data(task_id: str):
    """
    Get review data for a paused task
    获取暂停任务的审查数据
    """
    task_info = task_manager.get_task(task_id)

    if not task_info:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    # Check if task is in reviewable state
    if task_info["status"] not in [TaskStatus.paused, TaskStatus.reviewing]:
        raise HTTPException(
            status_code=400,
            detail=f"任务状态不允许审查: {task_info['status']}"
        )

    try:
        # Get current layer content from task result
        result = task_info.get("result", {})
        current_layer = task_info.get("current_layer", "layer_1")

        # Extract content based on current layer
        content = ""
        available_dimensions = []

        if current_layer == "layer_1":
            # Layer 1: Analysis report
            content = result.get("analysis_report", "Layer 1 analysis not available")
            available_dimensions = []  # Layer 1 has no dimensions to revise
        elif current_layer == "layer_2":
            # Layer 2: Planning concept
            content = result.get("planning_concept", "Layer 2 concept not available")
            available_dimensions = []  # Layer 2 has no dimensions to revise
        elif current_layer == "layer_3":
            # Layer 3: Detailed plan with dimensions
            content = result.get("detailed_plan", "Layer 3 detailed plan not available")
            available_dimensions = [
                "industry",
                "master_plan",
                "traffic",
                "public_service",
                "infrastructure",
                "ecological",
                "disaster_prevention",
                "heritage",
                "landscape",
                "project_bank"
            ]

        # Build summary
        summary = {
            "word_count": len(content),
            "layer": current_layer,
            "has_content": bool(content)
        }

        # Get available checkpoints
        checkpoints = task_manager.get_task_checkpoints(task_id)

        # Parse current layer number
        layer_number = 1
        if "layer_2" in current_layer:
            layer_number = 2
        elif "layer_3" in current_layer:
            layer_number = 3

        return ReviewDataResponse(
            task_id=task_id,
            current_layer=layer_number,
            content=content,
            summary=summary,
            available_dimensions=available_dimensions,
            checkpoints=checkpoints
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取审查数据失败: {str(e)}")


@router.post("/{task_id}/review/approve", response_model=ReviewActionResponse)
async def approve_review(task_id: str):
    """
    Approve review and continue execution
    批准审查并继续执行
    """
    task_info = task_manager.get_task(task_id)

    if not task_info:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    if task_info["status"] not in [TaskStatus.paused, TaskStatus.reviewing]:
        raise HTTPException(
            status_code=400,
            detail=f"任务状态不允许批准: {task_info['status']}"
        )

    try:
        # Call task manager to approve and continue
        result = await task_manager.approve_review(task_id)

        return ReviewActionResponse(
            success=result.get("success", False),
            message=result.get("message", "审查已批准，任务继续执行"),
            task_status=task_info.get("status", TaskStatus.running),
            revision_progress=None
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批准审查失败: {str(e)}")


@router.post("/{task_id}/review/reject", response_model=ReviewActionResponse)
async def reject_review(task_id: str, request: ReviewRejectRequest):
    """
    Reject review and trigger revision
    驳回审查并触发修复
    """
    task_info = task_manager.get_task(task_id)

    if not task_info:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    if task_info["status"] not in [TaskStatus.paused, TaskStatus.reviewing]:
        raise HTTPException(
            status_code=400,
            detail=f"任务状态不允许驳回: {task_info['status']}"
        )

    try:
        # Call task manager to reject and trigger revision
        result = await task_manager.reject_review(
            task_id=task_id,
            feedback=request.feedback,
            target_dimensions=request.target_dimensions
        )

        return ReviewActionResponse(
            success=result.get("success", False),
            message=result.get("message", "审查已驳回，开始修复"),
            task_status=task_info.get("status", TaskStatus.revising),
            revision_progress=result.get("revision_progress")
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"驳回审查失败: {str(e)}")


@router.post("/{task_id}/rollback", response_model=ReviewActionResponse)
async def rollback_checkpoint(task_id: str, request: RollbackRequest):
    """
    Rollback to a specific checkpoint
    回退到指定checkpoint
    """
    task_info = task_manager.get_task(task_id)

    if not task_info:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    try:
        # Call task manager to rollback
        result = await task_manager.rollback_to_checkpoint(
            task_id=task_id,
            checkpoint_id=request.checkpoint_id
        )

        return ReviewActionResponse(
            success=result.get("success", False),
            message=result.get("message", f"已回退到checkpoint: {request.checkpoint_id}"),
            task_status=task_info.get("status", TaskStatus.paused),
            revision_progress=None
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回退失败: {str(e)}")


@router.post("/{task_id}/resume", response_model=ReviewActionResponse)
async def resume_task(task_id: str):
    """
    Resume a paused task
    恢复暂停的任务
    """
    task_info = task_manager.get_task(task_id)

    if not task_info:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    if task_info["status"] != TaskStatus.paused:
        raise HTTPException(
            status_code=400,
            detail=f"任务状态不允许恢复: {task_info['status']}"
        )

    try:
        # Call task manager to resume
        result = await task_manager.resume_task(task_id)

        return ReviewActionResponse(
            success=result.get("success", False),
            message=result.get("message", "任务已恢复"),
            task_status=task_info.get("status", TaskStatus.running),
            revision_progress=None
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复任务失败: {str(e)}")
