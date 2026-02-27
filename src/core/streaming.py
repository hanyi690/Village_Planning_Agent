"""
SSE Streaming Support for Main Graph Execution

Provides Server-Sent Events (SSE) streaming capability for real-time updates
during main graph execution. This enables the frontend to receive progress
updates without polling.
"""

import json
import asyncio
from typing import AsyncGenerator, Dict, Any, Optional
from fastapi.responses import StreamingResponse
from langgraph.graph import StateGraph

from ..utils.logger import get_logger

logger = get_logger(__name__)

# Maximum report content size for SSE transmission (characters)
# Reports larger than this will be truncated with a notice
MAX_SSE_REPORT_SIZE = 500000  # 500KB limit for SSE transmission


def _safe_truncate_report(content: str, max_length: int = MAX_SSE_REPORT_SIZE) -> str:
    """
    Safely truncate report content if it exceeds maximum size

    Args:
        content: Report content to truncate
        max_length: Maximum length in characters

    Returns:
        Truncated content with notice if applicable, or original content
    """
    if len(content) > max_length:
        logger.warning(f"[Streaming] Report content too large ({len(content)} chars), truncating to {max_length}")
        return content[:max_length] + "\n\n[报告内容过长，已截断。完整内容请查看文件或使用API获取。]"
    return content


