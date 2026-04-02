"""
网络可达性内置工具

基于交通网络数据，计算各节点的可达性指标。
"""

from typing import Dict, Any

from ..registry import ToolRegistry
from ...utils.logger import get_logger

logger = get_logger(__name__)


@ToolRegistry.register("network_accessibility")
def calculate_network_accessibility(context: Dict[str, Any]) -> str:
    """
    网络可达性分析

    基于交通网络数据，计算各节点的可达性指标

    Args:
        context: 包含 traffic 等现状分析的上下文

    Returns:
        格式化的可达性分析结果
    """
    try:
        from ..adapters.analysis import NetworkAnalysisAdapter
        adapter = NetworkAnalysisAdapter()

        result = adapter.analyze_accessibility(context)

        return f"""## 交通可达性分析结果

{result}

**分析方法**：网络分析法
**路网数据**：OD 成本矩阵
"""
    except ImportError:
        logger.error("[network_accessibility] 网络分析模块未安装")
        return """## 交通可达性分析错误

**错误**: 网络分析模块未安装或导入失败。

**解决方案**: 请安装依赖 `pip install networkx` 后重试。
"""
    except Exception as e:
        logger.error(f"[network_accessibility] 分析失败: {e}")
        return f"""## 交通可达性分析错误

**错误**: {str(e)}

**上下文**: 请确保提供了有效的交通网络数据（包含 nodes 和 edges）。
"""


__all__ = ["calculate_network_accessibility"]