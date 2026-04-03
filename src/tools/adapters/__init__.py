"""
工具适配器模块

提供插件化的工具适配器管理，隔离外部专业计算库的复杂性。
"""

from typing import Dict, Type, Optional, Any
from .base_adapter import BaseAdapter, AdapterStatus, AdapterResult, MockAdapter
from .schema_registry import SchemaRegistry, SchemaDefinition, get_schema_registry
from ...utils.logger import get_logger

_logger = get_logger(__name__)


class AdapterFactory:
    """
    适配器工厂类

    负责创建和管理适配器实例，支持按需加载和缓存。
    """

    def __init__(self):
        """初始化适配器工厂"""
        self._adapter_classes: Dict[str, Type[BaseAdapter]] = {}
        self._adapter_instances: Dict[str, BaseAdapter] = {}
        self._schema_registry = get_schema_registry()

        _logger.info("[AdapterFactory] 适配器工厂已初始化")

    def register_adapter_class(self, name: str, adapter_class: Type[BaseAdapter]) -> bool:
        """
        注册适配器类

        Args:
            name: 适配器名称（唯一标识）
            adapter_class: 适配器类

        Returns:
            True if registration successful
        """
        try:
            if not issubclass(adapter_class, BaseAdapter):
                raise TypeError(f"{adapter_class} 必须继承自 BaseAdapter")

            self._adapter_classes[name] = adapter_class
            _logger.info(f"[AdapterFactory] 已注册适配器类: {name} -> {adapter_class.__name__}")
            return True

        except Exception as e:
            _logger.error(f"[AdapterFactory] 注册适配器类失败: {str(e)}")
            return False

    def create_adapter(
        self,
        name: str,
        config: Optional[Dict[str, Any]] = None,
        use_cache: bool = True
    ) -> Optional[BaseAdapter]:
        """
        创建适配器实例

        Args:
            name: 适配器名称
            config: 适配器配置参数
            use_cache: 是否使用缓存的实例

        Returns:
            适配器实例，如果创建失败则返回None
        """
        # 检查缓存
        if use_cache and name in self._adapter_instances:
            _logger.debug(f"[AdapterFactory] 使用缓存的适配器实例: {name}")
            return self._adapter_instances[name]

        # 检查适配器类是否已注册
        if name not in self._adapter_classes:
            _logger.error(f"[AdapterFactory] 适配器类未注册: {name}")
            return None

        try:
            # 创建实例
            adapter_class = self._adapter_classes[name]
            adapter_instance = adapter_class(config=config)

            # 缓存实例
            if use_cache:
                self._adapter_instances[name] = adapter_instance

            _logger.info(f"[AdapterFactory] 已创建适配器实例: {name}")
            return adapter_instance

        except Exception as e:
            _logger.error(f"[AdapterFactory] 创建适配器实例失败: {str(e)}")
            return None

    def get_adapter(self, name: str, config: Optional[Dict[str, Any]] = None) -> Optional[BaseAdapter]:
        """
        获取适配器实例（别名方法）

        Args:
            name: 适配器名称
            config: 适配器配置参数

        Returns:
            适配器实例
        """
        return self.create_adapter(name, config, use_cache=True)

    def list_available_adapters(self) -> Dict[str, Dict[str, Any]]:
        """
        列出所有可用的适配器

        Returns:
            适配器信息字典 {name: {class_name, is_available, status}}
        """
        result = {}

        for name, adapter_class in self._adapter_classes.items():
            # 尝试创建实例以检查依赖
            adapter = self.create_adapter(name, use_cache=True)
            if adapter:
                result[name] = {
                    "class_name": adapter_class.__name__,
                    "is_available": adapter.is_available,
                    "status": adapter.status.value,
                    "last_error": adapter.last_error
                }
            else:
                result[name] = {
                    "class_name": adapter_class.__name__,
                    "is_available": False,
                    "status": "creation_failed",
                    "last_error": "实例创建失败"
                }

        return result

    def run_adapter(
        self,
        name: str,
        **kwargs
    ) -> AdapterResult:
        """
        运行适配器

        Args:
            name: 适配器名称
            **kwargs: 执行参数

        Returns:
            适配器执行结果
        """
        adapter = self.get_adapter(name)
        if not adapter:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"适配器不可用: {name}"
            )

        _logger.info(f"[AdapterFactory] 运行适配器: {name}")
        return adapter.run(**kwargs)

    def validate_result(
        self,
        schema_name: str,
        result: AdapterResult,
        schema_version: str = "1.0.0"
    ) -> Dict[str, Any]:
        """
        验证适配器结果是否符合Schema

        Args:
            schema_name: Schema名称
            result: 适配器执行结果
            schema_version: Schema版本

        Returns:
            验证结果字典
        """
        if not result.success:
            return {
                "valid": False,
                "errors": [f"适配器执行失败: {result.error}"],
                "schema": None
            }

        return self._schema_registry.validate(schema_name, result.data, schema_version)

    def get_schema_info(self, schema_name: str, schema_version: str = "1.0.0") -> Optional[SchemaDefinition]:
        """
        获取Schema定义

        Args:
            schema_name: Schema名称
            schema_version: Schema版本

        Returns:
            SchemaDefinition对象
        """
        return self._schema_registry.get(schema_name, schema_version)

    def clear_cache(self):
        """清除所有缓存的适配器实例"""
        self._adapter_instances.clear()
        _logger.info("[AdapterFactory] 已清除适配器实例缓存")


