"""
Runtime Object Context Manager

使用contextvars实现线程安全的运行时组件传递，
避免Node内部的隐式全局依赖。
"""
import contextvars
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from backend.services.sse_event_stream import StreamingQueueManager
    from backend.services.storage_pipeline import AsyncStoragePipeline

# 定义上下文变量
_streaming_ctx: contextvars.ContextVar[Optional["StreamingQueueManager"]] = contextvars.ContextVar(
    "_streaming_ctx", default=None
)

_storage_ctx: contextvars.ContextVar[Optional["AsyncStoragePipeline"]] = contextvars.ContextVar(
    "_storage_ctx", default=None
)

_dimension_events_ctx: contextvars.ContextVar[list] = contextvars.ContextVar(
    "_dimension_events_ctx", default=[]
)


class StreamingContext:
    """
    Runtime object context manager

    在Node执行前设置上下文，Node内部可以通过上下文变量访问。
    这种方式避免了全局依赖，使依赖关系更明确。
    """

    @staticmethod
    def set_context(
        streaming_queue: Optional["StreamingQueueManager"] = None,
        storage_pipeline: Optional["AsyncStoragePipeline"] = None,
        dimension_events: list = []
    ) -> "StreamingContext":
        """创建上下文管理器"""
        return StreamingContext(
            _streaming_queue=streaming_queue,
            _storage_pipeline=storage_pipeline,
            _dimension_events=dimension_events
        )

    def __init__(
        self,
        _streaming_queue: Optional["StreamingQueueManager"] = None,
        _storage_pipeline: Optional["AsyncStoragePipeline"] = None,
        _dimension_events: list = []
    ):
        self._streaming_queue = _streaming_queue
        self._storage_pipeline = _storage_pipeline
        self._dimension_events = _dimension_events
        self._token = None

    def __enter__(self) -> "StreamingContext":
        """设置上下文变量"""
        self._token = (_streaming_ctx.set(self._streaming_queue),
                       _storage_ctx.set(self._storage_pipeline),
                       _dimension_events_ctx.set(self._dimension_events))
        return self

    def __exit__(self, *args):
        """清除上下文变量"""
        if self._token:
            for token in self._token:
                if token is not None:
                    token.var.reset(token)

    @staticmethod
    def get_streaming_queue() -> Optional["StreamingQueueManager"]:
        """获取当前上下文的流式队列"""
        return _streaming_ctx.get()

    @staticmethod
    def get_storage_pipeline() -> Optional["AsyncStoragePipeline"]:
        """获取当前上下文的存储管道"""
        return _storage_ctx.get()

    @staticmethod
    def get_dimension_events() -> list:
        """获取当前上下文的维度事件"""
        return _dimension_events_ctx.get()


# 便捷函数
def get_streaming_queue() -> Optional["StreamingQueueManager"]:
    """获取当前流式队列"""
    return StreamingContext.get_streaming_queue()

def get_storage_pipeline() -> Optional["AsyncStoragePipeline"]:
    """获取当前存储管道"""
    return StreamingContext.get_storage_pipeline()

def get_dimension_events() -> list:
    """获取当前维度事件"""
    return StreamingContext.get_dimension_events()
