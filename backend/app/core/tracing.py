"""
LangSmith Integration Module

Provides centralized LangSmith tracing functionality.
"""

import os
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.core.settings import (
    LANGCHAIN_TRACING_V2,
    LANGCHAIN_API_KEY,
    LANGCHAIN_PROJECT,
    LANGCHAIN_ENDPOINT,
    LANGCHAIN_CALLBACKS_BACKGROUND
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class LangSmithManager:
    """LangSmith Manager - Singleton pattern for LangSmith integration"""

    _instance: Optional['LangSmithManager'] = None
    _initialized: bool = False

    def __new__(cls) -> 'LangSmithManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if LangSmithManager._initialized:
            return

        self._enabled: bool = False
        self._client: Optional[Any] = None
        self._callbacks: List[Any] = []
        self._config: Dict[str, Any] = {}

        LangSmithManager._initialized = True
        self._initialize()

    def _initialize(self) -> None:
        self._config = {
            "tracing_v2": LANGCHAIN_TRACING_V2,
            "api_key": LANGCHAIN_API_KEY,
            "project": LANGCHAIN_PROJECT,
            "endpoint": LANGCHAIN_ENDPOINT,
            "background": LANGCHAIN_CALLBACKS_BACKGROUND
        }

        if not LANGCHAIN_TRACING_V2:
            logger.info("[LangSmith] Tracing is disabled")
            return

        if not LANGCHAIN_API_KEY:
            logger.warning("[LangSmith] API key not set")
            return

        try:
            self._initialize_client()
            self._enabled = True
            logger.info(f"[LangSmith] Tracing enabled for project: {LANGCHAIN_PROJECT}")
        except ImportError as e:
            logger.warning(f"[LangSmith] Failed to import: {e}")
        except Exception as e:
            logger.error(f"[LangSmith] Failed to initialize: {e}")

    def _initialize_client(self) -> None:
        try:
            import langsmith
            try:
                from langchain_core.tracers.langchain import LangChainTracer
            except ImportError:
                from langchain.callbacks import LangChainTracer

            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY
            os.environ["LANGCHAIN_PROJECT"] = LANGCHAIN_PROJECT

            if LANGCHAIN_ENDPOINT:
                os.environ["LANGCHAIN_ENDPOINT"] = LANGCHAIN_ENDPOINT
            if LANGCHAIN_CALLBACKS_BACKGROUND:
                os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "true"

            self._callbacks = [LangChainTracer()]
            self._client = langsmith.Client(api_key=LANGCHAIN_API_KEY)
            logger.debug("[LangSmith] Client initialized")
        except ImportError as e:
            logger.warning(f"[LangSmith] Package not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"[LangSmith] Initialization failed: {e}")
            raise

    def is_enabled(self) -> bool:
        return self._enabled

    def get_callbacks(self) -> List[Any]:
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
        metadata = {
            "project_name": project_name,
            "timestamp": datetime.now().isoformat(),
            "agent_version": "v4.1.0"
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
        config = self._config.copy()
        if config.get("api_key"):
            config["api_key"] = "***" + config["api_key"][-4:] if len(config["api_key"]) > 4 else "***"
        return config

    def enable(self) -> bool:
        if not LANGCHAIN_API_KEY:
            logger.error("[LangSmith] Cannot enable: API key not set")
            return False
        if not self._enabled:
            try:
                self._initialize_client()
                self._enabled = True
                logger.info("[LangSmith] Tracing enabled")
                return True
            except Exception as e:
                logger.error(f"[LangSmith] Failed to enable: {e}")
                return False
        return True

    def disable(self) -> None:
        if self._enabled:
            self._enabled = False
            logger.info("[LangSmith] Tracing disabled")


_manager_instance: Optional[LangSmithManager] = None


def get_langsmith_manager() -> LangSmithManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = LangSmithManager()
    return _manager_instance


def is_tracing_enabled() -> bool:
    return get_langsmith_manager().is_enabled()


def get_tracing_callbacks() -> List[Any]:
    return get_langsmith_manager().get_callbacks()


def create_run_metadata(
    project_name: str = "村庄",
    dimension: Optional[str] = None,
    layer: Optional[int] = None,
    extra_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
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