"""
工具包装器 - 无循环依赖版本

将 Adapter 适配器包装为可注册的工具函数，
但不自动注册，由调用者决定注册时机。
"""

from typing import Dict, Any, Type, Optional, Callable
from .base_adapter import BaseAdapter, AdapterResult, AdapterStatus
from ...utils.logger import get_logger

logger = get_logger(__name__)

# 已知上下文键列表
KNOWN_CONTEXT_KEYS = ("analysis_type", "village_data", "socio_economic", "traffic", "land_use")


def create_adapter_tool_function(
    adapter_class: Type[BaseAdapter],
    adapter_name: str,
    default_analysis_type: Optional[str] = None,
    result_formatter: Optional[Callable[[AdapterResult], str]] = None
) -> Callable[[Dict[str, Any]], str]:
    """
    将 Adapter 类转换为工具函数

    Args:
        adapter_class: Adapter 类
        adapter_name: 适配器名称（用于日志）
        default_analysis_type: 默认分析类型
        result_formatter: 自定义结果格式化函数

    Returns:
        工具函数（需由调用者注册到 ToolRegistry）
    """

    def tool_function(context: Dict[str, Any]) -> str:
        """
        工具函数包装器

        Args:
            context: 包含所需数据的上下文字典

        Returns:
            格式化的工具输出字符串
        """
        logger.info(f"[AdapterWrapper] 执行适配器: {adapter_name}")

        try:
            adapter = adapter_class()
            kwargs = {}

            if default_analysis_type:
                kwargs["analysis_type"] = default_analysis_type

            # 使用循环提取已知键
            for key in KNOWN_CONTEXT_KEYS:
                if key in context:
                    kwargs[key] = context[key]

            result = adapter.run(**kwargs)

            if result_formatter:
                return result_formatter(result)
            else:
                return _default_format_result(result, adapter_name)

        except Exception as e:
            logger.error(f"[AdapterWrapper] 适配器执行失败: {adapter_name}, 错误: {e}")
            return f"## {adapter_name} 执行失败\n\n错误: {str(e)}"

    return tool_function


def _default_format_result(result: AdapterResult, adapter_name: str) -> str:
    """默认结果格式化函数"""
    if not result.success:
        return f"## {adapter_name} 执行失败\n\n错误: {result.error or '未知错误'}"

    lines = [f"## {adapter_name} 分析结果\n"]

    if result.metadata:
        lines.append("**分析参数:**")
        for key, value in result.metadata.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    if result.data:
        lines.append("**分析结果:**")
        for key, value in result.data.items():
            if isinstance(value, dict):
                lines.append(f"\n### {key}")
                for k, v in value.items():
                    lines.append(f"- {k}: {v}")
            elif isinstance(value, list):
                lines.append(f"\n### {key}")
                for item in value[:10]:
                    lines.append(f"- {item}")
                if len(value) > 10:
                    lines.append(f"- ... 共 {len(value)} 项")
            else:
                lines.append(f"- {key}: {value}")

    return "\n".join(lines)


# 预定义的格式化函数

def format_population_result(result: AdapterResult) -> str:
    """格式化人口预测结果"""
    if not result.success:
        return f"## 人口预测失败\n\n错误: {result.error or '未知错误'}"

    data = result.data
    lines = ["## 人口预测结果\n"]

    if "current_population" in data:
        lines.append(f"**当前人口:** {data['current_population']} 人\n")

    if "projections" in data:
        lines.append("**人口预测:**")
        for year, pop in data["projections"].items():
            lines.append(f"- {year}年: {pop} 人")
        lines.append("")

    if "structure" in data:
        lines.append("**人口结构:**")
        structure = data["structure"]
        lines.append(f"- 劳动年龄人口: {structure.get('working_age', 'N/A')}")
        lines.append(f"- 老年人口比例: {structure.get('elderly_ratio', 'N/A')}")
        lines.append(f"- 儿童人口比例: {structure.get('children_ratio', 'N/A')}")

    return "\n".join(lines)


