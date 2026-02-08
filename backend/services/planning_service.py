"""
Planning Service - Task Management and Execution
规划服务 - 任务管理和执行

This module provides the PlanningTaskManager class for managing planning tasks.
Note: This is legacy code maintained for backward compatibility.
New code should use the session-based architecture in backend/api/planning.py.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.schemas import PlanningRequest, TaskStatus
from backend.utils.progress_helper import calculate_progress

logger = logging.getLogger(__name__)


class PlanningTaskManager:
    """
    Task Manager for planning operations

    Manages the lifecycle of planning tasks including creation, execution,
    review, and checkpoint management.
    """

    def __init__(self) -> None:
        """Initialize task manager"""
        self.tasks: Dict[str, Dict[str, Any]] = {}
        logger.info("[TaskManager] Initialized")

    def create_task(self, task_id: str, request: PlanningRequest) -> None:
        """
        Create a new task

        Args:
            task_id: Unique identifier for the task
            request: Planning request data
        """
        self.tasks[task_id] = {
            "task_id": task_id,
            "status": TaskStatus.pending,
            "request": request.dict(),
            "result": None,
            "error": None,
            "progress": 0,
            "current_layer": None,
            "message": "Task created",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        logger.info(f"[TaskManager] Task created: {task_id}")

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task information

        Args:
            task_id: Task identifier

        Returns:
            Task data dict or None if not found
        """
        return self.tasks.get(task_id)

    def list_tasks(self) -> Dict[str, Dict[str, Any]]:
        """
        List all tasks

        Returns:
            Copy of all tasks dict
        """
        return self.tasks.copy()

    def delete_task(self, task_id: str) -> None:
        """
        Delete a task

        Args:
            task_id: Task identifier
        """
        if task_id in self.tasks:
            del self.tasks[task_id]
            logger.info(f"[TaskManager] Task deleted: {task_id}")

    async def run_planning_task(self, task_id: str, request: PlanningRequest) -> None:
        """
        Execute planning task

        Args:
            task_id: Task identifier
            request: Planning request data
        """
        try:
            self._update_task_status(task_id, TaskStatus.running, message="开始执行规划任务")
            self._update_task_progress(task_id, 10, current_layer="layer_1")

            from src.agent import run_village_planning

            logger.info(f"[TaskManager] Running planning task: {task_id}")

            result = await asyncio.to_thread(
                run_village_planning,
                project_name=request.project_name,
                village_data=request.village_data,
                task_description=request.task_description,
                constraints=request.constraints,
                need_human_review=request.need_human_review,
                stream_mode=request.stream_mode,
                step_mode=request.step_mode,
                step_level="layer"
            )

            if result.get("status") == "paused":
                self._handle_paused_state(task_id, result)
                return

            self._handle_completed_state(task_id, result)

        except Exception as e:
            import traceback
            error_msg = str(e)
            logger.error(f"[TaskManager] Task failed: {task_id}, Error: {error_msg}")
            logger.error(f"[TaskManager] Traceback: {traceback.format_exc()}")

            self._update_task_status(
                task_id,
                TaskStatus.failed,
                message=f"任务执行失败: {error_msg}",
                error=error_msg
            )

            # Clean up registry resources even on failure
            self._cleanup_session(task_id)

    def _update_task_with_result(self, task_id: str, result: Dict[str, Any]) -> None:
        """
        Update task with planning result data

        Centralizes the logic for updating task state from planning results.

        Args:
            task_id: Task identifier
            result: Result dict from planning execution
        """
        update_data = {
            "analysis_report": result.get("analysis_report", ""),
            "planning_concept": result.get("planning_concept", ""),
            "detailed_plan": result.get("detailed_plan", ""),
            "layer_1_completed": result.get("layer_1_completed", False),
            "layer_2_completed": result.get("layer_2_completed", False),
            "layer_3_completed": result.get("layer_3_completed", False),
        }

        if result.get("status") == "paused":
            current_layer = result.get("current_layer", 1)
            update_data.update({
                "current_layer": current_layer,
                "checkpoint_id": result.get("checkpoint_id", ""),
                "state": result.get("state"),
                "progress": calculate_progress(current_layer)
            })
        else:
            update_data.update({
                "result": result,
                "final_output": result.get("final_output", ""),
                "final_output_path": result.get("final_output_path"),
                "all_layers_completed": result.get("all_layers_completed", False),
                "dimension_reports": result.get("dimension_reports", {}),
                "checkpoints": [],
                "progress": 100
            })

        self.tasks[task_id].update(update_data)

    def _handle_paused_state(self, task_id: str, result: Dict[str, Any]) -> None:
        """
        Handle task pause (for review)

        Updates task state and sets status to paused.

        Args:
            task_id: Task identifier
            result: Result dict from planning execution
        """
        current_layer = result.get("current_layer", 1)
        logger.info(f"[TaskManager] Task paused at layer {current_layer}: {task_id}")

        self._update_task_with_result(task_id, result)
        self._update_task_status(
            task_id,
            TaskStatus.paused,
            message=f"Layer {current_layer} 已完成，等待审查"
        )
        self._update_task_progress(
            task_id,
            calculate_progress(current_layer),
            current_layer=f"layer_{current_layer}"
        )

    def _handle_completed_state(self, task_id: str, result: Dict[str, Any]) -> None:
        """
        Handle task completion

        Updates task with final results and sets status to completed.

        Args:
            task_id: Task identifier
            result: Result dict from planning execution
        """
        self._update_task_with_result(task_id, result)
        self._update_task_status(task_id, TaskStatus.completed, message="规划任务完成")
        logger.info(f"[TaskManager] Task completed: {task_id}")

        # Clean up registry resources
        self._cleanup_session(task_id)

    def _cleanup_session(self, session_id: str) -> None:
        """
        Clean up resources for a completed session

        Args:
            session_id: Session identifier to clean up
        """
        try:
            from src.utils.output_manager_registry import get_output_manager_registry
            registry = get_output_manager_registry()
            registry.remove(session_id)
            logger.info(f"[Cleanup] Removed session: {session_id}")
        except Exception as e:
            logger.warning(f"[Cleanup] Failed to remove session {session_id}: {e}")

    def _update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        message: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Update task status

        Args:
            task_id: Task identifier
            status: New task status
            message: Optional status message
            error: Optional error message
        """
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
            self.tasks[task_id]["updated_at"] = datetime.now()
            if message:
                self.tasks[task_id]["message"] = message
            if error:
                self.tasks[task_id]["error"] = error

    def _update_task_progress(
        self,
        task_id: str,
        progress: float,
        current_layer: Optional[str] = None
    ) -> None:
        """
        Update task progress

        Args:
            task_id: Task identifier
            progress: Progress value (0-100)
            current_layer: Optional current layer identifier
        """
        if task_id in self.tasks:
            self.tasks[task_id]["progress"] = progress
            self.tasks[task_id]["updated_at"] = datetime.now()
            if current_layer:
                self.tasks[task_id]["current_layer"] = current_layer

    def _load_checkpoints_from_dir(self, checkpoint_dir: Path) -> List[Dict[str, Any]]:
        """
        Load checkpoints from a directory

        Args:
            checkpoint_dir: Path to checkpoints directory

        Returns:
            List of checkpoint info dicts
        """
        checkpoints = []
        for checkpoint_file in sorted(checkpoint_dir.glob("*.json")):
            try:
                with open(checkpoint_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                checkpoints.append({
                    "checkpoint_id": data.get("checkpoint_id"),
                    "description": data.get("metadata", {}).get("description", ""),
                    "timestamp": data.get("timestamp", ""),
                    "layer": data.get("metadata", {}).get("layer", 0)
                })
            except Exception as e:
                logger.warning(f"[TaskManager] Failed to load checkpoint {checkpoint_file}: {e}")
        return checkpoints

    # Review and revision methods
    def get_task_checkpoints(self, task_id: str) -> List[Dict[str, Any]]:
        """
        Get checkpoint list for a task

        Args:
            task_id: Task identifier

        Returns:
            List of checkpoint info dicts
        """
        task = self.get_task(task_id)
        if not task:
            logger.warning(f"[TaskManager] Task not found: {task_id}")
            return []

        try:
            project_name = task.get("request", {}).get("project_name", "")
            output_manager = task.get("output_manager")

            if output_manager:
                checkpoint_dir = Path(output_manager.output_path) / "checkpoints"
                if checkpoint_dir.exists():
                    return self._load_checkpoints_from_dir(checkpoint_dir)

            # Fallback: try to find in results directory
            results_dir = Path("results")
            if results_dir.exists():
                for project_dir in results_dir.iterdir():
                    if project_name in project_dir.name:
                        checkpoint_dir = project_dir / "checkpoints"
                        if checkpoint_dir.exists():
                            return self._load_checkpoints_from_dir(checkpoint_dir)

            return []

        except Exception as e:
            logger.error(f"[TaskManager] Failed to get checkpoints: {e}")
            return []

    async def approve_review(self, task_id: str) -> Dict[str, Any]:
        """
        Approve review and continue execution

        Args:
            task_id: Task identifier

        Returns:
            Response dict with success status and message
        """
        task = self.get_task(task_id)
        if not task:
            return {"success": False, "message": "Task not found"}

        try:
            if task.get("status") != TaskStatus.paused:
                return {"success": False, "message": "Task status does not allow approval"}

            self._update_task_status(task_id, TaskStatus.running, message="Review approved, continuing execution")

            checkpoint_id = task.get("checkpoint_id")
            state = task.get("state")
            output_manager = task.get("output_manager")

            if not state:
                return {"success": False, "message": "Task state not found"}

            asyncio.create_task(self._continue_execution(task_id, state, checkpoint_id, output_manager))

            return {"success": True, "message": "Review approved, continuing execution"}

        except Exception as e:
            logger.error(f"[TaskManager] Approve review failed: {e}")
            return {"success": False, "message": f"Approval failed: {str(e)}"}

    async def _continue_execution(
        self,
        task_id: str,
        state: Dict[str, Any],
        checkpoint_id: str,
        output_manager: Any
    ) -> None:
        """
        Continue task execution from checkpoint

        Args:
            task_id: Task identifier
            state: Current task state
            checkpoint_id: Checkpoint to resume from
            output_manager: Output manager instance
        """
        try:
            from src.agent import run_village_planning

            logger.info(f"[TaskManager] Continuing task {task_id} from checkpoint {checkpoint_id}")

            result = await asyncio.to_thread(
                run_village_planning,
                project_name=state.get("project_name"),
                village_data=state.get("village_data"),
                task_description=state.get("task_description"),
                constraints=state.get("constraints"),
                need_human_review=state.get("need_human_review", False),
                stream_mode=state.get("stream_mode", False),
                step_mode=state.get("step_mode", False),
                step_level="layer",
                resume_from_checkpoint=checkpoint_id,
                output_manager=output_manager
            )

            if result.get("status") == "paused":
                self._handle_paused_state(task_id, result)
                return

            self._handle_completed_state(task_id, result)

        except Exception as e:
            import traceback
            error_msg = str(e)
            logger.error(f"[TaskManager] Continue execution failed: {error_msg}")
            logger.error(f"[TaskManager] Traceback: {traceback.format_exc()}")

            self._update_task_status(
                task_id,
                TaskStatus.failed,
                message=f"继续执行失败: {error_msg}",
                error=error_msg
            )

    async def reject_review(
        self,
        task_id: str,
        feedback: str,
        target_dimensions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Reject review and trigger revision

        Args:
            task_id: Task identifier
            feedback: User feedback for revision
            target_dimensions: Optional list of dimensions to revise

        Returns:
            Response dict with success status and message
        """
        task = self.get_task(task_id)
        if not task:
            return {"success": False, "message": "Task not found"}

        try:
            if task.get("status") not in [TaskStatus.paused, TaskStatus.reviewing]:
                return {"success": False, "message": "Task status does not allow rejection"}

            self.tasks[task_id]["human_feedback"] = feedback
            self.tasks[task_id]["target_dimensions"] = target_dimensions or []
            self._update_task_status(task_id, TaskStatus.revising, message="Starting revision")

            return {"success": True, "message": "Revision started"}

        except Exception as e:
            logger.error(f"[TaskManager] Reject review failed: {e}")
            return {"success": False, "message": f"Rejection failed: {str(e)}"}

    async def rollback_to_checkpoint(
        self,
        task_id: str,
        checkpoint_id: str
    ) -> Dict[str, Any]:
        """
        Rollback task to a specific checkpoint

        Args:
            task_id: Task identifier
            checkpoint_id: Checkpoint ID to rollback to

        Returns:
            Response dict with success status and layer info
        """
        task = self.get_task(task_id)
        if not task:
            return {"success": False, "message": "Task not found"}

        try:
            project_name = task.get("request", {}).get("project_name", "")
            output_manager = task.get("output_manager")

            if output_manager:
                checkpoint_dir = Path(output_manager.output_path) / "checkpoints"
                checkpoint_file = checkpoint_dir / f"{checkpoint_id}.json"

                if checkpoint_file.exists():
                    with open(checkpoint_file, 'r', encoding='utf-8') as f:
                        checkpoint_data = json.load(f)

                    checkpoint_state = checkpoint_data.get("state", {})
                    metadata = checkpoint_data.get("metadata", {})

                    self.tasks[task_id].update({
                        "analysis_report": checkpoint_state.get("analysis_report", ""),
                        "planning_concept": checkpoint_state.get("planning_concept", ""),
                        "detailed_plan": checkpoint_state.get("detailed_plan", ""),
                        "current_layer": checkpoint_state.get("current_layer", 1),
                        "layer_1_completed": checkpoint_state.get("layer_1_completed", False),
                        "layer_2_completed": checkpoint_state.get("layer_2_completed", False),
                        "layer_3_completed": checkpoint_state.get("layer_3_completed", False),
                    })

                    layer = metadata.get("layer", 0)
                    self._update_task_status(
                        task_id,
                        TaskStatus.paused,
                        message=f"Rolled back to Layer {layer}"
                    )

                    return {
                        "success": True,
                        "message": f"Rolled back to Layer {layer}",
                        "layer": layer
                    }

            return {"success": False, "message": "Checkpoint not found"}

        except Exception as e:
            logger.error(f"[TaskManager] Rollback failed: {e}")
            return {"success": False, "message": f"Rollback failed: {str(e)}"}

    async def resume_task(self, task_id: str) -> Dict[str, Any]:
        """
        Resume a paused task

        Args:
            task_id: Task identifier

        Returns:
            Response dict with success status and message
        """
        task = self.get_task(task_id)
        if not task:
            return {"success": False, "message": "Task not found"}

        try:
            if task.get("status") != TaskStatus.paused:
                return {"success": False, "message": "Task status does not allow resume"}

            return await self.approve_review(task_id)

        except Exception as e:
            logger.error(f"[TaskManager] Resume failed: {e}")
            return {"success": False, "message": f"Resume failed: {str(e)}"}
