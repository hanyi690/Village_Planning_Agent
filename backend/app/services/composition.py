"""Composition root: creates and injects all service dependencies.

Called from ``app.main`` lifespan. Modules receive Ports, not concrete
services. The root owns the lifecycle of the report store, the task
supervisor and any context provider singleton.
"""

from __future__ import annotations

from typing import Optional


class CompositionRoot:
    """Central registry for service singletons.

    Lazily initializes on first access so tests and scripts that never touch
    a given service do not pay its startup cost. ``initialize`` is called
    explicitly from ``app.main`` lifespan to fix the lifecycle at boot.
    """

    _report_store: Optional[object] = None
    _task_supervisor: Optional[object] = None
    _context_provider: Optional[object] = None

    @classmethod
    def initialize(cls):
        if cls._report_store is None:
            from app.services.report_store import ReportStore

            cls._report_store = ReportStore.get_instance()
            from app.modules.ports import registry

            registry.set_report_store_default(cls._report_store)
        if cls._task_supervisor is None:
            from app.services.task_supervisor import TaskSupervisor

            cls._task_supervisor = TaskSupervisor()

    @classmethod
    def get_report_store(cls):
        if cls._report_store is None:
            cls.initialize()
        return cls._report_store

    @classmethod
    def get_task_supervisor(cls):
        if cls._task_supervisor is None:
            cls.initialize()
        return cls._task_supervisor

    @classmethod
    def get_context_provider(cls):
        if cls._context_provider is None:
            from app.services.context.planning_context import get_cached_context

            cls._context_provider = get_cached_context
            from app.modules.ports import registry

            registry.set_context_reader_default(cls._context_provider)
        return cls._context_provider

    @classmethod
    def reset(cls):
        cls._report_store = None
        cls._task_supervisor = None
        cls._context_provider = None


__all__ = ["CompositionRoot"]