def format_gis_result(result: AdapterResult) -> str:
    """格式化 GIS 分析结果"""
    if not result.success:
        return f"## GIS 分析失败\n\n错误: {result.error or '未知错误'}"

    data = result.data
    lines = ["## GIS 空间分析结果\n"]

    if "land_use" in data:
        lines.append("**土地利用结构:**")
        for land_type, ratio in data["land_use"].items():
            lines.append(f"- {land_type}: {ratio}%")
        lines.append("")

    if "coverage" in data:
        lines.append("**服务覆盖率:**")
        for service, coverage in data["coverage"].items():
            lines.append(f"- {service}: {coverage}%")

    return "\n".join(lines)


def format_network_result(result: AdapterResult) -> str:
    """格式化网络分析结果"""
    if not result.success:
        return f"## 网络分析失败\n\n错误: {result.error or '未知错误'}"

    data = result.data
    lines = ["## 交通网络分析结果\n"]

    if "accessibility" in data:
        lines.append("**可达性指标:**")
        acc = data["accessibility"]
        lines.append(f"- 平均出行时间: {acc.get('avg_travel_time', 'N/A')} 分钟")
        lines.append(f"- 最大出行时间: {acc.get('max_travel_time', 'N/A')} 分钟")
        lines.append("")

    if "connectivity" in data:
        lines.append("**连通性指标:**")
        conn = data["connectivity"]
        lines.append(f"- 道路密度: {conn.get('road_density', 'N/A')} km/km²")
        lines.append(f"- 连通度指数: {conn.get('connectivity_index', 'N/A')}")

    return "\n".join(lines)


def format_gis_fetch_result(result: AdapterResult) -> str:
    """格式化 GIS 数据获取结果"""
    if not result.success:
        return f"## GIS 数据获取失败\n\n错误: {result.error or '未知错误'}"

    data = result.data
    metadata = result.metadata
    lines = ["## GIS 数据获取结果\n"]

    source = metadata.get("source", "unknown")
    location = metadata.get("location", "unknown")
    lines.append(f"**数据来源:** {source}")
    lines.append(f"**目标位置:** {location}")

    if "crs" in metadata:
        lines.append(f"**坐标系:** {metadata['crs']}")

    if "count" in metadata:
        lines.append(f"**要素数量:** {metadata['count']}")
    if "nodes_count" in metadata:
        lines.append(f"**节点数量:** {metadata['nodes_count']}")
    if "edges_count" in metadata:
        lines.append(f"**边数量:** {metadata['edges_count']}")

    if "geometry_types" in metadata:
        geom_types = ", ".join(metadata["geometry_types"])
        lines.append(f"**几何类型:** {geom_types}")

    if "geojson" in data:
        geojson = data["geojson"]
        features = geojson.get("features", [])
        preview_count = min(3, len(features))
        if features:
            lines.append(f"\n**GeoJSON 预览 (前 {preview_count} 个要素):**")
            for i, f in enumerate(features[:preview_count]):
                props = f.get("properties", {})
                geom_type = f.get("geometry", {}).get("type", "unknown")
                name = props.get("name", props.get("id", "未命名"))
                lines.append(f"{i+1}. {name} ({geom_type})")

            if len(features) > preview_count:
                lines.append(f"... 共 {len(features)} 个要素")

    return "\n".join(lines)


def format_visualization_result(result: AdapterResult) -> str:
    """格式化可视化结果"""
    if not result.success:
        return f"## 可视化生成失败\n\n错误: {result.error or '未知错误'}"

    data = result.data
    metadata = result.metadata
    lines = ["## GIS 可视化结果\n"]

    format_type = data.get("format", "unknown")
    lines.append(f"**输出格式:** {format_type}")

    renderer = metadata.get("renderer", "unknown")
    lines.append(f"**渲染器:** {renderer}")

    if data.get("file_path"):
        lines.append(f"**输出文件:** {data['file_path']}")

    if data.get("content"):
        content = data["content"]
        lines.append(f"**HTML 长度:** {len(content)} 字符")

    if "center" in metadata:
        center = metadata["center"]
        lines.append(f"**地图中心:** [{center[0]:.4f}, {center[1]:.4f}]")
    if "zoom" in metadata:
        lines.append(f"**缩放级别:** {metadata['zoom']}")
    if "title" in metadata:
        lines.append(f"**图表标题:** {metadata['title']}")
    if "value_column" in metadata:
        lines.append(f"**分级字段:** {metadata['value_column']}")
    if "bins" in metadata:
        lines.append(f"**分级数量:** {metadata['bins']}")

    if format_type == "html":
        lines.append("\n**提示:** HTML 内容可直接嵌入网页展示交互式地图")
    elif format_type == "png":
        lines.append("\n**提示:** PNG 文件可用于报告嵌入或离线展示")

    return "\n".join(lines)


