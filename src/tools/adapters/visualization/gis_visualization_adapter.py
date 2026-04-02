"""
GIS 可视化适配器

自动生成交互地图、分级统计图等可视化输出。
支持 folium（交互地图）和 matplotlib（静态图表）渲染器。

参考设计：docs/references/geopandas-ai
- 分析数据特征
- LLM 生成可视化代码
- 代码执行失败自动重试修复
"""

from typing import Dict, Any, Optional, Type
from dataclasses import dataclass
import json
import traceback
import tempfile
import os

from ..base_adapter import BaseAdapter, AdapterResult, AdapterStatus
from ....utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 可视化结果类型
# ==========================================

@dataclass
class VisualizationResult:
    """可视化结果"""
    success: bool
    format: str  # html/png/json
    metadata: Dict[str, Any]
    content: Optional[str] = None  # HTML内容或PNG路径
    file_path: Optional[str] = None
    error: Optional[str] = None


# ==========================================
# 渲染器基类
# ==========================================

class BaseRenderer:
    """渲染器基类"""

    def __init__(self):
        self._available = False
        self._check_dependencies()

    def _check_dependencies(self):
        """检查依赖"""
        pass

    def is_available(self) -> bool:
        """检查是否可用"""
        return self._available

    def render(self, data: Dict, **kwargs) -> VisualizationResult:
        """渲染数据"""
        raise NotImplementedError


# ==========================================
# Folium 渲染器
# ==========================================

# 国内可用的地图瓦片源
TILE_SOURCES = {
    # OpenStreetMap 官方瓦片（国内可能不稳定）
    "openstreetmap": {
        "tiles": "OpenStreetMap",
        "attr": "OpenStreetMap contributors"
    },
    # GeoQ ArcGIS 在线地图（国内稳定）
    "geoq": {
        "tiles": "https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}",
        "attr": "GeoQ ArcGIS"
    },
    # GeoQ 彩色版
    "geoq_color": {
        "tiles": "https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineStreetColor/MapServer/tile/{z}/{y}/{x}",
        "attr": "GeoQ ArcGIS Color"
    },
    # GeoQ 灰色版（适合叠加数据）
    "geoq_gray": {
        "tiles": "https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineStreetGray/MapServer/tile/{z}/{y}/{x}",
        "attr": "GeoQ ArcGIS Gray"
    },
    # 高德地图（需要授权）
    "gaode": {
        "tiles": "https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        "attr": "Gaode Maps"
    },
    # 天地图（需要申请 API Key）
    "tianditu_vec": {
        "tiles": "https://t{s}.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk={tk}",
        "attr": "Tianditu"
    },
}


