"""
OutputManager Registry - Manages OutputManager instances outside LangGraph state
"""
import threading
from typing import Dict, Optional
from .output_manager import OutputManager
from .logger import get_logger

logger = get_logger(__name__)

class OutputManagerRegistry:
    """Thread-safe registry for OutputManager instances"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._registry: Dict[str, OutputManager] = {}
        return cls._instance

    def register(self, session_id: str, output_manager: OutputManager) -> None:
        """Register an OutputManager for a session"""
        with self._lock:
            self._registry[session_id] = output_manager
            logger.info(f"[OutputManagerRegistry] Registered: {session_id}")

    def get(self, session_id: str) -> Optional[OutputManager]:
        """Get OutputManager for a session"""
        with self._lock:
            return self._registry.get(session_id)

    def remove(self, session_id: str) -> None:
        """Remove OutputManager for a session"""
        with self._lock:
            if session_id in self._registry:
                del self._registry[session_id]
                logger.info(f"[OutputManagerRegistry] Removed: {session_id}")

# Global instance
_output_manager_registry = OutputManagerRegistry()

def get_output_manager_registry() -> OutputManagerRegistry:
    return _output_manager_registry