# 全局适配器工厂实例
_global_factory: Optional[AdapterFactory] = None


def get_adapter_factory() -> AdapterFactory:
    """
    获取全局适配器工厂实例

    Returns:
        AdapterFactory实例
    """
    global _global_factory
    if _global_factory is None:
        _global_factory = AdapterFactory()
        _initialize_builtin_adapters(_global_factory)
    return _global_factory


def _initialize_builtin_adapters(factory: AdapterFactory):
    """
    初始化内置适配器

    注意：实际的适配器类将在后续文件中定义（gis_adapter, network_adapter等）
    """
    _logger.info("[AdapterFactory] 初始化内置适配器（延迟加载）")

    # Analysis 适配器
    try:
        from .analysis import GISAnalysisAdapter, NetworkAnalysisAdapter, PopulationPredictionAdapter
        factory.register_adapter_class("gis_analysis", GISAnalysisAdapter)
        factory.register_adapter_class("network_analysis", NetworkAnalysisAdapter)
        factory.register_adapter_class("population_prediction", PopulationPredictionAdapter)
    except ImportError:
        _logger.warning("[AdapterFactory] Analysis 适配器模块未找到，将在稍后注册")

    # Data Fetch 适配器
    try:
        from .data_fetch import GISDataFetchAdapter
        factory.register_adapter_class("gis_data_fetch", GISDataFetchAdapter)
    except ImportError:
        _logger.warning("[AdapterFactory] Data Fetch 适配器模块未找到，将在稍后注册")




def create_adapter(name: str, config: Optional[Dict[str, Any]] = None) -> Optional[BaseAdapter]:
    """
    创建适配器的便捷函数

    Args:
        name: 适配器名称
        config: 适配器配置

    Returns:
        适配器实例
    """
    factory = get_adapter_factory()
    return factory.create_adapter(name, config)


def run_adapter(name: str, **kwargs) -> AdapterResult:
    """
    运行适配器的便捷函数

    Args:
        name: 适配器名称
        **kwargs: 执行参数

    Returns:
        适配器执行结果
    """
    factory = get_adapter_factory()
    return factory.run_adapter(name, **kwargs)


# 导出公共接口
__all__ = [
    "BaseAdapter",
    "AdapterStatus",
    "AdapterResult",
    "MockAdapter",
    "SchemaRegistry",
    "SchemaDefinition",
    "get_schema_registry",
    "AdapterFactory",
    "get_adapter_factory",
    "create_adapter",
    "run_adapter",
]