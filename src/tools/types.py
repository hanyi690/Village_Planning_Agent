"""
GIS 工具返回值类型定义和规范化函数

解决工具返回值类型不统一问题：
- population_model_v1 等工具返回 Markdown 文本字符串
- gis_tool_wrappers 中工具返回 JSON 字符串（解析后为 dict）

通过规范化层统一处理，下游代码无需关心类型差异。
"""

from typing import TypedDict, Any, Optional, Union, List, Tuple, Dict
from dataclasses import dataclass, field
from enum import Enum
import json

from ..utils.logger import get_logger

logger = get_logger(__name__)


# Module-level constant: layer styles mapping for category extraction
# Avoid recreation overhead on every function call
LAYER_STYLES = {
    "water": {
        "color": "#87CEEB",
        "layerType": "sensitivity_zone",
        "layerName": "水系",
        "default_props": {"sensitivity_level": "中敏感区"},
    },
    "road": {
        "color": "#FF6B6B",
        "layerType": "development_axis",
        "layerName": "道路",
        "default_props": {"axis_type": "交通主轴"},
    },
    "residential": {
        "color": "#FFD700",
        "layerType": "function_zone",
        "layerName": "居民地",
        "default_props": {"zone_type": "居住用地"},
    },
}


class ResultDataType(str, Enum):
    """结果数据类型"""
    GEOJSON = "geojson"      # GIS 图层数据
    ANALYSIS = "analysis"    # 分析结果 dict
    TEXT = "text"            # Markdown/纯文本
    ERROR = "error"          # 错误结果


@dataclass
class NormalizedToolResult:
    """规范化后的工具结果 - 统一访问接口"""
    success: bool
    data_type: ResultDataType
    raw_data: Dict[str, Any] = field(default_factory=dict)

    # 根据类型提取的核心数据
    geojson_data: Optional[Dict] = None
    layers_data: Optional[List[Dict]] = None
    analysis_data: Optional[Dict] = None
    text_data: Optional[str] = None

    # 元数据
    center: Optional[Tuple[float, float]] = None
    error: Optional[str] = None
    location: Optional[str] = None

    @property
    def has_geojson(self) -> bool:
        """是否有 GeoJSON 图层数据"""
        return self.geojson_data is not None or self.layers_data is not None

    @property
    def has_text(self) -> bool:
        """是否有文本数据"""
        return self.text_data is not None

    @property
    def has_analysis(self) -> bool:
        """是否有分析结果"""
        return self.analysis_data is not None

    def get(self, key: str, default: Any = None) -> Any:
        """向后兼容：模拟 dict.get() 行为"""
        return self.raw_data.get(key, default)


def normalize_tool_result(
    raw_result: Union[str, Dict, None],
    tool_name: str = None
) -> NormalizedToolResult:
    """
    规范化工具返回值

    Args:
        raw_result: 工具原始返回值（字符串或 dict）
        tool_name: 工具名称（用于日志）

    Returns:
        NormalizedToolResult 实例
    """
    if raw_result is None:
        return NormalizedToolResult(
            success=False,
            data_type=ResultDataType.ERROR,
            error="工具返回空结果"
        )

    # 1. 字符串类型处理
    if isinstance(raw_result, str):
        # 尝试解析为 JSON
        try:
            parsed = json.loads(raw_result)
            return _normalize_dict_result(parsed, tool_name)
        except json.JSONDecodeError:
            # 非 JSON 字符串，作为文本处理
            logger.debug(f"[规范化] {tool_name}: 纯文本结果，长度 {len(raw_result)}")
            return NormalizedToolResult(
                success=True,
                data_type=ResultDataType.TEXT,
                raw_data={"success": True, "data": raw_result},
                text_data=raw_result
            )

    # 2. Dict 类型处理
    if isinstance(raw_result, dict):
        return _normalize_dict_result(raw_result, tool_name)

    # 3. 其他类型（未知）
    logger.warning(f"[规范化] {tool_name}: 未知类型 {type(raw_result).__name__}")
    return NormalizedToolResult(
        success=False,
        data_type=ResultDataType.ERROR,
        error=f"未知返回类型: {type(raw_result).__name__}",
        raw_data={"success": False, "error": f"未知返回类型"}
    )