def format_accessibility_result(result: AdapterResult) -> str:
    """格式化可达性分析结果"""
    if not result.success:
        return f"## 可达性分析失败\n\n错误: {result.error or '未知错误'}"

    data = result.data
    metadata = result.metadata
    analysis_type = metadata.get("analysis_type", "unknown")
    lines = ["## 可达性分析结果\n"]

    lines.append(f"**分析类型:** {analysis_type}")
    lines.append(f"**数据来源:** {metadata.get('source', 'unknown')}")

    if "summary" in data:
        summary = data["summary"]
        lines.append("\n**分析汇总:**")
        lines.append(f"- 总目标数: {summary.get('total', 'N/A')}")
        lines.append(f"- 可达数量: {summary.get('reachable', 'N/A')}")
        lines.append(f"- 覆盖率: {summary.get('coverage_rate', 0) * 100:.1f}%")

    if "accessibility_matrix" in data:
        matrix = data["accessibility_matrix"]
        lines.append(f"\n**可达性矩阵 (共 {len(matrix)} 个目标):**")

        # 显示前 5 个
        for i, item in enumerate(matrix[:5]):
            dest = item.get("destination", "unknown")
            distance_km = item.get("distance_km", 0)
            time_min = item.get("time_minutes", 0)
            reachable = item.get("is_reachable", False)
            status = "✅ 可达" if reachable else "❌ 不可达"
            lines.append(f"{i+1}. 目标 {dest} - {distance_km:.2f}km, {time_min:.1f}分钟 {status}")

        if len(matrix) > 5:
            lines.append(f"... 共 {len(matrix)} 个目标")

    if "coverage_by_type" in data:
        coverage = data["coverage_by_type"]
        lines.append("\n**各类型覆盖情况:**")
        for poi_type, info in coverage.items():
            lines.append(f"- {poi_type}: 范围内 {info['in_range']} 个 (半径 {info['radius']}m)")

    return "\n".join(lines)


def format_poi_result(result: AdapterResult) -> str:
    """格式化 POI 搜索结果"""
    if not result.success:
        return f"## POI 搜索失败\n\n错误: {result.error or '未知错误'}"

    data = result.data
    metadata = result.metadata
    lines = ["## POI 搜索结果\n"]

    keyword = metadata.get("keyword", "unknown")
    total = metadata.get("total_count", 0)
    lines.append(f"**搜索关键词:** {keyword}")
    lines.append(f"**数据来源:** {metadata.get('source', 'unknown')}")

    if "pois" in data:
        pois = data["pois"]
        lines.append(f"\n**找到 {len(pois)} 个 POI (总数量: {total}):**")

        for i, poi in enumerate(pois[:10]):
            name = poi.get("name", "未命名")
            address = poi.get("address", "")
            distance = poi.get("distance")
            category = poi.get("category", "")

            if distance:
                lines.append(f"{i+1}. {name} ({category}) - {distance:.0f}m")
            else:
                lines.append(f"{i+1}. {name} ({category})")
            if address:
                lines.append(f"   地址: {address}")

        if len(pois) > 10:
            lines.append(f"... 共 {len(pois)} 个 POI")

    if "geojson" in data:
        geojson = data["geojson"]
        features = geojson.get("features", [])
        lines.append(f"\n**GeoJSON 数据:** {len(features)} 个要素")

    return "\n".join(lines)


__all__ = [
    "create_adapter_tool_function",
    "format_population_result",
    "format_gis_result",
    "format_network_result",
    "format_gis_fetch_result",
    "format_visualization_result",
    "format_accessibility_result",
    "format_poi_result",
]