async def stream_graph_execution(
    graph: StateGraph,
    initial_state: Dict[str, Any],
    session_id: str,
    enable_streaming: bool = False  # 新增：是否启用 token 级流式输出
) -> StreamingResponse:
    """
    Stream main graph execution events via SSE

    Args:
        graph: The compiled StateGraph instance
        initial_state: Initial state dictionary for graph execution
        session_id: Session identifier (typically timestamp)
        enable_streaming: Enable token-level streaming output (default: False)

    Returns:
        StreamingResponse with SSE events

    Event Types:
        - layer_started: When a new layer execution begins
        - layer_completed: When a layer finishes successfully
        - checkpoint_saved: When a checkpoint is saved
        - pause: When execution pauses (step mode or review)
        - content_delta: When LLM generates new tokens (if enable_streaming=True)
        - completed: When entire planning finishes
        - error: When an error occurs
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events during graph execution"""
        try:
            import os
            logger.info(f"[Streaming] ===== Starting execution stream for session {session_id} =====")
            logger.info(f"[Streaming] Initial state keys: {list(initial_state.keys())}")
            logger.info(f"[Streaming] step_mode={initial_state.get('step_mode')}")
            logger.info(f"[Streaming] enable_streaming={enable_streaming}")
            logger.info(f"[Streaming] LLM_MODEL={os.getenv('LLM_MODEL', 'not set')}")

            # 如果启用流式输出，在状态中添加 token 缓冲区
            if enable_streaming:
                initial_state['_pending_tokens'] = []
                initial_state['_streaming_enabled'] = True

                # 创建 token 回调函数工厂
                def create_token_callback(layer: int, dimension: str):
                    """创建 token 回调函数"""
                    def on_token(token: str, accumulated: str):
                        """将 token 添加到待发送列表"""
                        pending = initial_state.get('_pending_tokens', [])
                        pending.append({
                            'delta': token,
                            'layer': layer,
                            'dimension': dimension,
                            'accumulated': accumulated
                        })
                    return on_token

                initial_state['_token_callback_factory'] = create_token_callback
                logger.info("[Streaming] Token buffering enabled")

            logger.info(f"[Streaming] Calling graph.astream()...")
            event_count = 0

            # Track previous state to detect transitions
            previous_event = {}

            # Stream graph execution
            async for event in graph.astream(initial_state, stream_mode="values"):
                event_count += 1
                logger.info(f"[Streaming] Event #{event_count}: current_layer={event.get('current_layer')}")

                # 发送待处理的 token 事件（流式输出）
                if enable_streaming and '_pending_tokens' in event:
                    pending_tokens = event['_pending_tokens']
                    while pending_tokens:
                        token_data = pending_tokens.pop(0)  # FIFO
                        yield _format_sse_event("content_delta", {
                            "delta": token_data['delta'],
                            "accumulated": token_data.get('accumulated', ''),
                            "current_layer": token_data['layer'],
                            "dimension": token_data.get('dimension', ''),
                            "session_id": session_id,
                            "timestamp": __import__('time').time()
                        })
                        logger.debug(f"[Streaming] Sent content_delta: {token_data['delta'][:20]}...")

                    # 清空已发送的 token
                    event['_pending_tokens'] = []

                # Extract relevant information from state
                current_layer = event.get("current_layer", 0)

                # Layer completion events - detect transitions from False to True
                # This fixes the issue where LangGraph accumulates state, causing multiple
                # layer_X_completed flags to be True in the same event
                layer_1_now_completed = event.get("layer_1_completed", False)
                layer_1_was_completed = previous_event.get("layer_1_completed", False)

                if layer_1_now_completed and not layer_1_was_completed:
                    # Layer 1 just completed
                    analysis_reports = event.get("analysis_reports", {})
                    
                    # 动态生成综合报告用于显示
                    from ..utils.report_utils import generate_analysis_report
                    report_content = _safe_truncate_report(
                        generate_analysis_report(analysis_reports, event.get("project_name", "村庄"))
                    )

                    logger.info(f"[Streaming] Layer 1 just completed, sending event. Report size: {len(report_content)} chars, dimensions: {len(analysis_reports)}")

                    yield _format_sse_event("layer_completed", {
                        "layer": 1,
                        "layer_number": 1,
                        "session_id": session_id,
                        "message": "现状分析完成",
                        "current_layer": 2,
                        # Include report content directly for immediate display
                        "report_content": report_content,
                        "dimension_reports": analysis_reports,
                        "timestamp": __import__('time').time()
                    })

                layer_2_now_completed = event.get("layer_2_completed", False)
                layer_2_was_completed = previous_event.get("layer_2_completed", False)

                if layer_2_now_completed and not layer_2_was_completed:
                    # Layer 2 just completed
                    concept_reports = event.get("concept_reports", {})
                    
                    # 动态生成综合报告用于显示
                    from ..utils.report_utils import generate_concept_report
                    report_content = _safe_truncate_report(
                        generate_concept_report(concept_reports, event.get("project_name", "村庄"))
                    )

                    logger.info(f"[Streaming] Layer 2 just completed, sending event. Report size: {len(report_content)} chars, dimensions: {len(concept_reports)}")

                    yield _format_sse_event("layer_completed", {
                        "layer": 2,
                        "layer_number": 2,
                        "session_id": session_id,
                        "message": "规划思路完成",
                        "current_layer": 3,
                        "report_content": report_content,
                        "dimension_reports": concept_reports,
                        "timestamp": __import__('time').time()
                    })

                layer_3_now_completed = event.get("layer_3_completed", False)
                layer_3_was_completed = previous_event.get("layer_3_completed", False)

                if layer_3_now_completed and not layer_3_was_completed:
                    # Layer 3 just completed
                    detail_reports = event.get("detail_reports", {})
                    
                    # 动态生成综合报告用于显示
                    from ..utils.report_utils import generate_detail_report
                    report_content = _safe_truncate_report(
                        generate_detail_report(detail_reports, event.get("project_name", "村庄"))
                    )

                    logger.info(f"[Streaming] Layer 3 just completed, sending event. Report size: {len(report_content)} chars, dimensions: {len(detail_reports)}")

                    yield _format_sse_event("layer_completed", {
                        "layer": 3,
                        "layer_number": 3,
                        "session_id": session_id,
                        "message": "详细规划完成",
                        "current_layer": 4,
                        "report_content": report_content,
                        "dimension_reports": detail_reports,
                        "timestamp": __import__('time').time()
                    })

                # Update previous state (only track layer completion flags)
                previous_event = {
                    "layer_1_completed": layer_1_now_completed,
                    "layer_2_completed": layer_2_now_completed,
                    "layer_3_completed": layer_3_now_completed,
                }

                # Dimension revised event (修复完成事件)
                # 使用 sent_revised_events 进行去重，防止并行分支重复上报
                last_revised_dimensions = event.get("last_revised_dimensions", [])
                if last_revised_dimensions:
                    # 初始化已发送集合（如果不存在）
                    if '_sent_revised_events' not in initial_state:
                        initial_state['_sent_revised_events'] = set()
                    
                    sent_events = initial_state['_sent_revised_events']
                    
                    for dim in last_revised_dimensions:
                        if dim not in sent_events:
                            sent_events.add(dim)
                            
                            # 获取维度信息
                            from ..config.dimension_metadata import get_dimension_config, get_dimension_layer
                            dim_config = get_dimension_config(dim)
                            dim_name = dim_config.get("name", dim) if dim_config else dim
                            dim_layer = get_dimension_layer(dim)
                            
                            # 获取修复后的内容
                            if dim_layer == 1:
                                revised_content = event.get("analysis_reports", {}).get(dim, "")
                            elif dim_layer == 2:
                                revised_content = event.get("concept_reports", {}).get(dim, "")
                            else:
                                revised_content = event.get("detail_reports", {}).get(dim, "")
                            
                            logger.info(f"[Streaming] Sending dimension_revised event: {dim} ({dim_name})")
                            
                            yield _format_sse_event("dimension_revised", {
                                "dimension_key": dim,
                                "dimension_name": dim_name,
                                "layer": dim_layer,
                                "session_id": session_id,
                                "message": f"{dim_name} 已修复",
                                "content": _safe_truncate_report(revised_content, 50000),  # 单维度限制 50KB
                                "timestamp": __import__('time').time()
                            })

                # Checkpoint saved event
                if event.get("last_checkpoint_id"):
                    yield _format_sse_event("checkpoint_saved", {
                        "checkpoint_id": event["last_checkpoint_id"],
                        "session_id": session_id,
                        "current_layer": current_layer
                    })

                # Pause event (step mode or human review)
                if event.get("pause_after_step"):
                    logger.info(f"[Streaming] Pause event at layer {current_layer}")
                    yield _format_sse_event("pause", {
                        "session_id": session_id,
                        "current_layer": current_layer,
                        "checkpoint_id": event.get("last_checkpoint_id", ""),
                        "reason": "step_mode" if event.get("step_mode") else "human_review"
                    })
                    # Don't break - let the stream complete naturally
                    # The async for loop will check for more events or complete when the graph finishes
                    # Frontend will disconnect EventSource after receiving pause event

                # Review request event (web-based review)
                if event.get("waiting_for_review"):
                    review_id = event.get("review_id", "")
                    review_content = event.get("review_content", "")
                    review_title = event.get("review_title", "")
                    current_layer_review = event.get("current_layer", 1)

                    logger.info(f"[Streaming] Sending review_request event for session {session_id}")

                    yield _format_sse_event("review_request", {
                        "review_id": review_id,
                        "title": review_title,
                        "content": review_content,
                        "current_layer": current_layer_review,
                        "session_id": session_id,
                        "message": f"请审查 {review_title}"
                    })

                    # Pause execution stream, waiting for frontend response
                    # Frontend will call /api/planning/review/{session_id} to continue
                    break

                # Progress updates from messages
                if event.get("messages"):
                    latest_message = event["messages"][-1]
                    if hasattr(latest_message, 'content'):
                        yield _format_sse_event("progress", {
                            "session_id": session_id,
                            "message": latest_message.content[:200],  # Truncate long messages
                            "current_layer": current_layer
                        })

            # Check if execution completed normally
            if not initial_state.get("pause_after_step"):
                logger.info(f"[Streaming] Execution completed normally")
                yield _format_sse_event("completed", {
                    "session_id": session_id,
                    "message": "规划完成",
                    "success": True
                })

            logger.info(f"[Streaming] ===== Stream completed. Total events: {event_count} =====")

        except Exception as e:
            logger.error(f"[Streaming] ===== EXCEPTION =====", exc_info=True)
            logger.error(f"[Streaming] Error type: {type(e).__name__}")
            logger.error(f"[Streaming] Error: {str(e)}")
            # 改进：提供更详细的错误信息
            import traceback
            error_details = {
                "session_id": session_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()[:1000],  # 限制长度
                "success": False
            }
            yield _format_sse_event("error", error_details)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


