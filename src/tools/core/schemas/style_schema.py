"""
Style Schema - 图层样式定义

从统一配置 src/config/gis_styles.py 导入样式定义。
提供 GIS 图层样式配置的统一入口。

注意: 样式定义已统一到 src/config/gis_styles.py，
此处仅为 schemas 模块的便捷导入入口。
"""

# 从统一配置导入所有样式相关定义
from src.config.gis_styles import (
    PLANNING_STYLES,
    LAYER_GEOMETRY_TYPES,
    get_style_for_layer,
    get_style_for_feature,
    export_styles_json,
    export_legend_json,
    get_all_layer_types,
    get_geometry_type,
    FillStyle,
    LineStyle,
    MarkerStyle,
)

__all__ = [
    'PLANNING_STYLES',
    'LAYER_GEOMETRY_TYPES',
    'get_style_for_layer',
    'get_style_for_feature',
    'export_styles_json',
    'export_legend_json',
    'get_all_layer_types',
    'get_geometry_type',
    'FillStyle',
    'LineStyle',
    'MarkerStyle',
]