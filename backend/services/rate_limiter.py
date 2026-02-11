"""
Rate Limiter - 规划请求限流管理器
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class RequestRecord:
    """单次请求记录"""
    timestamp: datetime
    session_id: str
    project_name: str


class RateLimiter:
    """限流管理器 - 单例模式"""

    _instance: RateLimiter | None = None
    _lock = threading.Lock()

    def __new__(cls) -> RateLimiter:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, '_initialized'):
            return

        self._initialized = True

        # 配置参数
        self.window_seconds = 5
        self.max_requests = 3
        self.cooldown_seconds = 10

        # 存储结构
        self._history: dict[str, list[RequestRecord]] = {}
        self._active_tasks: dict[str, datetime] = {}
        self._completed_tasks: dict[str, datetime] = {}

        logger.info("[RateLimiter] 初始化完成（内存存储模式）")

    def check_rate_limit(self, project_name: str, session_id: str) -> tuple[bool, str]:
        """
        检查是否触发限流

        Returns:
            (allowed, message)
        """
        with self._lock:
            now = datetime.now()

            if project_name in self._active_tasks:
                logger.warning(f"[RateLimiter] 项目 '{project_name}' 正在执行中")
                return False, "请求过于频繁，请稍后再试"

            if project_name in self._completed_tasks:
                completed_at = self._completed_tasks[project_name]
                cooldown_end = completed_at + timedelta(seconds=self.cooldown_seconds)
                if now < cooldown_end:
                    logger.warning(f"[RateLimiter] 项目 '{project_name}' 在冷却期内")
                    return False, "请求过于频繁，请稍后再试"

            if project_name in self._history:
                window_start = now - timedelta(seconds=self.window_seconds)
                recent_requests = [
                    r for r in self._history[project_name]
                    if r.timestamp >= window_start
                ]

                if len(recent_requests) >= self.max_requests:
                    logger.warning(
                        f"[RateLimiter] 项目 '{project_name}' "
                        f"在 {self.window_seconds} 秒内已发起 {len(recent_requests)} 次请求"
                    )
                    return False, "请求过于频繁，请稍后再试"

            self._record_request(project_name, session_id, now)
            return True, "请求通过限流检查"

    def _record_request(self, project_name: str, session_id: str, timestamp: datetime) -> None:
        """记录请求"""
        if project_name not in self._history:
            self._history[project_name] = []

        self._history[project_name].append(
            RequestRecord(
                timestamp=timestamp,
                session_id=session_id,
                project_name=project_name
            )
        )

        # 清理过期记录（保留最近1小时）
        cutoff_time = timestamp - timedelta(hours=1)
        self._history[project_name] = [
            r for r in self._history[project_name]
            if r.timestamp >= cutoff_time
        ]

        logger.info(f"[RateLimiter] 记录请求: project={project_name}, session={session_id}")

    def mark_task_started(self, project_name: str) -> None:
        """标记任务开始执行"""
        with self._lock:
            self._active_tasks[project_name] = datetime.now()
            logger.info(f"[RateLimiter] 任务开始: {project_name}")

    def mark_task_completed(self, project_name: str, success: bool = True) -> None:
        """标记任务完成"""
        with self._lock:
            now = datetime.now()

            if project_name in self._active_tasks:
                del self._active_tasks[project_name]

            if success:
                self._completed_tasks[project_name] = now
                logger.info(f"[RateLimiter] 任务完成: {project_name}, 冷却期开始")
            else:
                logger.info(f"[RateLimiter] 任务失败: {project_name}")

            # 清理过期的完成记录（保留1天）
            cutoff_time = now - timedelta(days=1)
            self._completed_tasks = {
                k: v for k, v in self._completed_tasks.items()
                if v >= cutoff_time
            }

    def get_status(self) -> dict:
        """获取限流状态（用于监控）"""
        with self._lock:
            return {
                "active_tasks": len(self._active_tasks),
                "completed_tasks": len(self._completed_tasks),
                "tracked_projects": len(self._history),
                "config": {
                    "window_seconds": self.window_seconds,
                    "max_requests": self.max_requests,
                    "cooldown_seconds": self.cooldown_seconds
                }
            }

    def reset_project(self, project_name: str) -> bool:
        """重置项目的限流状态（管理员功能）"""
        with self._lock:
            removed = (
                project_name in self._history
                or project_name in self._active_tasks
                or project_name in self._completed_tasks
            )

            self._history.pop(project_name, None)
            self._active_tasks.pop(project_name, None)
            self._completed_tasks.pop(project_name, None)

            if removed:
                logger.info(f"[RateLimiter] 已重置项目: {project_name}")

            return removed

    def get_retry_after(self, project_name: str) -> int | None:
        """
        Get seconds until next allowed request

        Returns:
            Seconds until retry is allowed, or None if no limit active
        """
        with self._lock:
            now = datetime.now()

            if project_name in self._active_tasks:
                return 60

            if project_name in self._completed_tasks:
                completed_time = self._completed_tasks[project_name]
                elapsed = (now - completed_time).total_seconds()
                remaining = self.cooldown_seconds - int(elapsed)
                if remaining > 0:
                    return remaining

            if project_name in self._history:
                recent = [
                    r for r in self._history[project_name]
                    if (now - r.timestamp).total_seconds() < self.window_seconds
                ]
                if len(recent) >= self.max_requests:
                    elapsed = (now - recent[0].timestamp).total_seconds()
                    return self.window_seconds - int(elapsed)

            return None


# 全局单例
rate_limiter = RateLimiter()

