"""
Session Helper - 统一会话查找逻辑
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


class SessionHelper:
    """会话辅助类 - 统一会话和村庄目录查找"""

    TIMESTAMP_PATTERN = re.compile(r"^\d{8}_\d{6}$")

    def __init__(self, results_dir: Path):
        """
        初始化

        Args:
            results_dir: 结果目录路径
        """
        self.results_dir = results_dir

    def resolve_village_dir(self, village_name: str) -> Path:
        """
        解析村庄目录

        Args:
            village_name: 村庄名称

        Returns:
            村庄目录路径

        Raises:
            HTTPException: 村庄不存在
        """
        from fastapi import HTTPException

        village_dir = self.results_dir / village_name
        if not village_dir.exists():
            raise HTTPException(status_code=404, detail=f"村庄不存在: {village_name}")
        return village_dir

    def resolve_session_dir(
        self,
        village_name: str,
        session: Optional[str] = None,
        require_session: bool = True
    ) -> Tuple[Path, str]:
        """
        解析会话目录

        Args:
            village_name: 村庄名称
            session: 会话ID（可选）
            require_session: 是否要求会话必须存在

        Returns:
            (会话目录, 会话ID) 元组

        Raises:
            HTTPException: 村庄不存在或会话不存在
        """
        from fastapi import HTTPException

        village_dir = self.resolve_village_dir(village_name)

        if session:
            session_dir = village_dir / session
            if not session_dir.exists():
                raise HTTPException(status_code=404, detail=f"会话不存在: {session}")
            return session_dir, session

        # 使用最新会话
        sessions = self._list_session_dirs(village_dir)
        if require_session and not sessions:
            raise HTTPException(status_code=404, detail=f"村庄没有规划会话")

        if not sessions:
            return village_dir, ""

        sessions.sort(reverse=True)
        latest_session = sessions[0]
        return village_dir / latest_session, latest_session

    def list_all_sessions(self, village_name: str) -> list:
        """
        列出村庄的所有会话

        Args:
            village_name: 村庄名称

        Returns:
            会话信息列表
        """
        village_dir = self.resolve_village_dir(village_name)
        sessions = []

        for session_dir in village_dir.iterdir():
            if not session_dir.is_dir() or not self._is_timestamp(session_dir.name):
                continue

            created_at = datetime.fromtimestamp(session_dir.stat().st_ctime)
            sessions.append({
                "session_id": session_dir.name,
                "timestamp": created_at.isoformat(),
                "has_final_report": (session_dir / "final_combined_*.md").exists()
            })

        sessions.sort(key=lambda s: s["timestamp"], reverse=True)
        return sessions

    def _list_session_dirs(self, village_dir: Path) -> list:
        """
        列出会话目录

        Args:
            village_dir: 村庄目录

        Returns:
            会话目录名称列表
        """
        return [
            s.name for s in village_dir.iterdir()
            if s.is_dir() and self._is_timestamp(s.name)
        ]

    @classmethod
    def _is_timestamp(cls, name: str) -> bool:
        """
        检查目录名是否是时间戳格式 (YYYYMMDD_HHMMSS)

        Args:
            name: 目录名

        Returns:
            是否是时间戳格式
        """
        return bool(cls.TIMESTAMP_PATTERN.match(name))


__all__ = ["SessionHelper"]
