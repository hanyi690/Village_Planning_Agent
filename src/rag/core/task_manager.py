"""
RAG Document Task Manager - 文档处理任务管理器

支持：
- 线程池并行处理（最大 4 个文档）
- 任务状态追踪（pending/processing/completed/failed/retrying）
- 进度回调机制
- 失败自动重试（最多 3 次）

设计说明：
- MarkItDown 是同步库，无法 asyncio 化
- ChromaDB API 是同步调用
- 使用 ThreadPoolExecutor 实现并行
- SSEManager 已有跨线程发布机制可复用
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
    PENDING = "pending"          # 等待处理
    PROCESSING = "processing"    # 正在处理
    COMPLETED = "completed"      # 完成
    FAILED = "failed"            # 失败（重试后）
    RETRYING = "retrying"        # 重试中


@dataclass
class TaskProgress:
    """任务进度信息"""
    task_id: str
    filename: str
    status: TaskStatus
    progress: float = 0.0                    # 0.0 - 100.0
    current_step: str = "等待处理"
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None  # 处理结果

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 API 返回）"""
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


class DocumentTaskManager:
    """
    文档处理任务管理器

    使用线程池并行处理文档，支持进度追踪和失败重试。
    """

    MAX_WORKERS = 4      # 最大并行文档数
    MAX_RETRIES = 3      # 最大重试次数

    def __init__(self):
        """初始化任务管理器"""
        self._executor = ThreadPoolExecutor(max_workers=self.MAX_WORKERS)
        self._tasks: Dict[str, TaskProgress] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._progress_callbacks: List[Callable[[str, float, str], None]] = []
        self._completion_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []

    def submit(
        self,
        file_path: str,
        process_func: Callable[[str, Callable[[float, str], None]], Dict[str, Any]],
        **kwargs
    ) -> str:
        """
        提交文档处理任务

        Args:
            file_path: 文件路径
            process_func: 处理函数，接受 (file_path, progress_callback) 参数
            **kwargs: 传递给处理函数的额外参数

        Returns:
            task_id: 任务 ID
        """
        task_id = self._generate_task_id()
        filename = file_path.split('/')[-1].split('\\')[-1]

        # 创建任务记录
        task = TaskProgress(
            task_id=task_id,
            filename=filename,
            status=TaskStatus.PENDING,
            current_step="等待处理",
        )

        with self._lock:
            self._tasks[task_id] = task

        # 创建进度回调（内部）
        def progress_callback(progress: float, step: str):
            self._update_progress(task_id, progress, step)

        # 提交任务到线程池
        def task_wrapper():
            return self._execute_task(task_id, file_path, process_func, progress_callback, kwargs)

        future = self._executor.submit(task_wrapper)
        with self._lock:
            self._futures[task_id] = future

        logger.info(f"[TaskManager] 任务已提交: {task_id} - {filename}")
        return task_id

    def get_task(self, task_id: str) -> Optional[TaskProgress]:
        """获取单个任务状态"""
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[TaskProgress]:
        """获取所有任务列表"""
        with self._lock:
            return list(self._tasks.values())

    def get_active_tasks_count(self) -> int:
        """获取正在处理的任务数量"""
        with self._lock:
            return sum(1 for t in self._tasks.values()
                      if t.status in (TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.RETRYING))

    def register_progress_callback(self, callback: Callable[[str, float, str], None]):
        """注册进度回调函数"""
        self._progress_callbacks.append(callback)

    def register_completion_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """注册完成回调函数"""
        self._completion_callbacks.append(callback)

    def clear_completed_tasks(self, max_age_hours: int = 24):
        """清理已完成的旧任务"""
        cutoff = datetime.now().timestamp() - max_age_hours * 3600
        with self._lock:
            to_remove = [
                task_id for task_id, task in self._tasks.items()
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                and task.completed_at and task.completed_at.timestamp() < cutoff
            ]
            for task_id in to_remove:
                del self._tasks[task_id]
                if task_id in self._futures:
                    del self._futures[task_id]

        if to_remove:
            logger.info(f"[TaskManager] 已清理 {len(to_remove)} 个旧任务")

    def shutdown(self, wait: bool = True):
        """关闭线程池"""
        self._executor.shutdown(wait=wait)
        logger.info("[TaskManager] 线程池已关闭")

    # ============================================
    # 内部方法
    # ============================================

    def _generate_task_id(self) -> str:
        """生成任务 ID"""
        return uuid.uuid4().hex[:8]

    def _update_progress(self, task_id: str, progress: float, step: str):
        """更新任务进度"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.progress = progress
                task.current_step = step
                if progress > 0 and task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.PROCESSING
                    task.started_at = datetime.now()

        # 触发进度回调
        for callback in self._progress_callbacks:
            try:
                callback(task_id, progress, step)
            except Exception as e:
                logger.warning(f"[TaskManager] 进度回调失败: {e}")

    def _execute_task(
        self,
        task_id: str,
        file_path: str,
        process_func: Callable,
        progress_callback: Callable[[float, str], None],
        kwargs: Dict
    ) -> Dict[str, Any]:
        """执行任务（含重试逻辑）"""
        task = self._tasks.get(task_id)
        if not task:
            return {"status": "error", "message": "任务不存在"}

        max_retries = self.MAX_RETRIES
        last_error = None

        for attempt in range(max_retries + 1):
            # 更新状态
            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    if attempt > 0:
                        task.status = TaskStatus.RETRYING
                        task.retry_count = attempt
                        task.current_step = f"重试 ({attempt}/{max_retries})"
                    else:
                        task.status = TaskStatus.PROCESSING
                        task.started_at = datetime.now()
                    task.error_message = None

            try:
                logger.info(f"[TaskManager] 开始处理: {task_id} (尝试 {attempt + 1})")

                # 执行处理函数
                result = process_func(file_path, progress_callback, **kwargs)

                # 成功
                with self._lock:
                    task = self._tasks.get(task_id)
                    if task:
                        task.status = TaskStatus.COMPLETED
                        task.progress = 100.0
                        task.current_step = "完成"
                        task.completed_at = datetime.now()
                        task.result = result

                logger.info(f"[TaskManager] 任务完成: {task_id}")

                # 触发完成回调
                for callback in self._completion_callbacks:
                    try:
                        callback(task_id, result)
                    except Exception as e:
                        logger.warning(f"[TaskManager] 完成回调失败: {e}")

                return result

            except Exception as e:
                last_error = str(e)
                logger.error(f"[TaskManager] 任务失败: {task_id} - {e} (尝试 {attempt + 1})")

                if attempt < max_retries:
                    # 等待后重试
                    import time
                    time.sleep(2 * (attempt + 1))  # 递增等待时间
                else:
                    # 最终失败
                    with self._lock:
                        task = self._tasks.get(task_id)
                        if task:
                            task.status = TaskStatus.FAILED
                            task.error_message = last_error
                            task.completed_at = datetime.now()
                            task.current_step = "失败"

                    return {
                        "status": "error",
                        "message": f"处理失败（重试 {max_retries} 次后）: {last_error}"
                    }

        return {"status": "error", "message": f"处理失败: {last_error}"}


# 全局实例
_task_manager: Optional[DocumentTaskManager] = None
_manager_lock = threading.Lock()


def get_task_manager() -> DocumentTaskManager:
    """获取任务管理器单例"""
    global _task_manager
    with _manager_lock:
        if _task_manager is None:
            _task_manager = DocumentTaskManager()
        return _task_manager