class FoliumRenderer(BaseRenderer):
    """
    Folium 交互地图渲染器

    生成交互式 HTML 地图，支持：
    - 基础地图
    - 标记点
    - GeoJSON 图层
    - 分级统计图
    - 热力图
    """

    def _check_dependencies(self):
        """检查依赖"""
        try:
            import folium
            self._available = True
            logger.info("[FoliumRenderer] folium 可用")
        except ImportError:
            logger.warning("[FoliumRenderer] folium 不可用，请安装: pip install folium")

    def _get_tiles_config(self, tiles: Optional[str] = None) -> Dict[str, Any]:
        """
        获取瓦片配置

        Args:
            tiles: 瓦片源名称或 URL，如 "geoq"、"openstreetmap" 或自定义 URL

        Returns:
            瓦片配置字典，包含 tiles URL 和 attr
        """
        # 尝试从项目配置读取默认瓦片源
        default_tile_source = "geoq"  # 默认使用国内瓦片
        try:
            from ....core.config import GIS_TILE_SOURCE
            default_tile_source = GIS_TILE_SOURCE
        except ImportError:
            pass

        # 如果未指定，使用默认值
        if not tiles:
            tiles = default_tile_source

        # 检查是否是预定义的瓦片源名称
        if tiles in TILE_SOURCES:
            config = TILE_SOURCES[tiles].copy()  # 复制以避免修改原始配置

            # 处理天地图 API Key 替换
            tiles_url = config.get("tiles", "")
            if "{tk}" in tiles_url:
                # 获取天地图 API Key
                try:
                    from ....core.config import TIANDITU_API_KEY
                    api_key = TIANDITU_API_KEY
                except ImportError:
                    import os
                    api_key = os.environ.get("TIANDITU_API_KEY", "")

                if api_key:
                    config["tiles"] = tiles_url.replace("{tk}", api_key)
                    logger.info(f"[FoliumRenderer] 天地图瓦片已配置 API Key")
                else:
                    # 未配置 API Key，降级到其他瓦片
                    logger.warning("[FoliumRenderer] 天地图 API Key 未配置，降级到 GeoQ 瓦片")
                    config = TILE_SOURCES.get("geoq", TILE_SOURCES["openstreetmap"])

            return {
                "tiles": config["tiles"],
                "attr": config["attr"],
                "use_custom": True
            }

        # 检查是否是 folium 内置样式名
        builtin_tiles = ["OpenStreetMap", "Stamen Terrain", "Stamen Toner",
                         "Stamen Watercolor", "CartoDB positron", "CartoDB dark_matter"]
        if tiles in builtin_tiles:
            return {
                "tiles": tiles,
                "attr": "",
                "use_custom": False
            }

        # 自定义 URL
        if tiles.startswith("http"):
            # 处理自定义 URL 中的 API Key 占位符
            if "{tk}" in tiles:
                try:
                    from ....core.config import TIANDITU_API_KEY
                    api_key = TIANDITU_API_KEY
                except ImportError:
                    import os
                    api_key = os.environ.get("TIANDITU_API_KEY", "")

                if api_key:
                    tiles = tiles.replace("{tk}", api_key)
                else:
                    logger.warning("[FoliumRenderer] 自定义瓦片需要 API Key 但未配置")

            return {
                "tiles": tiles,
                "attr": "Custom Tiles",
                "use_custom": True
            }

        # 未知类型，使用默认瓦片
        logger.warning(f"[FoliumRenderer] 未知的瓦片源 '{tiles}'，使用默认瓦片")
        config = TILE_SOURCES.get(default_tile_source, TILE_SOURCES["geoq"])
        return {
            "tiles": config["tiles"],
            "attr": config["attr"],
            "use_custom": True
        }

    def render(self, data: Dict, **kwargs) -> VisualizationResult:
        """
        渲染交互地图

        Args:
            data: 包含 geojson 或 features 的数据
            **kwargs:
                - location: 地图中心坐标 [lat, lon]
                - zoom_start: 初始缩放级别
                - tiles: 地图底图样式
                - style_function: 样式函数配置
        """
        if not self._available:
            return VisualizationResult(
                success=False,
                format="html",
                content=None,
                metadata={},
                error="folium 库不可用。请安装: pip install folium"
            )

        try:
            import folium

            # 获取 GeoJSON 数据
            geojson = data.get("geojson", data)

            # 计算地图中心
            center = self._calculate_center(geojson)
            location = kwargs.get("location", center)
            zoom_start = kwargs.get("zoom_start", 10)

            # 获取瓦片配置
            tiles_config = self._get_tiles_config(kwargs.get("tiles"))

            # 创建地图
            if tiles_config.get("use_custom"):
                # 使用自定义瓦片 URL
                m = folium.Map(
                    location=location,
                    zoom_start=zoom_start,
                    tiles=tiles_config["tiles"],
                    attr=tiles_config.get("attr", "")
                )
            else:
                # 使用内置瓦片样式
                m = folium.Map(
                    location=location,
                    zoom_start=zoom_start,
                    tiles=tiles_config["tiles"]
                )

            # 添加 GeoJSON 图层
            if geojson:
                style_function = kwargs.get("style_function", self._default_style())

                # 检查是否有可用的 tooltip 字段
                tooltip_fields = ['name', 'type'] if self._has_fields(geojson, ['name', 'type']) else None

                geojson_layer = folium.GeoJson(
                    geojson,
                    style_function=style_function
                )

                # 只有当有可用字段时才添加 tooltip
                if tooltip_fields:
                    geojson_layer.add_child(folium.GeoJsonTooltip(fields=tooltip_fields))

                geojson_layer.add_to(m)

            # 保存 HTML
            html_content = m.get_root().render()

            return VisualizationResult(
                success=True,
                format="html",
                content=html_content,
                metadata={
                    "renderer": "folium",
                    "center": location,
                    "zoom": zoom_start,
                    "tiles": tiles_config.get("tiles", "unknown")
                }
            )

        except Exception as e:
            logger.error(f"[FoliumRenderer] 渲染失败: {e}")
            return VisualizationResult(
                success=False,
                format="html",
                content=None,
                metadata={},
                error=f"渲染失败: {str(e)}"
            )

    def _calculate_center(self, geojson: Dict) -> list:
        """计算 GeoJSON 的中心坐标"""
        try:
            import geopandas as gpd

            gdf = gpd.read_file(json.dumps(geojson), driver="GeoJSON")
            centroid = gdf.geometry.union_all().centroid
            return [centroid.y, centroid.x]
        except Exception:
            # 默认中心（中国）
            return [30.0, 120.0]

    def _has_fields(self, geojson: Dict, fields: list) -> bool:
        """检查 GeoJSON 是否包含指定字段"""
        features = geojson.get("features", [])
        if not features:
            return False
        props = features[0].get("properties", {})
        return all(f in props for f in fields)

    def _default_style(self) -> callable:
        """默认样式函数"""
        def style(feature):
            return {
                'fillColor': '#3186cc',
                'color': '#3186cc',
                'weight': 2,
                'fillOpacity': 0.5
            }
        return style

    def render_choropleth(
        self,
        geojson: Dict,
        value_column: str,
        **kwargs
    ) -> VisualizationResult:
        """
        渲染分级统计图

        Args:
            geojson: GeoJSON 数据
            value_column: 数值字段名
            **kwargs:
                - key_on: 关联字段
                - fill_color: 颜色方案
                - bins: 分级数量
        """
        if not self._available:
            return VisualizationResult(
                success=False,
                format="html",
                content=None,
                metadata={},
                error="folium 库不可用"
            )

        try:
            import folium

            center = self._calculate_center(geojson)
            location = kwargs.get("location", center)
            zoom_start = kwargs.get("zoom_start", 10)

            # 获取瓦片配置
            tiles_config = self._get_tiles_config(kwargs.get("tiles"))

            # 创建地图
            if tiles_config.get("use_custom"):
                m = folium.Map(
                    location=location,
                    zoom_start=zoom_start,
                    tiles=tiles_config["tiles"],
                    attr=tiles_config.get("attr", "")
                )
            else:
                m = folium.Map(location=location, zoom_start=zoom_start, tiles=tiles_config["tiles"])

            # 分级统计图
            key_on = kwargs.get("key_on", "feature.properties.name")
            fill_color = kwargs.get("fill_color", "YlOrRd")
            bins = kwargs.get("bins", 5)

            folium.Choropleth(
                geo_data=geojson,
                data=self._extract_values(geojson, value_column),
                columns=["name", value_column],
                key_on=key_on,
                fill_color=fill_color,
                bins=bins,
                fill_opacity=0.7,
                line_opacity=0.2,
                legend_name=value_column
            ).add_to(m)

            html_content = m.get_root().render()

            return VisualizationResult(
                success=True,
                format="html",
                content=html_content,
                metadata={
                    "renderer": "folium.choropleth",
                    "value_column": value_column,
                    "bins": bins,
                    "color_scheme": fill_color
                }
            )

        except Exception as e:
            logger.error(f"[FoliumRenderer] 分级统计图渲染失败: {e}")
            return VisualizationResult(
                success=False,
                format="html",
                content=None,
                metadata={},
                error=f"分级统计图渲染失败: {str(e)}"
            )

    def _extract_values(self, geojson: Dict, value_column: str) -> list:
        """提取数值用于分级统计"""
        features = geojson.get("features", [])
        values = []
        for f in features:
            props = f.get("properties", {})
            name = props.get("name", f.get("id", "unknown"))
            value = props.get(value_column, 0)
            values.append([name, value])
        return values

    def render_heatmap(
        self,
        points: list,
        **kwargs
    ) -> VisualizationResult:
        """
        渲染热力图

        Args:
            points: [[lat, lon, weight], ...] 点位列表
            **kwargs:
                - radius: 热力半径
                - max_zoom: 最大缩放
        """
        if not self._available:
            return VisualizationResult(
                success=False,
                format="html",
                content=None,
                metadata={},
                error="folium 库不可用"
            )

        try:
            import folium
            from folium.plugins import HeatMap

            # 计算中心
            if points:
                center = [sum(p[0] for p in points) / len(points),
                          sum(p[1] for p in points) / len(points)]
            else:
                center = [30.0, 120.0]

            # 获取瓦片配置
            tiles_config = self._get_tiles_config(kwargs.get("tiles"))

            # 创建地图
            if tiles_config.get("use_custom"):
                m = folium.Map(
                    location=center,
                    zoom_start=kwargs.get("zoom_start", 12),
                    tiles=tiles_config["tiles"],
                    attr=tiles_config.get("attr", "")
                )
            else:
                m = folium.Map(
                    location=center,
                    zoom_start=kwargs.get("zoom_start", 12),
                    tiles=tiles_config["tiles"]
                )

            HeatMap(
                points,
                radius=kwargs.get("radius", 15),
                max_zoom=kwargs.get("max_zoom", 13)
            ).add_to(m)

            html_content = m.get_root().render()

            return VisualizationResult(
                success=True,
                format="html",
                content=html_content,
                metadata={
                    "renderer": "folium.heatmap",
                    "points_count": len(points),
                    "radius": kwargs.get("radius", 15)
                }
            )

        except Exception as e:
            logger.error(f"[FoliumRenderer] 热力图渲染失败: {e}")
            return VisualizationResult(
                success=False,
                format="html",
                content=None,
                metadata={},
                error=f"热力图渲染失败: {str(e)}"
            )


