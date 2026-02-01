"""
工具适配器基类

提供统一的适配器接口，隔离外部专业计算库的复杂性。
所有适配器都继承自BaseAdapter并实现其抽象方法。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

from ...utils.logger import get_logger

logger = get_logger(__name__)


class AdapterStatus(Enum):
    """适配器状态枚举"""
    IDLE = "idle"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass
class AdapterResult:
    """适配器执行结果"""
    success: bool
    status: AdapterStatus
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "success": self.success,
            "status": self.status.value,
            "data": self.data,
            "metadata": self.metadata,
            "error": self.error
        }


class BaseAdapter(ABC):
    """
    工具适配器基类

    所有专业工具适配器都应继承此类并实现以下方法：
    - validate_dependencies(): 验证外部依赖是否可用
    - initialize(): 初始化适配器
    - execute(): 执行核心计算逻辑
    - get_schema(): 获取输出数据的Schema定义
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化适配器

        Args:
            config: 适配器配置参数
        """
        self.config = config or {}
        self._status = AdapterStatus.IDLE
        self._dependencies_available = False
        self._error_message = None

        # 检查依赖
        self._check_dependencies()

    @property
    def status(self) -> AdapterStatus:
        """获取适配器状态"""
        return self._status

    @property
    def is_available(self) -> bool:
        """检查适配器是否可用（依赖已安装）"""
        return self._dependencies_available

    @property
    def last_error(self) -> Optional[str]:
        """获取最后一次错误信息"""
        return self._error_message

    def _check_dependencies(self):
        """
        检查外部依赖是否可用

        如果依赖不可用，适配器将进入DISABLED状态，但不会抛出异常。
        """
        try:
            self._dependencies_available = self.validate_dependencies()
            if self._dependencies_available:
                self._status = AdapterStatus.READY
                logger.debug(f"[{self.__class__.__name__}] 依赖检查通过")
            else:
                self._status = AdapterStatus.DISABLED
                logger.warning(f"[{self.__class__.__name__}] 依赖检查失败，适配器已禁用")
        except Exception as e:
            self._dependencies_available = False
            self._status = AdapterStatus.DISABLED
            self._error_message = f"依赖检查异常: {str(e)}"
            logger.error(f"[{self.__class__.__name__}] {self._error_message}")

    @abstractmethod
    def validate_dependencies(self) -> bool:
        """
        验证外部依赖是否可用

        子类应实现此方法来检查所需的外部库是否已安装。

        Returns:
            True if dependencies are available, False otherwise
        """
        pass

    @abstractmethod
    def initialize(self) -> bool:
        """
        初始化适配器

        子类应实现此方法来执行初始化逻辑（如加载模型、打开数据等）。

        Returns:
            True if initialization successful, False otherwise
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> AdapterResult:
        """
        执行核心计算逻辑

        子类应实现此方法来执行具体的专业计算。

        Args:
            **kwargs: 执行参数

        Returns:
            AdapterResult: 执行结果
        """
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """
        获取输出数据的Schema定义

        子类应实现此方法来定义输出数据的结构和验证规则。

        Returns:
            Dict containing schema definition
        """
        pass

    def run(self, **kwargs) -> AdapterResult:
        """
        运行适配器的安全包装方法

        此方法处理了状态管理、错误处理和日志记录。

        Args:
            **kwargs: 执行参数

        Returns:
            AdapterResult: 执行结果
        """
        # 检查依赖是否可用
        if not self._dependencies_available:
            return AdapterResult(
                success=False,
                status=AdapterStatus.DISABLED,
                data={},
                metadata={},
                error=f"适配器不可用：缺少外部依赖或依赖检查失败"
            )

        # 检查当前状态
        if self._status == AdapterStatus.RUNNING:
            logger.warning(f"[{self.__class__.__name__}] 适配器正在运行中，跳过本次调用")
            return AdapterResult(
                success=False,
                status=AdapterStatus.RUNNING,
                data={},
                metadata={},
                error="适配器正在运行中"
            )

        try:
            # 初始化适配器（如果尚未初始化）
            if self._status != AdapterStatus.READY:
                if not self.initialize():
                    return AdapterResult(
                        success=False,
                        status=self._status,
                        data={},
                        metadata={},
                        error=self._error_message or "初始化失败"
                    )

            # 执行计算
            self._status = AdapterStatus.RUNNING
            logger.info(f"[{self.__class__.__name__}] 开始执行")

            result = self.execute(**kwargs)

            # 更新状态
            if result.success:
                self._status = AdapterStatus.SUCCESS
                logger.info(f"[{self.__class__.__name__}] 执行成功")
            else:
                self._status = AdapterStatus.FAILED
                self._error_message = result.error
                logger.error(f"[{self.__class__.__name__}] 执行失败: {result.error}")

            return result

        except Exception as e:
            self._status = AdapterStatus.FAILED
            self._error_message = f"执行异常: {str(e)}"
            logger.exception(f"[{self.__class__.__name__}] 执行异常")
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=self._error_message
            )

    def reset(self):
        """重置适配器状态"""
        self._status = AdapterStatus.READY if self._dependencies_available else AdapterStatus.DISABLED
        self._error_message = None
        logger.debug(f"[{self.__class__.__name__}] 适配器已重置")

    def get_info(self) -> Dict[str, Any]:
        """
        获取适配器信息

        Returns:
            包含适配器元数据的字典
        """
        return {
            "adapter_name": self.__class__.__name__,
            "status": self._status.value,
            "is_available": self._dependencies_available,
            "last_error": self._error_message,
            "config": self.config,
            "schema": self.get_schema()
        }


class MockAdapter(BaseAdapter):
    """
    Mock适配器（仅用于测试）

    警告：此类仅用于单元测试和集成测试。

    ⚠️ 重要提示：
    - 生产环境中不应使用 MockAdapter，否则会导致不可预测的结果。
    - MockAdapter 返回的是预设的静态数据，不代表真实的分析结果。
    - 使用 MockAdapter 进行演示或展示可能会产生误导性的结果。

    正确的使用场景：
    - 单元测试中模拟适配器行为
    - 集成测试中隔离外部依赖
    - CI/CD 流水线中的快速测试

    错误的使用场景：
    - 生产环境部署
    - 用户演示或汇报
    - 真实规划项目分析
    """

    def __init__(self, mock_data: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.mock_data = mock_data or {}
        # 记录警告日志
        logger.warning(
            "[MockAdapter] MockAdapter 已初始化。"
            "请注意：MockAdapter 仅用于测试环境，不应在生产环境中使用！"
        )

    def validate_dependencies(self) -> bool:
        """Mock适配器始终可用"""
        return True

    def initialize(self) -> bool:
        """Mock适配器无需初始化"""
        self._status = AdapterStatus.READY
        logger.warning(
            "[MockAdapter] MockAdapter 已就绪。"
            "返回的数据为模拟数据，不代表真实分析结果。"
        )
        return True

    def execute(self, **kwargs) -> AdapterResult:
        """返回模拟数据"""
        logger.warning(
            "[MockAdapter] 执行分析并返回模拟数据。"
            "请确保此行为仅在测试环境中发生。"
        )
        return AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data=self.mock_data,
            metadata={"adapter_type": "mock", "warning": "This is mock data, not real analysis results"}
        )

    def get_schema(self) -> Dict[str, Any]:
        """返回空Schema"""
        return {
            "type": "object",
            "properties": {},
            "warning": "MockAdapter returns mock data, not real analysis results"
        }
