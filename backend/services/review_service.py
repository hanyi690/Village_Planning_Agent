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
from backend.schemas import TaskStatus
from backend.services.sse_manager import sse_manager
from backend.services.checkpoint_service import checkpoint_service
from backend.database.operations_async import (
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
        """
        Approve the current planning step and resume execution.

        Args:
            session_id: Session identifier
            review_id: Optional review ID for WebReviewTool

        Returns:
            ApproveResponse with result

        Raises:
            ValueError: If session not found
        """
        from src.orchestration.state import get_layer_dimensions, get_layer_name

        # Use CheckpointService for state validation
        state = await checkpoint_service.validate_session(session_id)

        # Calculate next layer using CheckpointService
        next_layer, next_phase = await checkpoint_service.calculate_next_layer(session_id, state)

        logger.info(f"[ReviewService] [{session_id}] Approving: phase={state.get('phase', 'init')} -> {next_phase}")

        # Update checkpoint state - clear pause flags and set next phase
        # ⚠️ 推进 phase 到下一阶段（Agent 自治：恢复执行后自动发送 layer_started）
        await checkpoint_service.update_state(session_id, {
            "pause_after_step": False,
            "previous_layer": 0,
            "phase": next_phase,
            "current_wave": 1,
        })

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
                from src.tools.web_review_tool import WebReviewTool
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
    ) -> RejectResponse:
        """
        Reject the current planning step with feedback.

        Args:
            session_id: Session identifier
            feedback: Feedback message for revision
            dimensions: Optional list of dimensions to revise
            review_id: Optional review ID for WebReviewTool

        Returns:
            RejectResponse with result

        Raises:
            ValueError: If feedback is empty
        """
        if not feedback:
            raise ValueError("Feedback is required for rejection")

        # Validate session exists
        await checkpoint_service.validate_session(session_id)

        # Update checkpoint state using CheckpointService
        await checkpoint_service.update_state(session_id, {
            "need_revision": True,
            "revision_target_dimensions": dimensions or [],
            "human_feedback": feedback,
            "pause_after_step": False,
        })

        logger.info(f"[ReviewService] [{session_id}] Rejected with feedback, dimensions={dimensions}")

        # Update database status
        await update_planning_session_async(session_id, {
            "status": TaskStatus.revising,
            "execution_error": None,
        })

        # Submit review decision if review_id provided
        if review_id:
            try:
                from src.tools.web_review_tool import WebReviewTool
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
        from src.orchestration.state import get_layer_dimensions

        # Validate session exists
        await checkpoint_service.validate_session(session_id)

        # Get checkpoint history using CheckpointService
        history = await checkpoint_service.get_checkpoint_history(session_id)

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
        def determine_completed_layer(values: dict) -> int:
            phase = values.get("phase", "")
            if phase:
                phase_layer_map = {
                    "layer1": 1,
                    "layer2": 2,
                    "layer3": 3,
                    "completed": 3,
                }
                layer = phase_layer_map.get(phase, 0)
                if layer > 0:
                    return layer

            completed_dims = values.get("completed_dimensions", {})
            if len(completed_dims.get("layer3", [])) >= len(get_layer_dimensions(3)):
                return 3
            if len(completed_dims.get("layer2", [])) >= len(get_layer_dimensions(2)):
                return 2
            if len(completed_dims.get("layer1", [])) >= len(get_layer_dimensions(1)):
                return 1
            return 0

        target_completed_layer = determine_completed_layer(target_values)
        logger.info(f"[Rollback] Target completed layer: {target_completed_layer}")

        # Build rollback state
        rollback_checkpoint_id = target_snapshot.get("config", {}).get("configurable", {}).get("checkpoint_id")
        existing_reports = target_values.get("reports", {})
        existing_completed = target_values.get("completed_dimensions", {})

        if target_completed_layer == 3:
            rollback_state = {
                **target_values,
                "phase": "layer3",
                "pause_after_step": True,
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
                "pause_after_step": True,
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
                "pause_after_step": True,
                "revision_from_checkpoint_id": rollback_checkpoint_id,
            }
        else:
            rollback_state = {
                **target_values,
                "phase": "init",
                "pause_after_step": True,
                "revision_from_checkpoint_id": rollback_checkpoint_id,
            }

        # Apply rollback state using CheckpointService with as_node=None
        await checkpoint_service.update_state(session_id, rollback_state, as_node=None)

        # Update database status
        await update_planning_session_async(session_id, {
            "status": TaskStatus.paused,
        })

        # Submit review decision if review_id provided
        if review_id:
            try:
                from src.tools.web_review_tool import WebReviewTool
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