# ==========================================
# Matplotlib 渲染器
# ==========================================

class MatplotlibRenderer(BaseRenderer):
    """
    Matplotlib 静态图表渲染器

    生成 PNG 静态图表，支持：
    - 地理要素渲染
    - 分级统计图
    - 多图层叠加
    """

    def _check_dependencies(self):
        """检查依赖"""
        try:
            import matplotlib
            import matplotlib.pyplot as plt
            self._available = True
            logger.info("[MatplotlibRenderer] matplotlib 可用")
        except ImportError:
            logger.warning("[MatplotlibRenderer] matplotlib 不可用，请安装: pip install matplotlib")

    def render(self, data: Dict, **kwargs) -> VisualizationResult:
        """
        渲染静态地图

        Args:
            data: 包含 geojson 的数据
            **kwargs:
                - title: 图表标题
                - figsize: 图表尺寸
                - color_scheme: 颜色方案
                - save_path: 保存路径
        """
        if not self._available:
            return VisualizationResult(
                success=False,
                format="png",
                content=None,
                metadata={},
                error="matplotlib 库不可用。请安装: pip install matplotlib"
            )

        try:
            import matplotlib.pyplot as plt
            import geopandas as gpd

            # 获取 GeoJSON 数据
            geojson = data.get("geojson", data)

            # 转换为 GeoDataFrame
            gdf = gpd.read_file(json.dumps(geojson), driver="GeoJSON")

            # 创建图表
            figsize = kwargs.get("figsize", (10, 10))
            fig, ax = plt.subplots(figsize=figsize)

            # 渲染地理要素
            column = kwargs.get("column")
            if column and column in gdf.columns:
                # 分级统计图
                cmap = kwargs.get("cmap", "viridis")
                gdf.plot(column=column, cmap=cmap, legend=True, ax=ax)
            else:
                # 单色渲染
                color = kwargs.get("color", "#3186cc")
                gdf.plot(color=color, ax=ax)

            # 设置标题
            title = kwargs.get("title", "GIS Visualization")
            ax.set_title(title)

            # 保存图表
            save_path = kwargs.get("save_path")
            if not save_path:
                # 使用临时目录
                temp_dir = tempfile.gettempdir()
                save_path = os.path.join(temp_dir, "gis_visualization.png")

            plt.savefig(save_path, dpi=kwargs.get("dpi", 150), bbox_inches='tight')
            plt.close()

            return VisualizationResult(
                success=True,
                format="png",
                content=None,
                file_path=save_path,
                metadata={
                    "renderer": "matplotlib",
                    "title": title,
                    "figsize": figsize,
                    "dpi": kwargs.get("dpi", 150)
                }
            )

        except Exception as e:
            logger.error(f"[MatplotlibRenderer] 渲染失败: {e}")
            return VisualizationResult(
                success=False,
                format="png",
                content=None,
                metadata={},
                error=f"渲染失败: {str(e)}"
            )


