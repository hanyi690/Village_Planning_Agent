"""
Multimodal Message Builder for Village Planning Agent

Builds LangChain messages that support text + image content.
Used when MULTIMODAL_ENABLED is true to send images to vision-capable LLMs.

Supported formats:
- OpenAI GPT-4o: {"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}
- ZhipuAI GLM-4V: Similar format with image_url content blocks
"""

from typing import List, Union, Optional, Dict, Any, Literal
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from ..utils.logger import get_logger
from app.core.settings import MULTIMODAL_ENABLED, IMAGE_DETAIL_LEVEL

logger = get_logger(__name__)

# Type-safe role definition
MessageRole = Literal["human", "ai", "system"]


def build_multimodal_message(
    text_content: str,
    image_base64: Optional[str] = None,
    image_format: Optional[str] = None,
    role: MessageRole = "human",
    detail: Optional[str] = None,
) -> Union[HumanMessage, AIMessage, SystemMessage]:
    """
    Build a multimodal message with text and optional image content.

    Args:
        text_content: The text content of the message
        image_base64: Optional base64-encoded image data
        image_format: Image format (e.g., "jpeg", "png", "gif")
        role: Message role ("human", "ai", or "system")
        detail: Image detail level for OpenAI ("low", "high", or "auto")

    Returns:
        LangChain message instance (HumanMessage, AIMessage, or SystemMessage)

    Examples:
        >>> # Text-only message
        >>> msg = build_multimodal_message("What is in this image?")
        >>> # Multimodal message with image
        >>> msg = build_multimodal_message(
        ...     "Describe this village layout",
        ...     image_base64="iVBORw0KGgo...",
        ...     image_format="png"
        ... )
    """
    if not MULTIMODAL_ENABLED:
        # If multimodal is disabled, just return text message
        logger.debug("[MessageBuilder] Multimodal disabled, returning text-only message")
        if role == "human":
            return HumanMessage(content=text_content)
        elif role == "ai":
            return AIMessage(content=text_content)
        else:
            return SystemMessage(content=text_content)

    # Build content array for multimodal message
    content: List[Union[str, Dict[str, Any]]] = []

    # Add text content
    if text_content:
        content.append({"type": "text", "text": text_content})

    # Add image content
    if image_base64 and image_format:
        image_url = f"data:image/{image_format};base64,{image_base64}"
        image_block = {
            "type": "image_url",
            "image_url": {
                "url": image_url,
            }
        }

        # Add detail level for OpenAI
        if detail or IMAGE_DETAIL_LEVEL:
            image_block["image_url"]["detail"] = detail or IMAGE_DETAIL_LEVEL

        content.append(image_block)
        logger.debug(f"[MessageBuilder] Added image block: format={image_format}, detail={detail or IMAGE_DETAIL_LEVEL}")

    # Create appropriate message type
    if role == "human":
        return HumanMessage(content=content)
    elif role == "ai":
        return AIMessage(content=content)
    else:
        # System messages typically don't support images
        return SystemMessage(content=text_content)


def is_image_message_supported(provider: str) -> bool:
    """
    Check if a provider supports image/vision messages.

    Args:
        provider: Provider name ("openai", "zhipuai", "deepseek")

    Returns:
        True if the provider supports vision capabilities
    """
    # OpenAI GPT-4o and GPT-4-vision support images
    if provider in ("openai", "deepseek"):
        return True  # DeepSeek may not actually support, but we try

    # ZhipuAI GLM-4V supports images
    if provider == "zhipuai":
        return True  # GLM-4V

    return False


def get_recommended_multimodal_model(provider: str) -> str:
    """
    Get the recommended multimodal model for a provider.

    Priority: MULTIMODAL_MODEL env var > provider-specific default

    Args:
        provider: Provider name

    Returns:
        Recommended model name for vision tasks
    """
    from app.core.settings import MULTIMODAL_MODEL

    # Use configured multimodal model if available
    if MULTIMODAL_MODEL:
        logger.debug(f"[MessageBuilder] Using configured MULTIMODAL_MODEL: {MULTIMODAL_MODEL}")
        return MULTIMODAL_MODEL

    # Fallback to provider-specific defaults
    if provider == "openai":
        return "gpt-4o"  # Most capable vision model
    elif provider == "zhipuai":
        return "glm-4v"  # ZhipuAI vision model
    elif provider == "deepseek":
        logger.warning("[MessageBuilder] DeepSeek does not support vision, returning text model")
        return "deepseek-chat"

    return "gpt-4o"  # Default fallback