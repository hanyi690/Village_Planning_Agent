"""
Error Handler - 统一错误处理

提供标准化的错误响应方法。
"""

from typing import Optional
from fastapi import HTTPException


class ErrorHandler:
    """错误处理类 - 提供统一的错误响应"""

    @staticmethod
    def village_not_found(village_name: str) -> HTTPException:
        """
        村庄不存在错误

        Args:
            village_name: 村庄名称

        Returns:
            HTTPException 实例
        """
        return HTTPException(
            status_code=404,
            detail=f"村庄不存在: {village_name}"
        )

    @staticmethod
    def session_not_found(session: str) -> HTTPException:
        """
        会话不存在错误

        Args:
            session: 会话ID

        Returns:
            HTTPException 实例
        """
        return HTTPException(
            status_code=404,
            detail=f"会话不存在: {session}"
        )

    @staticmethod
    def no_sessions(village_name: Optional[str] = None) -> HTTPException:
        """
        没有会话错误

        Args:
            village_name: 村庄名称（可选）

        Returns:
            HTTPException 实例
        """
        if village_name:
            return HTTPException(
                status_code=404,
                detail=f"村庄 {village_name} 没有规划会话"
            )
        return HTTPException(
            status_code=404,
            detail="村庄没有规划会话"
        )

    @staticmethod
    def file_not_found(filename: str, layer: Optional[str] = None) -> HTTPException:
        """
        文件不存在错误

        Args:
            filename: 文件名
            layer: 层级（可选）

        Returns:
            HTTPException 实例
        """
        if layer:
            return HTTPException(
                status_code=404,
                detail=f"层级 {layer} 中的文件不存在: {filename}"
            )
        return HTTPException(
            status_code=404,
            detail=f"文件不存在: {filename}"
        )

    @staticmethod
    def layer_not_found(layer: str) -> HTTPException:
        """
        层级不存在错误

        Args:
            layer: 层级名称

        Returns:
            HTTPException 实例
        """
        return HTTPException(
            status_code=404,
            detail=f"层级不存在: {layer}"
        )

    @staticmethod
    def checkpoint_not_found(checkpoint_id: str) -> HTTPException:
        """
        检查点不存在错误

        Args:
            checkpoint_id: 检查点ID

        Returns:
            HTTPException 实例
        """
        return HTTPException(
            status_code=404,
            detail=f"检查点不存在: {checkpoint_id}"
        )

    @staticmethod
    def generic_error(message: str, status_code: int = 400) -> HTTPException:
        """
        通用错误

        Args:
            message: 错误消息
            status_code: HTTP状态码

        Returns:
            HTTPException 实例
        """
        return HTTPException(
            status_code=status_code,
            detail=message
        )


__all__ = ["ErrorHandler"]
