"""
Web-based Review Tool
Replaces CLI-based InteractiveTool for web environment
"""

import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime
from ..utils.logger import get_logger

logger = get_logger(__name__)


class WebReviewTool:
    """Web环境审查工具 - 非阻塞，基于事件"""

    def __init__(self):
        self.pending_reviews: Dict[str, Dict[str, Any]] = {}

    def request_review(
        self,
        content: str,
        title: str,
        session_id: str,
        current_layer: int,
        available_checkpoints: Optional[List[Dict[str, Any]]] = None,
        available_dimensions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        请求Web前端审查

        返回: {
            "success": True,
            "review_id": "uuid",
            "waiting_for_frontend": True
        }
        """
        review_id = str(uuid.uuid4())

        review_request = {
            "review_id": review_id,
            "content": content,
            "title": title,
            "session_id": session_id,
            "current_layer": current_layer,
            "available_checkpoints": available_checkpoints or [],
            "available_dimensions": available_dimensions,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }

        self.pending_reviews[review_id] = review_request
        logger.info(f"[WebReviewTool] Created review request {review_id} for session {session_id}")

        return {
            "success": True,
            "review_id": review_id,
            "waiting_for_frontend": True
        }

    def submit_review_decision(
        self,
        review_id: str,
        action: str,  # approve/reject/rollback
        feedback: Optional[str] = None,
        checkpoint_id: Optional[str] = None,
        target_dimensions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        处理前端提交的审查决定

        返回: {
            "success": True,
            "action": "approve",
            ...
        }
        """
        if review_id not in self.pending_reviews:
            logger.error(f"[WebReviewTool] Review {review_id} not found")
            return {"success": False, "error": "Review not found"}

        review = self.pending_reviews[review_id]
        review["status"] = "completed"
        review["action"] = action
        review["feedback"] = feedback
        review["checkpoint_id"] = checkpoint_id
        review["target_dimensions"] = target_dimensions
        review["completed_at"] = datetime.now().isoformat()

        logger.info(f"[WebReviewTool] Review {review_id} completed with action: {action}")

        return {
            "success": True,
            "action": action,
            "feedback": feedback,
            "checkpoint_id": checkpoint_id,
            "target_dimensions": target_dimensions
        }

    def get_review_status(self, review_id: str) -> Dict[str, Any]:
        """获取审查状态"""
        if review_id not in self.pending_reviews:
            return {"success": False, "error": "Review not found"}

        review = self.pending_reviews[review_id]
        return {
            "success": True,
            "status": review["status"],
            "action": review.get("action"),
            "review": review
        }

    def cleanup_review(self, review_id: str) -> None:
        """清理已完成的审查请求"""
        if review_id in self.pending_reviews:
            del self.pending_reviews[review_id]
            logger.info(f"[WebReviewTool] Cleaned up review {review_id}")
