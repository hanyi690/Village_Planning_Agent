"""
Knowledge Base Builder Service

后台知识库构建服务，合并任务管理和元数据注入功能。

来源合并：
- src/rag/core/task_manager.py (任务管理)
- src/rag/metadata/injector.py (元数据注入)
"""

import uuid
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class TaskProgress:
    """任务进度信息"""
    task_id: str
    filename: str
    status: TaskStatus
    progress: float = 0.0
    current_step: str = "等待处理"
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "filename": self.filename,
            "status": self.status.value,
            "progress": self.progress,
            "current_step": self.current_step,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class KnowledgeBaseBuilder:
    """知识库构建服务"""

    MAX_WORKERS = 4
    MAX_RETRIES = 3

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=self.MAX_WORKERS)
        self._tasks: Dict[str, TaskProgress] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._progress_callbacks: List[Callable] = []
        self._completion_callbacks: List[Callable] = []

    def submit(self, file_path: str, process_func: Callable, **kwargs) -> str:
        """提交构建任务"""
        task_id = uuid.uuid4().hex[:8]
        filename = file_path.split('/')[-1].split('\\')[-1]
        task = TaskProgress(task_id=task_id, filename=filename, status=TaskStatus.PENDING)
        with self._lock:
            self._tasks[task_id] = task

        def progress_callback(progress: float, step: str):
            self._update_progress(task_id, progress, step)

        def task_wrapper():
            return self._execute_task(task_id, file_path, process_func, progress_callback, kwargs)

        future = self._executor.submit(task_wrapper)
        with self._lock:
            self._futures[task_id] = future
        logger.info(f"[KBBuilder] Task submitted: {task_id} - {filename}")
        return task_id

    def get_task(self, task_id: str) -> Optional[TaskProgress]:
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[TaskProgress]:
        with self._lock:
            return list(self._tasks.values())

    def register_progress_callback(self, callback: Callable):
        self._progress_callbacks.append(callback)

    def register_completion_callback(self, callback: Callable):
        self._completion_callbacks.append(callback)

    def clear_completed_tasks(self, max_age_hours: int = 24):
        cutoff = datetime.now().timestamp() - max_age_hours * 3600
        with self._lock:
            to_remove = [
                tid for tid, t in self._tasks.items()
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                and t.completed_at and t.completed_at.timestamp() < cutoff
            ]
            for tid in to_remove:
                del self._tasks[tid]
                if tid in self._futures:
                    del self._futures[tid]

    def shutdown(self, wait: bool = True):
        self._executor.shutdown(wait=wait)

    def _update_progress(self, task_id: str, progress: float, step: str):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.progress = progress
                task.current_step = step
                if progress > 0 and task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.PROCESSING
                    task.started_at = datetime.now()
        for cb in self._progress_callbacks:
            try: cb(task_id, progress, step)
            except Exception: pass

    def _execute_task(self, task_id, file_path, process_func, progress_callback, kwargs):
        task = self._tasks.get(task_id)
        if not task:
            return {"status": "error", "message": "Task not found"}
        max_retries = self.MAX_RETRIES
        last_error = None
        for attempt in range(max_retries + 1):
            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    if attempt > 0:
                        task.status = TaskStatus.RETRYING
                        task.retry_count = attempt
                    else:
                        task.status = TaskStatus.PROCESSING
                        task.started_at = datetime.now()
            try:
                result = process_func(file_path, progress_callback, **kwargs)
                with self._lock:
                    task = self._tasks.get(task_id)
                    if task:
                        task.status = TaskStatus.COMPLETED
                        task.progress = 100.0
                        task.completed_at = datetime.now()
                        task.result = result
                for cb in self._completion_callbacks:
                    try: cb(task_id, result)
                    except Exception: pass
                return result
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    import time
                    time.sleep(2 * (attempt + 1))
                else:
                    with self._lock:
                        task = self._tasks.get(task_id)
                        if task:
                            task.status = TaskStatus.FAILED
                            task.error_message = last_error
                            task.completed_at = datetime.now()
                    return {"status": "error", "message": f"Failed after {max_retries} retries: {last_error}"}
        return {"status": "error", "message": f"Failed: {last_error}"}


_kb_builder: Optional[KnowledgeBaseBuilder] = None
_builder_lock = threading.Lock()


def get_kb_builder() -> KnowledgeBaseBuilder:
    """Get KB builder singleton"""
    global _kb_builder
    with _builder_lock:
        if _kb_builder is None:
            _kb_builder = KnowledgeBaseBuilder()
        return _kb_builder


__all__ = ["KnowledgeBaseBuilder", "TaskStatus", "TaskProgress", "get_kb_builder"]