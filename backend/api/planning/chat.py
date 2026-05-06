"""
Planning API Chat - 对话端点

处理用户对话消息，支持多模态（文本+图片）。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage

from backend.services import PlanningRuntimeService
from backend.schemas import ChatMessageRequest, ImageData
from backend.database.operations_async import get_planning_session_async
from src.core.message_builder import build_multimodal_message
from src.core.config import MULTIMODAL_ENABLED

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/planning/chat/{session_id}")
async def send_chat_message(session_id: str, request: ChatMessageRequest):
    """
    发送对话消息（支持多模态）

    通过 LangGraph stream 模式处理 conversation_node。
    """
    msg_preview = request.message[:50] if request.message else ""
    has_images = request.images and len(request.images) > 0
    logger.info(f"[Planning API] [{session_id}] 收到对话消息: {msg_preview}... (images={len(request.images or [])})")

    # Verify session
    db_session = await get_planning_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    config = PlanningRuntimeService.get_thread_config(session_id)

    # Build message - use multimodal if images are provided and enabled
    if has_images and MULTIMODAL_ENABLED:
        # Build multimodal message with first image (can extend to multiple images later)
        first_image = request.images[0]
        user_message = build_multimodal_message(
            text_content=request.message,
            image_base64=first_image.image_base64,
            image_format=first_image.image_format,
            role="human",
        )
        logger.debug(f"[Planning API] [{session_id}] Built multimodal message with image: format={first_image.image_format}")
    else:
        user_message = HumanMessage(content=request.message)

    content_chunks: List[str] = []

    try:
        graph = PlanningRuntimeService.get_graph()

        async for event in graph.astream_events(
            {"messages": [user_message]},
            config=config,
            version="v2"
        ):
            event_type = event.get("event")
            data = event.get("data", {})

            if event_type == "on_chain_stream":
                chunk = data.get("chunk")
                if chunk and hasattr(chunk, "content"):
                    token = chunk.content
                    content_chunks.append(token)
                    accumulated = "".join(content_chunks)

                    # Send delta event via SSE
                    from backend.services.sse_manager import sse_manager
                    sse_manager.append_event(session_id, {
                        "type": "ai_response_delta",
                        "delta": token,
                        "accumulated": accumulated,
                        "timestamp": datetime.now().isoformat()
                    })
                    sse_manager.publish_sync(session_id, {
                        "type": "ai_response_delta",
                        "delta": token,
                        "accumulated": accumulated,
                    })

            elif event_type == "on_tool_start":
                tool_name = data.get("name", "unknown")
                from backend.services.sse_manager import sse_manager
                sse_manager.append_event(session_id, {
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "timestamp": datetime.now().isoformat()
                })

            elif event_type == "on_tool_end":
                tool_name = data.get("name", "unknown")
                output = data.get("output", "")
                from backend.services.sse_manager import sse_manager
                sse_manager.append_event(session_id, {
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "status": "success",
                    "result_preview": str(output)[:200] if output else "",
                    "timestamp": datetime.now().isoformat()
                })

        # Send completion event
        final_content = "".join(content_chunks)
        from backend.services.sse_manager import sse_manager
        sse_manager.append_event(session_id, {
            "type": "ai_response_complete",
            "content": final_content,
            "timestamp": datetime.now().isoformat()
        })

        logger.info(f"[Planning API] [{session_id}] 对话消息处理完成")

        return {
            "success": True,
            "session_id": session_id,
            "message": "Chat message processed"
        }

    except Exception as e:
        logger.error(f"[Planning API] [{session_id}] 对话消息处理失败: {e}", exc_info=True)
        from backend.services.sse_manager import sse_manager
        sse_manager.append_event(session_id, {
            "type": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        })
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")


__all__ = ["router"]