"""
Backend schemas - Pydantic models shared across API and services.
"""

from enum import Enum
from pydantic import BaseModel
from typing import Optional, List


class TaskStatus(str, Enum):
    """Task execution status."""
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ImageData(BaseModel):
    """Image data for multimodal input."""
    id: str
    image_base64: str
    tags: List[str] = []


__all__ = ["TaskStatus", "ImageData"]