def _format_sse_event(event_type: str, data: Dict[str, Any]) -> str:
    """
    Format data as Server-Sent Event

    Args:
        event_type: Type of event (layer_completed, pause, error, etc.)
        data: Event data dictionary

    Returns:
        Formatted SSE string
    """
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_checkpoint_resume(
    graph: StateGraph,
    state: Dict[str, Any],
    session_id: str,
    enable_streaming: bool = False  # 新增
) -> StreamingResponse:
    """
    Stream execution when resuming from checkpoint

    Args:
        graph: The compiled StateGraph instance
        state: Restored state from checkpoint
        session_id: Session identifier
        enable_streaming: Enable token-level streaming (default: False)

    Returns:
        StreamingResponse with SSE events
    """
    logger.info(f"[Streaming] Resuming execution from checkpoint for session {session_id}")

    # Reset pause flag to continue execution
    state["pause_after_step"] = False

    return await stream_graph_execution(graph, state, session_id, enable_streaming)


class StreamingOrchestrator:
    """
    High-level orchestrator for streaming execution

    Manages the lifecycle of streaming executions including:
    - Starting new planning sessions
    - Resuming from checkpoints
    - Handling step mode pauses
    """

    def __init__(self, graph: StateGraph):
        """
        Initialize orchestrator with a compiled graph

        Args:
            graph: Compiled StateGraph instance
        """
        self.graph = graph
        self.active_streams: Dict[str, bool] = {}

    async def start_planning(
        self,
        initial_state: Dict[str, Any],
        session_id: str,
        enable_streaming: bool = False  # 新增
    ) -> StreamingResponse:
        """
        Start a new planning session with streaming

        Args:
            initial_state: Initial state for graph execution
            session_id: Unique session identifier
            enable_streaming: Enable token-level streaming (default: False)

        Returns:
            StreamingResponse with SSE events
        """
        logger.info(f"[Orchestrator] Starting planning session {session_id}")
        self.active_streams[session_id] = True

        return await stream_graph_execution(self.graph, initial_state, session_id, enable_streaming)

    async def resume_from_checkpoint(
        self,
        checkpoint_id: str,
        project_name: str,
        session_id: str,
        enable_streaming: bool = False  # 新增
    ) -> StreamingResponse:
        """
        Resume execution from a checkpoint with streaming

        Args:
            checkpoint_id: Checkpoint identifier
            project_name: Project/village name
            session_id: Session identifier
            enable_streaming: Enable token-level streaming (default: False)

        Returns:
            StreamingResponse with SSE events
        """
        logger.info(f"[Orchestrator] Resuming session {session_id} from checkpoint {checkpoint_id}")

        # 使用 LangGraph API 从 checkpoint 恢复
        # 构建 config（使用 session_id 作为 thread_id）
        config = {
            "configurable": {
                "thread_id": session_id,
                "checkpoint_id": checkpoint_id
            }
        }

        # 继续执行（LangGraph 会自动从 checkpoint 恢复状态）
        # 注意：这里需要传入 None 作为初始状态，LangGraph 会从 checkpoint 加载
        return await stream_graph_execution(
            self.graph, 
            None,  # 由 LangGraph 从 checkpoint 加载
            session_id, 
            enable_streaming,
            config=config
        )

    def is_stream_active(self, session_id: str) -> bool:
        """Check if a stream is currently active for a session"""
        return self.active_streams.get(session_id, False)

    def mark_stream_complete(self, session_id: str):
        """Mark a stream as complete"""
        self.active_streams.pop(session_id, None)


__all__ = [
    "stream_graph_execution",
    "stream_checkpoint_resume",
    "StreamingOrchestrator",
]
