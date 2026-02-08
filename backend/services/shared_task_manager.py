"""
Shared Task Manager Instance
所有API模块共享同一个task_manager实例，确保数据一致性
"""

from .planning_service import PlanningTaskManager

# Global singleton
_shared_task_manager = None


def get_shared_task_manager() -> PlanningTaskManager:
    """获取共享的task_manager实例"""
    global _shared_task_manager
    if _shared_task_manager is None:
        _shared_task_manager = PlanningTaskManager()
    return _shared_task_manager


# Convenient export
task_manager = get_shared_task_manager()
