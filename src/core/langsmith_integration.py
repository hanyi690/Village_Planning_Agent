"""
LangSmith Integration Module

Provides centralized LangSmith tracing functionality for the Village Planning Agent.

Features:
- Singleton LangSmithManager for consistent access
- Automatic configuration validation
- Callback handler management
- Run metadata creation with project and dimension context
- Graceful degradation when LangSmith is disabled or misconfigured

Usage:
    >>> from src.core.langsmith_integration import get_langsmith_manager
    >>> langsmith = get_langsmith_manager()
    >>> if langsmith.is_enabled():
    ...     callbacks = langsmith.get_callbacks()
    ...     metadata = langsmith.create_run_metadata(project_name="My Village", dimension="industry")
"""

import os
from typing import Dict, Any, Optional, List
from datetime import datetime

from .config import (
    LANGCHAIN_TRACING_V2,
    LANGCHAIN_API_KEY,
    LANGCHAIN_PROJECT,
    LANGCHAIN_ENDPOINT,
    LANGCHAIN_CALLBACKS_BACKGROUND
)
from ..utils.logger import get_logger

logger = get_logger(__name__)


class LangSmithManager:
    """
    LangSmith Manager - Singleton pattern for LangSmith integration

    Manages LangSmith tracing configuration, client initialization,
    and provides unified interface for callbacks and metadata.
    """

    _instance: Optional['LangSmithManager'] = None
    _initialized: bool = False

    def __new__(cls) -> 'LangSmithManager':
        """Implement singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize LangSmith manager (only once)"""
        if LangSmithManager._initialized:
            return

        self._enabled: bool = False
        self._client: Optional[Any] = None
        self._callbacks: List[Any] = []
        self._config: Dict[str, Any] = {}

        LangSmithManager._initialized = True
        self._initialize()

    def _initialize(self) -> None:
        """
        Initialize LangSmith client and validate configuration

        Performs comprehensive validation of LangSmith settings:
        1. Check if tracing is enabled
        2. Validate API key presence
        3. Initialize LangSmith client
        4. Configure callback handlers
        """
        self._config = {
            "tracing_v2": LANGCHAIN_TRACING_V2,
            "api_key": LANGCHAIN_API_KEY,
            "project": LANGCHAIN_PROJECT,
            "endpoint": LANGCHAIN_ENDPOINT,
            "background": LANGCHAIN_CALLBACKS_BACKGROUND
        }

        # Check if tracing is enabled
        if not LANGCHAIN_TRACING_V2:
            logger.info("[LangSmith] Tracing is disabled via LANGCHAIN_TRACING_V2")
            return

        # Validate API key
        if not LANGCHAIN_API_KEY:
            logger.warning(
                "[LangSmith] LANGCHAIN_TRACING_V2 is true but LANGCHAIN_API_KEY is not set. "
                "Tracing will be disabled. Set your API key in .env file."
            )
            return

        # Initialize LangSmith client
        try:
            self._initialize_client()
            self._enabled = True
            logger.info(f"[LangSmith] Tracing enabled for project: {LANGCHAIN_PROJECT}")

        except ImportError as e:
            logger.warning(f"[LangSmith] Failed to import langsmith: {e}. Tracing disabled.")
        except Exception as e:
            logger.error(f"[LangSmith] Failed to initialize: {e}. Tracing disabled.")

    def _initialize_client(self) -> None:
        """
        Initialize the LangSmith client

        Imports and initializes langsmith client with configured settings.
        Sets up environment variables for LangChain auto-tracing.
        """
        try:
            import langsmith
            # LangChain v1: LangChainTracer moved to langchain_core.tracers
            try:
                from langchain_core.tracers.langchain import LangChainTracer
            except ImportError:
                from langchain.callbacks import LangChainTracer  # Fallback for older versions
            try:
                from langchain_core.tracers.langchain import LangSmithRunTree
            except ImportError:
                from langchain.smith import LangSmithRunTree  # Fallback for older versions

            # Set environment variables for LangChain auto-tracing
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY
            os.environ["LANGCHAIN_PROJECT"] = LANGCHAIN_PROJECT

            if LANGCHAIN_ENDPOINT:
                os.environ["LANGCHAIN_ENDPOINT"] = LANGCHAIN_ENDPOINT

            if LANGCHAIN_CALLBACKS_BACKGROUND:
                os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "true"

            # Create tracer callback
            self._callbacks = [LangChainTracer()]

            # Store client reference (for future use)
            self._client = langsmith.Client(api_key=LANGCHAIN_API_KEY)

            logger.debug("[LangSmith] Client initialized successfully")

        except ImportError as e:
            logger.warning(f"[LangSmith] langsmith package not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"[LangSmith] Client initialization failed: {e}")
            raise

    def is_enabled(self) -> bool:
        """
        Check if LangSmith tracing is currently enabled

        Returns:
            True if tracing is enabled and configured, False otherwise
        """
        return self._enabled

    def get_callbacks(self) -> List[Any]:
        """
        Get LangSmith callback handlers for LLM calls

        Returns:
            List of callback handlers (empty list if disabled)

        Example:
            >>> callbacks = langsmith.get_callbacks()
            >>> llm.invoke([HumanMessage(content="Hello")], callbacks=callbacks)
        """
        if not self._enabled:
            return []
        return self._callbacks.copy()

    def create_run_metadata(
        self,
        project_name: str = "村庄",
        dimension: Optional[str] = None,
        layer: Optional[int] = None,
        extra_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create run metadata for LangSmith tracing

        Metadata helps organize and filter traces in LangSmith Dashboard.

        Args:
            project_name: Name of the village project
            dimension: Dimension key (e.g., "industry", "traffic")
            layer: Planning layer (1=analysis, 2=concept, 3=detailed)
            extra_info: Additional metadata fields

        Returns:
            Dictionary with metadata fields

        Example:
            >>> metadata = langsmith.create_run_metadata(
            ...     project_name="My Village",
            ...     dimension="industry",
            ...     layer=3
            ... )
        """
        metadata = {
            "project_name": project_name,
            "timestamp": datetime.now().isoformat(),
            "agent_version": "v4.1.0"  # Update with actual version
        }

        if dimension:
            metadata["dimension"] = dimension

        if layer:
            layer_names = {1: "analysis", 2: "concept", 3: "detailed"}
            metadata["layer"] = layer
            metadata["layer_name"] = layer_names.get(layer, "unknown")

        if extra_info:
            metadata.update(extra_info)

        return metadata

    def get_config(self) -> Dict[str, Any]:
        """
        Get current LangSmith configuration (safe for logging)

        Returns:
            Configuration dictionary with sensitive data masked
        """
        config = self._config.copy()
        # Mask API key for security
        if config.get("api_key"):
            config["api_key"] = "***" + config["api_key"][-4:] if len(config["api_key"]) > 4 else "***"
        return config

    def enable(self) -> bool:
        """
        Manually enable LangSmith tracing

        Returns:
            True if successfully enabled
        """
        if not LANGCHAIN_API_KEY:
            logger.error("[LangSmith] Cannot enable: LANGCHAIN_API_KEY not set")
            return False

        if not self._enabled:
            try:
                self._initialize_client()
                self._enabled = True
                logger.info("[LangSmith] Tracing manually enabled")
                return True
            except Exception as e:
                logger.error(f"[LangSmith] Failed to enable: {e}")
                return False

        return True

    def disable(self) -> None:
        """Manually disable LangSmith tracing"""
        if self._enabled:
            self._enabled = False
            logger.info("[LangSmith] Tracing manually disabled")


# Singleton instance accessor
_manager_instance: Optional[LangSmithManager] = None


def get_langsmith_manager() -> LangSmithManager:
    """
    Get the singleton LangSmithManager instance

    This is the recommended way to access LangSmith functionality.

    Returns:
        LangSmithManager singleton instance

    Example:
        >>> from src.core.langsmith_integration import get_langsmith_manager
        >>> langsmith = get_langsmith_manager()
        >>> if langsmith.is_enabled():
        ...     callbacks = langsmith.get_callbacks()
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = LangSmithManager()
    return _manager_instance


# Convenience functions for quick access
def is_tracing_enabled() -> bool:
    """Quick check if tracing is enabled"""
    return get_langsmith_manager().is_enabled()


def get_tracing_callbacks() -> List[Any]:
    """Quick access to tracing callbacks"""
    return get_langsmith_manager().get_callbacks()


def create_run_metadata(
    project_name: str = "村庄",
    dimension: Optional[str] = None,
    layer: Optional[int] = None,
    extra_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Quick access to metadata creation"""
    return get_langsmith_manager().create_run_metadata(
        project_name=project_name,
        dimension=dimension,
        layer=layer,
        extra_info=extra_info
    )


__all__ = [
    "LangSmithManager",
    "get_langsmith_manager",
    "is_tracing_enabled",
    "get_tracing_callbacks",
    "create_run_metadata"
]
