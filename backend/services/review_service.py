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

from backend.schemas import TaskStatus
from backend.services.sse_manager import sse_manager
from backend.services.checkpoint_service import checkpoint_service
from backend.database.operations_async import (
    update_planning_session_async,
    get_planning_session_async,
)

logger = logging.getLogger(__name__)


class ApproveResponse:
    """Response model for approve action."""
    def __init__(
        self,
        session_id: str,
        message: str,
        resumed: bool = True,
        current_layer: Optional[int] = None,
    ):
        self.session_id = session_id
        self.message = message
        self.resumed = resumed
        self.current_layer = current_layer

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "message": self.message,
            "session_id": self.session_id,
            "resumed": self.resumed,
        }
        if self.current_layer is not None:
            result["current_layer"] = self.current_layer
        return result


class RejectResponse:
    """Response model for reject action."""
    def __init__(self, session_id: str, message: str, resumed: bool = True):
        self.session_id = session_id
        self.message = message
        self.resumed = resumed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "session_id": self.session_id,
            "resumed": self.resumed,
        }


class RollbackResponse:
    """Response model for rollback action."""
    def __init__(
        self,
        session_id: str,
        message: str,
        phase: str,
        target_layer: int,
        resumed: bool = False,
    ):
        self.session_id = session_id
        self.message = message
        self.phase = phase
        self.target_layer = target_layer
        self.resumed = resumed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "phase": self.phase,
            "target_layer": self.target_layer,
            "resumed": self.resumed,
        }


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
        from src.orchestration.main_graph import create_unified_planning_graph
        from src.orchestration.state import get_layer_dimensions
        from backend.database.engine import get_global_checkpointer

        # Get current state from checkpoint
        checkpointer = await get_global_checkpointer()
        graph = create_unified_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}

        checkpoint_state = await graph.aget_state(config)
        if not checkpoint_state or not checkpoint_state.values:
            raise ValueError(f"Session {session_id} not found in checkpoint")

        state = checkpoint_state.values
        phase = state.get("phase", "init")
        completed_dims = state.get("completed_dimensions", {})

        # Calculate next layer based on phase
        phase_order = ["init", "layer1", "layer2", "layer3", "completed"]
        try:
            phase_idx = phase_order.index(phase)
            current_layer = phase_idx
        except ValueError:
            current_layer = 1

        next_layer = current_layer
        layer_1_completed = len(completed_dims.get("layer1", [])) >= len(get_layer_dimensions(1))
        layer_2_completed = len(completed_dims.get("layer2", [])) >= len(get_layer_dimensions(2))
        layer_3_completed = len(completed_dims.get("layer3", [])) >= len(get_layer_dimensions(3))

        if phase == "layer1" and layer_1_completed:
            next_layer = 2
            next_phase = "layer2"
        elif phase == "layer2" and layer_2_completed:
            next_layer = 3
            next_phase = "layer3"
        elif phase == "layer3" and layer_3_completed:
            next_layer = 4
            next_phase = "completed"
        else:
            next_phase = phase

        logger.info(f"[ReviewService] [{session_id}] Approving: phase={phase} -> {next_phase}")

        # Update checkpoint state
        await graph.aupdate_state(config, {
            "pause_after_step": False,
            "phase": next_phase,
            "current_wave": 1,
        })

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
            ValueError: If feedback is empty or session not found
        """
        from src.orchestration.main_graph import create_unified_planning_graph
        from backend.database.engine import get_global_checkpointer

        if not feedback:
            raise ValueError("Feedback is required for rejection")

        # Get checkpointer
        checkpointer = await get_global_checkpointer()
        graph = create_unified_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}

        # Update checkpoint state
        await graph.aupdate_state(config, {
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
        from src.orchestration.main_graph import create_unified_planning_graph
        from src.orchestration.state import get_layer_dimensions
        from backend.database.engine import get_global_checkpointer

        # Get checkpointer
        checkpointer = await get_global_checkpointer()
        graph = create_unified_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}

        # Find target checkpoint
        target_state_snapshot = None
        available_checkpoints = []
        async for state_snapshot in graph.aget_state_history(config):
            snapshot_checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
            available_checkpoints.append(snapshot_checkpoint_id)
            if snapshot_checkpoint_id == checkpoint_id:
                target_state_snapshot = state_snapshot
                break

        if not target_state_snapshot:
            logger.error(f"[Rollback] Checkpoint not found! Available: {available_checkpoints}")
            raise ValueError(f"Checkpoint not found: {checkpoint_id}")

        target_values = target_state_snapshot.values

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
        rollback_checkpoint_id = target_state_snapshot.config.get("configurable", {}).get("checkpoint_id")
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

        # Apply rollback state
        await graph.aupdate_state(config, rollback_state, as_node=None)

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