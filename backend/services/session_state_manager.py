"""
会话状态管理器 - 线程安全的原子状态更新

提供统一的会话状态管理，确保原子更新和线程安全。
"""

import logging
from dataclasses import dataclass, field
from threading import RLock
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """
    线程安全的会话状态

    使用 dataclass 提供清晰的状态定义，
    所有属性访问都通过属性方法进行线程安全保护。

    Attributes:
        session_id: 会话唯一标识
        project_name: 项目名称
        status: 当前状态（running/completed/failed/paused）
        current_layer: 当前层级（1/2/3）
        _layer_1_completed: Layer 1 完成标志
        _layer_2_completed: Layer 2 完成标志
        _layer_3_completed: Layer 3 完成标志
        _pause_after_step: 步进模式暂停标志
        _events: 事件列表
        _lock: 线程安全锁
    """
    session_id: str
    project_name: str
    status: str = 'running'
    current_layer: int = 1
    _layer_1_completed: bool = False
    _layer_2_completed: bool = False
    _layer_3_completed: bool = False
    _pause_after_step: bool = False
    _events: List[Dict] = field(default_factory=list)
    _lock: RLock = field(default_factory=RLock)

    # ============================================
    # Layer 1 属性
    # ============================================

    @property
    def layer_1_completed(self) -> bool:
        """获取 Layer 1 完成状态（线程安全）"""
        with self._lock:
            return self._layer_1_completed

    @layer_1_completed.setter
    def layer_1_completed(self, value: bool) -> None:
        """设置 Layer 1 完成状态（线程安全）"""
        with self._lock:
            self._layer_1_completed = value
            logger.debug(f"[SessionState] {self.session_id} Layer 1 completed: {value}")

    # ============================================
    # Layer 2 属性
    # ============================================

    @property
    def layer_2_completed(self) -> bool:
        """获取 Layer 2 完成状态（线程安全）"""
        with self._lock:
            return self._layer_2_completed

    @layer_2_completed.setter
    def layer_2_completed(self, value: bool) -> None:
        """设置 Layer 2 完成状态（线程安全）"""
        with self._lock:
            self._layer_2_completed = value
            logger.debug(f"[SessionState] {self.session_id} Layer 2 completed: {value}")

    # ============================================
    # Layer 3 属性
    # ============================================

    @property
    def layer_3_completed(self) -> bool:
        """获取 Layer 3 完成状态（线程安全）"""
        with self._lock:
            return self._layer_3_completed

    @layer_3_completed.setter
    def layer_3_completed(self, value: bool) -> None:
        """设置 Layer 3 完成状态（线程安全）"""
        with self._lock:
            self._layer_3_completed = value
            logger.debug(f"[SessionState] {self.session_id} Layer 3 completed: {value}")

    # ============================================
    # 暂停和审查状态属性
    # ============================================

    @property
    def pause_after_step(self) -> bool:
        """获取步进模式暂停状态（线程安全）"""
        with self._lock:
            return self._pause_after_step

    @pause_after_step.setter
    def pause_after_step(self, value: bool) -> None:
        """设置步进模式暂停状态（线程安全）"""
        with self._lock:
            self._pause_after_step = value
            logger.debug(f"[SessionState] {self.session_id} pause_after_step: {value}")

    @property
    def waiting_for_review(self) -> bool:
        """
        派生属性：是否等待审查

        等待审查等同于暂停状态
        """
        return self.pause_after_step

    # ============================================
    # 事件管理方法
    # ============================================

    def add_event(self, event: Dict[str, Any]) -> None:
        """
        线程安全地添加事件到会话

        Args:
            event: 事件字典
        """
        with self._lock:
            self._events.append(event)
            logger.debug(f"[SessionState] {self.session_id} Event added: {event.get('type', 'unknown')}")

    def get_events(self) -> List[Dict[str, Any]]:
        """
        线程安全地获取事件列表副本

        Returns:
            事件列表的副本（避免外部修改）
        """
        with self._lock:
            events_copy = list(self._events)
            logger.debug(f"[SessionState] {self.session_id} Retrieved {len(events_copy)} events")
            return events_copy

    def clear_events(self) -> None:
        """
        清空事件列表（线程安全）

        用于测试或重置
        """
        with self._lock:
            self._events.clear()
            logger.debug(f"[SessionState] {self.session_id} Events cleared")

    # ============================================
    # 状态查询方法
    # ============================================

    def get_status(self) -> str:
        """获取当前状态"""
        with self._lock:
            return self.status

    def set_status(self, status: str) -> None:
        """
        设置状态（线程安全）

        Args:
            status: 新状态（running/completed/failed/paused）
        """
        with self._lock:
            old_status = self.status
            self.status = status
            logger.info(f"[SessionState] {self.session_id} Status: {old_status} -> {status}")

    def get_current_layer(self) -> int:
        """获取当前层级"""
        with self._lock:
            return self.current_layer

    def set_current_layer(self, layer: int) -> None:
        """
        设置当前层级（线程安全）

        Args:
            layer: 新层级（1/2/3）
        """
        with self._lock:
            old_layer = self.current_layer
            self.current_layer = layer
            logger.info(f"[SessionState] {self.session_id} Layer: {old_layer} -> {layer}")

    # ============================================
    # 实用方法
    # ============================================

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典（用于序列化和API响应）

        Returns:
            包含所有会话状态的字典
        """
        with self._lock:
            return {
                "session_id": self.session_id,
                "project_name": self.project_name,
                "status": self.status,
                "current_layer": self.current_layer,
                "layer_1_completed": self._layer_1_completed,
                "layer_2_completed": self._layer_2_completed,
                "layer_3_completed": self._layer_3_completed,
                "pause_after_step": self._pause_after_step,
                "waiting_for_review": self.waiting_for_review,
                "events_count": len(self._events),
            }

    def __repr__(self) -> str:
        """字符串表示"""
        return f"SessionState(id={self.session_id}, status={self.status}, layer={self.current_layer})"


# ============================================
# 会话状态管理器
# ============================================

class SessionStateManager:
    """
    会话状态管理器 - 单例模式

    提供全局的会话状态管理，确保原子更新和线程安全。
    """

    _instance: Optional['SessionStateManager'] = None
    _lock: RLock = RLock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化管理器"""
        if self._instance is not None:
            raise RuntimeError("SessionStateManager is a singleton. Use get_instance() instead.")

        # 会话状态存储：session_id -> SessionState
        self._sessions: Dict[str, SessionState] = {}
        self._lock = RLock()
        logger.info("SessionStateManager initialized")

    @classmethod
    def get_instance(cls) -> 'SessionStateManager':
        """
        获取管理器单例

        Returns:
            SessionStateManager 单例实例
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def create_session(
        self,
        session_id: str,
        project_name: str,
        initial_state: Dict[str, Any]
    ) -> SessionState:
        """
        创建新会话状态

        Args:
            session_id: 会话ID
            project_name: 项目名称
            initial_state: 初始状态

        Returns:
            创建的 SessionState 对象
        """
        with self._lock:
            if session_id in self._sessions:
                logger.warning(f"[SessionManager] Session {session_id} already exists")
                return self._sessions[session_id]

            session_state = SessionState(
                session_id=session_id,
                project_name=project_name,
                status="running",
                current_layer=1,
            )
            self._sessions[session_id] = session_state
            logger.info(f"[SessionManager] Created session state: {session_id}")
            return session_state

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """
        获取会话状态

        Args:
            session_id: 会话ID

        Returns:
            SessionState 对象，不存在时返回 None
        """
        with self._lock:
            return self._sessions.get(session_id)

    def remove_session(self, session_id: str) -> bool:
        """
        移除会话状态

        Args:
            session_id: 会话ID

        Returns:
            True: 成功, False: 会话不存在
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"[SessionManager] Session {session_id} not found")
                return False

            del self._sessions[session_id]
            logger.info(f"[SessionManager] Removed session state: {session_id}")
            return True

    def get_all_sessions(self) -> List[str]:
        """
        获取所有会话ID列表

        Returns:
            会话ID列表
        """
        with self._lock:
            return list(self._sessions.keys())

    def get_session_count(self) -> int:
        """
        获取当前会话数量

        Returns:
            会话总数
        """
        with self._lock:
            count = len(self._sessions)
            logger.debug(f"[SessionManager] Active sessions: {count}")
            return count

    def clear_all_sessions(self) -> None:
        """
        清空所有会话（用于测试）

        警告：此操作会删除所有会话状态
        """
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            logger.warning(f"[SessionManager] Cleared {count} sessions")

    # ============================================
    # 便捷方法：原子更新多个会话
    # ============================================

    def update_session_layer(
        self,
        session_id: str,
        layer: int,
        completed: bool
    ) -> bool:
        """
        原子更新层级完成状态

        Args:
            session_id: 会话ID
            layer: 层级（1/2/3）
            completed: 是否完成

        Returns:
            True: 成功, False: 会话不存在
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                logger.error(f"[SessionManager] Session {session_id} not found")
                return False

            if layer == 1:
                session.layer_1_completed = completed
            elif layer == 2:
                session.layer_2_completed = completed
            elif layer == 3:
                session.layer_3_completed = completed

            logger.info(f"[SessionManager] {session_id} Layer {layer} completed: {completed}")
            return True

    def set_session_pause(self, session_id: str, paused: bool) -> bool:
        """
        原子设置暂停状态

        Args:
            session_id: 会话ID
            paused: 是否暂停

        Returns:
            True: 成功, False: 会话不存在
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                logger.error(f"[SessionManager] Session {session_id} not found")
                return False

            session.pause_after_step = paused
            logger.info(f"[SessionManager] {session_id} Pause: {paused}")
            return True

    def add_session_event(
        self,
        session_id: str,
        event: Dict[str, Any]
    ) -> bool:
        """
        原子添加会话事件

        Args:
            session_id: 会话ID
            event: 事件字典

        Returns:
            True: 成功, False: 会话不存在
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                logger.error(f"[SessionManager] Session {session_id} not found")
                return False

            session.add_event(event)
            logger.debug(f"[SessionManager] {session_id} Event added: {event.get('type', 'unknown')}")
            return True

    def get_session_events(self, session_id: str) -> List[Dict[str, Any]]:
        """
        原子获取会话事件列表

        Args:
            session_id: 会话ID

        Returns:
            事件列表，会话不存在时返回空列表
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                logger.warning(f"[SessionManager] Session {session_id} not found")
                return []

            return session.get_events()

    def get_session_status(self, session_id: str) -> Optional[str]:
        """
        原子获取会话状态

        Args:
            session_id: 会话ID

        Returns:
            状态字符串，会话不存在时返回 None
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.get_status()