def _normalize_dict_result(
    result: Dict[str, Any],
    tool_name: str = None
) -> NormalizedToolResult:
    """
    规范化 dict 类型的结果

    Args:
        result: 已解析的 dict 结果
        tool_name: 工具名称

    Returns:
        NormalizedToolResult 实例
    """
    # 检查成功标志
    success = result.get("success", False)

    if not success:
        return NormalizedToolResult(
            success=False,
            data_type=ResultDataType.ERROR,
            error=result.get("error", "未知错误"),
            raw_data=result
        )

    # 提取各类数据
    geojson_data = None
    layers_data = None
    analysis_data = None
    text_data = None
    center = None
    location = None

    # 1. 顶层 geojson/layers
    if result.get("geojson"):
        geojson_data = result["geojson"]
        features = geojson_data.get("features", [])
        if features:
            layers_data = [{
                "geojson": geojson_data,
                "layerType": result.get("layer_type", "analysis"),
                "layerName": result.get("layer_name", "分析结果"),
            }]
    elif result.get("layers"):
        layers_data = result["layers"]

    # 2. 嵌套 data 字段
    data_field = result.get("data")
    if data_field is not None:
        # 类型安全检查
        if isinstance(data_field, str):
            # data 字段是字符串（如 population_model_v1）
            text_data = data_field
        elif isinstance(data_field, dict):
            # 从嵌套 data 提取 geojson
            if not layers_data and data_field.get("geojson"):
                nested_geojson = data_field["geojson"]
                features = nested_geojson.get("features", [])
                if features:
                    layers_data = [{
                        "geojson": nested_geojson,
                        "layerType": data_field.get("layer_type", "analysis"),
                        "layerName": data_field.get("layer_name", "分析结果"),
                    }]

            # 从嵌套 data 提取各类别图层（water/road/residential）
            if not layers_data:
                layers_data = _extract_category_layers(data_field)

            # 提取 summary 等分析数据
            if data_field.get("summary"):
                analysis_data = {"summary": data_field["summary"]}

    # 3. 分析数据字段（顶层）
    analysis_keys = ["overall_score", "suitability_level", "sensitivity_class",
                     "recommendations", "summary", "coverage_rate", "reachable_count"]
    if not analysis_data:
        extracted = {}
        for key in analysis_keys:
            if result.get(key) is not None:
                extracted[key] = result[key]
        if extracted:
            analysis_data = extracted

    # 4. 元数据提取
    center = _extract_center(result)
    location = result.get("location")

    # 5. 确定数据类型
    if layers_data or geojson_data:
        data_type = ResultDataType.GEOJSON
    elif analysis_data:
        data_type = ResultDataType.ANALYSIS
    elif text_data:
        data_type = ResultDataType.TEXT
    else:
        data_type = ResultDataType.ANALYSIS  # 默认为分析类型

    logger.debug(f"[规范化] {tool_name}: 类型={data_type.value}, "
                 f"图层={len(layers_data or [])}, 文本={len(text_data or '')}")

    return NormalizedToolResult(
        success=True,
        data_type=data_type,
        raw_data=result,
        geojson_data=geojson_data,
        layers_data=layers_data,
        analysis_data=analysis_data,
        text_data=text_data,
        center=center,
        location=location
    )


def _extract_category_layers(data: Dict[str, Any]) -> Optional[List[Dict]]:
    """
    从嵌套 data 提取各类别图层（water/road/residential）

    Args:
        data: 嵌套的 data 字段

    Returns:
        图层列表或 None
    """
    layers = []

    for category, style in LAYER_STYLES.items():
        cat_data = data.get(category, {})
        # 类型安全检查
        if not isinstance(cat_data, dict):
            continue
        if cat_data.get("success") and cat_data.get("geojson"):
            geojson = cat_data["geojson"]
            features = geojson.get("features", [])
            if features:
                # 为每个要素注入默认分类属性
                for feature in features:
                    props = feature.get("properties", {})
                    if not isinstance(props, dict):
                        props = {}
                    for k, v in style["default_props"].items():
                        if k not in props:
                            props[k] = v
                    feature["properties"] = props

                layers.append({
                    "geojson": geojson,
                    "color": style["color"],
                    "layerType": style["layerType"],
                    "layerName": style["layerName"],
                })

    return layers if layers else None


def _extract_center(result: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """
    提取中心点坐标

    Args:
        result: 原始结果

    Returns:
        中心点坐标元组或 None
    """
    center = result.get("center")
    if center is None:
        # 尝试从嵌套 data 提取
        data_field = result.get("data")
        if isinstance(data_field, dict):
            center = data_field.get("center")

    if center is None:
        return None

    # 转换为 tuple
    if isinstance(center, list) and len(center) == 2:
        return tuple(center)
    if isinstance(center, tuple):
        return center

    return None


def safe_get_nested(data: Any, keys: List[str], default: Any = None) -> Any:
    """
    安全嵌套访问 - 避免链式 .get()

    Args:
        data: 数据（可能是 dict 或其他类型）
        keys: 键路径列表
        default: 默认值

    Returns:
        找到的值或默认值

    Example:
        safe_get_nested(result, ["data", "water", "geojson"])
    """
    if not isinstance(data, dict):
        return default

    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default

    return current


__all__ = [
    "ResultDataType",
    "NormalizedToolResult",
    "normalize_tool_result",
    "safe_get_nested",
]