# ==========================================
# GIS 可视化适配器
# ==========================================

class GISVisualizationAdapter(BaseAdapter):
    """
    GIS 可视化适配器

    支持的分析类型：
    1. interactive_map - 交互式地图（folium）
    2. choropleth - 分级统计图
    3. heatmap - 热力图
    4. static_map - 静态图表（matplotlib）
    5. smart_visualize - 智能可视化（自动选择最佳方式）

    输出格式：
    - HTML（交互地图）
    - PNG（静态图表）
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化适配器"""
        # 先设置默认值，再调用 super().__init__() 避免 validate_dependencies 创建的渲染器被覆盖
        self._folium_renderer: Optional[FoliumRenderer] = None
        self._matplotlib_renderer: Optional[MatplotlibRenderer] = None
        self._max_retries = 5

        # 调用父类初始化，这会调用 validate_dependencies() 创建渲染器
        super().__init__(config)

        # 从配置中读取 max_retries（如果有的话）
        self._max_retries = self.config.get("max_retries", 5)

    def validate_dependencies(self) -> bool:
        """验证外部依赖是否可用"""
        try:
            # 检查核心依赖
            import geopandas
            import shapely

            # 初始化渲染器
            self._folium_renderer = FoliumRenderer()
            self._matplotlib_renderer = MatplotlibRenderer()

            logger.info("[GISVisualizationAdapter] 核心依赖可用")
            return True

        except ImportError as e:
            logger.warning(f"[GISVisualizationAdapter] 核心依赖不可用: {e}")
            return False

    def initialize(self) -> bool:
        """初始化适配器"""
        try:
            # 检查渲染器可用性
            folium_available = self._folium_renderer and self._folium_renderer.is_available()
            matplotlib_available = self._matplotlib_renderer and self._matplotlib_renderer.is_available()

            if not folium_available and not matplotlib_available:
                logger.warning("[GISVisualizationAdapter] 所有渲染器不可用，可视化将失败")
                self._error_message = "所有渲染器不可用"
                # 状态已在 validate_dependencies 中设置为 READY，保持不变
                # 但返回 True 以允许尝试执行

            self._status = AdapterStatus.READY
            logger.info(f"[GISVisualizationAdapter] 渲染器状态: folium={folium_available}, matplotlib={matplotlib_available}")
            return True

        except Exception as e:
            self._error_message = f"初始化失败: {str(e)}"
            logger.error(f"[GISVisualizationAdapter] {self._error_message}")
            return False

    def execute(
        self,
        analysis_type: str = "interactive_map",
        **kwargs
    ) -> AdapterResult:
        """
        执行 GIS 可视化

        Args:
            analysis_type: 分析类型
                - interactive_map: 交互式地图
                - choropleth: 分级统计图
                - heatmap: 热力图
                - static_map: 静态图表
                - smart_visualize: 智能可视化

            **kwargs: 参数
                - data/geojson: GeoJSON 数据
                - location: 地图中心
                - zoom_start: 缩放级别
                - value_column: 分级字段（choropleth）
                - points: 热力点数据（heatmap）
                - title: 图表标题
                - figsize: 图表尺寸

        Returns:
            AdapterResult: 包含可视化结果
        """
        logger.info(f"[GISVisualizationAdapter] 执行: {analysis_type}")

        if analysis_type == "interactive_map":
            return self._render_interactive_map(**kwargs)
        elif analysis_type == "choropleth":
            return self._render_choropleth(**kwargs)
        elif analysis_type == "heatmap":
            return self._render_heatmap(**kwargs)
        elif analysis_type == "static_map":
            return self._render_static_map(**kwargs)
        elif analysis_type == "smart_visualize":
            return self._smart_visualize(**kwargs)
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"不支持的分析类型: {analysis_type}"
            )

    def get_schema(self) -> Dict[str, Any]:
        """获取输出 Schema"""
        return {
            "adapter_name": "GISVisualizationAdapter",
            "supported_analyses": [
                "interactive_map",
                "choropleth",
                "heatmap",
                "static_map",
                "smart_visualize"
            ],
            "output_schema": {
                "format": "string (html/png)",
                "content": "string (HTML content)",
                "file_path": "string (PNG path)",
                "metadata": {
                    "renderer": "string",
                    "center": "array",
                    "zoom": "number"
                }
            }
        }

    # ==========================================
    # 具体渲染方法
    # ==========================================

    def _render_interactive_map(self, **kwargs) -> AdapterResult:
        """渲染交互式地图"""
        data = kwargs.get("data", kwargs.get("geojson"))

        if not data:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 data 或 geojson 参数"
            )

        if not self._folium_renderer or not self._folium_renderer.is_available():
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="Folium 渲染器不可用。请安装: pip install folium"
            )

        # 移除可能导致重复参数的键
        render_kwargs = {k: v for k, v in kwargs.items() if k not in ("data", "geojson")}
        result = self._folium_renderer.render(data, **render_kwargs)

        if result.success:
            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data={
                    "format": result.format,
                    "content": result.content,
                    "file_path": result.file_path
                },
                metadata=result.metadata
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=result.error
            )

    def _render_choropleth(self, **kwargs) -> AdapterResult:
        """渲染分级统计图"""
        geojson = kwargs.get("geojson", kwargs.get("data"))
        value_column = kwargs.get("value_column")

        if not geojson:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 geojson 参数"
            )

        if not value_column:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 value_column 参数"
            )

        if not self._folium_renderer or not self._folium_renderer.is_available():
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="Folium 渲染器不可用"
            )

        result = self._folium_renderer.render_choropleth(geojson, value_column, **kwargs)

        if result.success:
            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data={
                    "format": result.format,
                    "content": result.content,
                    "file_path": result.file_path
                },
                metadata=result.metadata
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=result.error
            )

    def _render_heatmap(self, **kwargs) -> AdapterResult:
        """渲染热力图"""
        points = kwargs.get("points")

        if not points:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 points 参数"
            )

        if not self._folium_renderer or not self._folium_renderer.is_available():
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="Folium 渲染器不可用"
            )

        # 移除可能导致重复参数的键
        render_kwargs = {k: v for k, v in kwargs.items() if k not in ("points",)}
        result = self._folium_renderer.render_heatmap(points, **render_kwargs)

        if result.success:
            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data={
                    "format": result.format,
                    "content": result.content,
                    "file_path": result.file_path
                },
                metadata=result.metadata
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=result.error
            )

    def _render_static_map(self, **kwargs) -> AdapterResult:
        """渲染静态图表"""
        data = kwargs.get("data", kwargs.get("geojson"))

        if not data:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 data 或 geojson 参数"
            )

        if not self._matplotlib_renderer or not self._matplotlib_renderer.is_available():
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="Matplotlib 渲染器不可用。请安装: pip install matplotlib"
            )

        # 移除可能导致重复参数的键
        render_kwargs = {k: v for k, v in kwargs.items() if k not in ("data", "geojson")}
        result = self._matplotlib_renderer.render(data, **render_kwargs)

        if result.success:
            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data={
                    "format": result.format,
                    "content": result.content,
                    "file_path": result.file_path
                },
                metadata=result.metadata
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=result.error
            )

    # ==========================================
    # Smart Visualize - 智能可视化
    # ==========================================

    def _smart_visualize(self, **kwargs) -> AdapterResult:
        """
        智能可视化

        分析数据特征，自动选择最佳可视化方式：
        1. 分析 GeoJSON 数据结构
        2. 确定可视化类型
        3. 生成可视化代码
        4. 执行并返回结果
        """
        data = kwargs.get("data", kwargs.get("geojson"))
        prompt = kwargs.get("prompt", "")

        if not data:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 data 或 geojson 参数"
            )

        # 分析数据特征
        data_analysis = self._analyze_data_characteristics(data)

        logger.info(f"[GISVisualizationAdapter] 数据分析: {data_analysis}")

        # 确定最佳可视化方式
        viz_type = self._determine_visualization_type(data_analysis, prompt)

        logger.info(f"[GISVisualizationAdapter] 选择可视化类型: {viz_type}")

        # 执行对应可视化，先移除可能冲突的参数
        clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("data", "geojson", "prompt")}

        if viz_type == "interactive_map":
            return self._render_interactive_map(data=data, **clean_kwargs)
        elif viz_type == "choropleth":
            # 自动查找数值字段
            value_column = self._find_value_column(data)
            if value_column:
                return self._render_choropleth(geojson=data, value_column=value_column, **clean_kwargs)
            else:
                return self._render_interactive_map(data=data, **clean_kwargs)
        elif viz_type == "heatmap":
            points = self._extract_points_from_geojson(data)
            if points:
                return self._render_heatmap(points=points, **clean_kwargs)
            else:
                return self._render_interactive_map(data=data, **clean_kwargs)
        elif viz_type == "static_map":
            return self._render_static_map(data=data, **clean_kwargs)
        else:
            return self._render_interactive_map(data=data, **clean_kwargs)

    def _analyze_data_characteristics(self, data: Dict) -> Dict[str, Any]:
        """分析数据特征"""
        analysis = {
            "type": "unknown",
            "feature_count": 0,
            "geometry_types": [],
            "has_numeric_fields": False,
            "numeric_fields": [],
            "has_points": False
        }

        try:
            import geopandas as gpd

            gdf = gpd.read_file(json.dumps(data), driver="GeoJSON")

            analysis["feature_count"] = len(gdf)
            analysis["geometry_types"] = list(gdf.geometry.geom_type.unique())

            # 检查数值字段
            numeric_cols = gdf.select_dtypes(include=['number']).columns.tolist()
            # 排除几何相关的数值字段
            numeric_cols = [c for c in numeric_cols if c not in ['id', 'index']]

            if numeric_cols:
                analysis["has_numeric_fields"] = True
                analysis["numeric_fields"] = numeric_cols

            # 检查是否主要是点要素
            if 'Point' in analysis["geometry_types"]:
                point_count = (gdf.geometry.geom_type == 'Point').sum()
                analysis["has_points"] = point_count > len(gdf) * 0.5
                analysis["point_ratio"] = point_count / len(gdf)

            return analysis

        except Exception as e:
            logger.warning(f"[GISVisualizationAdapter] 数据分析失败: {e}")
            # 降级分析
            features = data.get("features", [])
            analysis["feature_count"] = len(features)
            if features:
                geom_type = features[0].get("geometry", {}).get("type", "unknown")
                analysis["geometry_types"] = [geom_type]
            return analysis

    def _determine_visualization_type(
        self,
        analysis: Dict,
        prompt: str
    ) -> str:
        """根据数据特征和提示确定可视化类型"""

        # 根据提示优先判断
        if prompt:
            if "热力" in prompt or "heatmap" in prompt.lower():
                return "heatmap"
            if "分级" in prompt or "choropleth" in prompt.lower() or "统计" in prompt:
                return "choropleth"
            if "静态" in prompt or "png" in prompt.lower() or "图表" in prompt:
                return "static_map"
            if "交互" in prompt or "交互式" in prompt or "地图" in prompt:
                return "interactive_map"

        # 根据数据特征判断
        if analysis.get("has_numeric_fields"):
            # 有数值字段，适合分级统计图
            return "choropleth"

        if analysis.get("has_points") and analysis.get("feature_count", 0) > 100:
            # 大量点数据，适合热力图
            return "heatmap"

        # 默认交互地图
        return "interactive_map"

    def _find_value_column(self, data: Dict) -> Optional[str]:
        """查找适合分级的数值字段"""
        try:
            import geopandas as gpd
            gdf = gpd.read_file(json.dumps(data), driver="GeoJSON")

            numeric_cols = gdf.select_dtypes(include=['number']).columns.tolist()
            numeric_cols = [c for c in numeric_cols if c not in ['id', 'index', 'lat', 'lon']]

            if numeric_cols:
                return numeric_cols[0]
            return None

        except Exception:
            # 检查 properties
            features = data.get("features", [])
            if features:
                props = features[0].get("properties", {})
                for key, value in props.items():
                    if isinstance(value, (int, float)):
                        return key
            return None

    def _extract_points_from_geojson(self, data: Dict) -> list:
        """从 GeoJSON 提取点坐标"""
        points = []
        features = data.get("features", [])

        for f in features:
            geom = f.get("geometry", {})
            if geom.get("type") == "Point":
                coords = geom.get("coordinates", [])
                if len(coords) >= 2:
                    # folium 格式: [lat, lon, weight]
                    points.append([coords[1], coords[0], 1])
            elif geom.get("type") == "MultiPoint":
                for pt in geom.get("coordinates", []):
                    if len(pt) >= 2:
                        points.append([pt[1], pt[0], 1])

        return points