"""
Review Service - Review Actions Management

This service handles review-related operations:
- Approve planning step
- Reject with feedback
- Rollback to checkpoint
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from app.api.schemas import TaskStatus
from app.services.sse import sse_manager
from app.services.checkpoint import checkpoint_service
from app.services.runtime import PlanningRuntimeService
from app.database.operations import (
    update_planning_session_async,
    get_planning_session_async,
)

logger = logging.getLogger(__name__)


# ============================================
# Response Models (Pydantic)
# ============================================

class ApproveResponse(BaseModel):
    """Response model for approve action."""
    message: str = Field(default="approved")
    session_id: str
    resumed: bool = Field(default=True)
    current_layer: Optional[int] = None


class RejectResponse(BaseModel):
    """Response model for reject action."""
    message: str = Field(default="rejected")
    session_id: str
    resumed: bool = Field(default=True)


class RollbackResponse(BaseModel):
    """Response model for rollback action."""
    message: str
    phase: str
    target_layer: int
    resumed: bool = Field(default=False)


class ReviewService:
    """
    Review actions management service.

    Provides:
    - Approve planning step with resume
    - Reject with feedback and resume
    - Rollback to checkpoint
    """

    @staticmethod
    async def approve(
        session_id: str,
        review_id: Optional[str] = None,
    ) -> ApproveResponse:
        """Approve the current planning step and resume from interrupt."""
        from app.agent.state import get_layer_dimensions, get_layer_name

        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found in checkpoint")

        next_layer, next_phase = await checkpoint_service.calculate_next_layer(session_id, state)

        logger.info(f"[ReviewService] [{session_id}] Approving: phase={state.get('phase', 'init')} -> {next_phase}")

        # Resume from interrupt: approve handled in layer_completion_check
        logger.info(
            "[ReviewService] [%s] APPROVE: phase=%s, next_phase=%s, next_layer=%s",
            session_id, state.get('phase', 'init'), next_phase, next_layer,
        )
        asyncio.create_task(PlanningRuntimeService.resume_from_interrupt(
            session_id,
            resume_data={"action": "approve"},
        ))

        logger.info(f"[ReviewService] [{session_id}] Approved, phase={state.get('phase', 'init')} -> {next_phase}, next_layer={next_layer}")
        logger.info(f"[ReviewService] [{session_id}] layer_started 将由 Agent 恢复执行时自动发送")

        # Update stream state
        sse_manager.set_stream_state(session_id, "active")

        # Update database status
        await update_planning_session_async(session_id, {
            "status": TaskStatus.running,
        })

        # Submit review decision if review_id provided
        if review_id:
            try:
                from app.tools.web_review_tool import WebReviewTool
                web_review_tool = WebReviewTool()
                web_review_tool.submit_review_decision(review_id=review_id, action="approve")
            except Exception as e:
                logger.warning(f"[ReviewService] [{session_id}] Failed to submit review decision: {e}")

        logger.info(f"[ReviewService] [{session_id}] Approved, next_layer={next_layer}")

        return ApproveResponse(
            session_id=session_id,
            message="approved",
            resumed=True,
            current_layer=next_layer,
        )

    @staticmethod
    async def reject(
        session_id: str,
        feedback: str,
        dimensions: Optional[List[str]] = None,
        review_id: Optional[str] = None,
        images: Optional[List[Dict]] = None,
    ) -> RejectResponse:
        """Reject the current planning step with feedback — resume from interrupt."""
        if not feedback:
            raise ValueError("Feedback is required for rejection")

        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found in checkpoint")

        # Resume from interrupt: reject handled in layer_completion_check
        logger.info(
            "[ReviewService] [%s] REJECT: phase=%s, feedback=%s, dimensions=%s",
            session_id, state.get('phase', 'init'), feedback[:100], dimensions,
        )
        asyncio.create_task(PlanningRuntimeService.resume_from_interrupt(
            session_id,
            resume_data={
                "action": "reject",
                "feedback": feedback,
                "dimensions": dimensions or [],
                "images": images or [],
            },
        ))

        logger.info(f"[ReviewService] [{session_id}] Rejected with feedback, dimensions={dimensions}")

        # Update database status
        await update_planning_session_async(session_id, {
            "status": TaskStatus.revising,
            "execution_error": None,
        })

        # Submit review decision if review_id provided
        if review_id:
            try:
                from app.tools.web_review_tool import WebReviewTool
                web_review_tool = WebReviewTool()
                web_review_tool.submit_review_decision(
                    review_id=review_id,
                    action="reject",
                    feedback=feedback,
                    target_dimensions=dimensions
                )
            except Exception as e:
                logger.warning(f"[ReviewService] [{session_id}] Failed to submit review decision: {e}")

        logger.info(f"[ReviewService] [{session_id}] Rejected, revision will be generated")

        return RejectResponse(
            session_id=session_id,
            message="rejected",
            resumed=True,
        )

    @staticmethod
    async def rollback(
        session_id: str,
        checkpoint_id: str,
        review_id: Optional[str] = None,
    ) -> RollbackResponse:
        """
        Rollback to a specific checkpoint.

        Args:
            session_id: Session identifier
            checkpoint_id: Target checkpoint ID
            review_id: Optional review ID for WebReviewTool

        Returns:
            RollbackResponse with result

        Raises:
            ValueError: If checkpoint not found
        """
        from app.agent.state import get_layer_dimensions

        # Validate session exists
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found in checkpoint")

        # Get checkpoint history using PlanningRuntimeService
        history = []
        async for state_snapshot in PlanningRuntimeService.aget_state_history(session_id):
            snapshot_checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
            history.append({
                "checkpoint_id": snapshot_checkpoint_id,
                "values": state_snapshot.values,
                "config": state_snapshot.config,
            })

        # Find target checkpoint
        target_snapshot = None
        available_checkpoints = []
        for snapshot in history:
            snapshot_checkpoint_id = snapshot.get("checkpoint_id", "")
            available_checkpoints.append(snapshot_checkpoint_id)
            if snapshot_checkpoint_id == checkpoint_id:
                target_snapshot = snapshot
                break

        if not target_snapshot:
            logger.error(f"[Rollback] Checkpoint not found! Available: {available_checkpoints}")
            raise ValueError(f"Checkpoint not found: {checkpoint_id}")

        target_values = target_snapshot.get("values", {})

        # Determine completed layer from target state
        from app.agent.state import _phase_to_layer
        target_completed_layer = _phase_to_layer(target_values.get("phase", "")) or 0
        if target_completed_layer == 0:
            completed_dims = target_values.get("completed_dimensions", {})
            if len(completed_dims.get("layer3", [])) >= len(get_layer_dimensions(3)):
                target_completed_layer = 3
            elif len(completed_dims.get("layer2", [])) >= len(get_layer_dimensions(2)):
                target_completed_layer = 2
            elif len(completed_dims.get("layer1", [])) >= len(get_layer_dimensions(1)):
                target_completed_layer = 1
        logger.info(f"[Rollback] Target completed layer: {target_completed_layer}")

        # Build rollback state
        rollback_checkpoint_id = target_snapshot.get("config", {}).get("configurable", {}).get("checkpoint_id")
        existing_reports = target_values.get("reports", {})
        existing_completed = target_values.get("completed_dimensions", {})

        if target_completed_layer == 3:
            rollback_state = {
                **target_values,
                "phase": "layer3",
                "step_mode": True,
                "revision_from_checkpoint_id": rollback_checkpoint_id,
            }
        elif target_completed_layer == 2:
            rollback_state = {
                **target_values,
                "phase": "layer2",
                "reports": {
                    "layer1": existing_reports.get("layer1", {}),
                    "layer2": existing_reports.get("layer2", {}),
                    "layer3": {},
                },
                "completed_dimensions": {
                    "layer1": existing_completed.get("layer1", []),
                    "layer2": existing_completed.get("layer2", []),
                    "layer3": [],
                },
                "step_mode": True,
                "revision_from_checkpoint_id": rollback_checkpoint_id,
            }
        elif target_completed_layer == 1:
            rollback_state = {
                **target_values,
                "phase": "layer1",
                "reports": {
                    "layer1": existing_reports.get("layer1", {}),
                    "layer2": {},
                    "layer3": {},
                },
                "completed_dimensions": {
                    "layer1": existing_completed.get("layer1", []),
                    "layer2": [],
                    "layer3": [],
                },
                "step_mode": True,
                "revision_from_checkpoint_id": rollback_checkpoint_id,
            }
        else:
            rollback_state = {
                **target_values,
                "phase": "init",
                "step_mode": True,
                "revision_from_checkpoint_id": rollback_checkpoint_id,
            }

        # Apply rollback state (no graph resumption — paused state)
        await PlanningRuntimeService.aupdate_state(session_id, rollback_state, as_node="layer_completion_check")

        # Update database status
        await update_planning_session_async(session_id, {
            "status": TaskStatus.paused,
        })

        # Submit review decision if review_id provided
        if review_id:
            try:
                from app.tools.web_review_tool import WebReviewTool
                web_review_tool = WebReviewTool()
                web_review_tool.submit_review_decision(
                    review_id=review_id,
                    action="rollback",
                    checkpoint_id=checkpoint_id
                )
            except Exception as e:
                logger.warning(f"[ReviewService] [{session_id}] Failed to submit review decision: {e}")

        logger.info(f"[ReviewService] [{session_id}] Rolled back to layer {target_completed_layer}")

        return RollbackResponse(
            session_id=session_id,
            message=f"Rolled back to Layer {target_completed_layer} completed state",
            phase=rollback_state.get("phase", "init"),
            target_layer=target_completed_layer,
            resumed=False,
        )


# Singleton instance
review_service = ReviewService()


__all__ = ["ReviewService", "review_service", "ApproveResponse", "RejectResponse", "RollbackResponse"]