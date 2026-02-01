"""
交通网络分析适配器

提供路网连通度分析、可达性分析、网络中心性分析等功能。
使用 NetworkX 进行图网络分析。
"""

from typing import Dict, Any, List, Optional, Tuple
import json

from .base_adapter import BaseAdapter, AdapterResult, AdapterStatus
from ...utils.logger import get_logger

logger = get_logger(__name__)


class NetworkAnalysisAdapter(BaseAdapter):
    """
    交通网络分析适配器

    支持的分析类型：
    1. 连通度分析 (connectivity_metrics)
    2. 可达性分析 (accessibility_analysis)
    3. 网络中心性分析 (centrality_analysis)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化网络适配器

        Args:
            config: 配置参数
        """
        super().__init__(config)
        self._networkx_available = False
        self._graph = None  # NetworkX图对象

    def validate_dependencies(self) -> bool:
        """
        验证外部依赖是否可用

        Returns:
            True if networkx is available, False otherwise
        """
        try:
            import networkx
            self._networkx_available = True
            logger.info("[NetworkAdapter] networkx 可用")
            return True
        except ImportError:
            logger.warning("[NetworkAdapter] networkx 不可用")
            return False

    def initialize(self) -> bool:
        """
        初始化适配器

        Returns:
            True if initialization successful
        """
        try:
            if self._networkx_available:
                import networkx as nx
                self._graph = nx.Graph()
                logger.info("[NetworkAdapter] networkx 已初始化")

            self._status = AdapterStatus.READY
            return True
        except Exception as e:
            self._error_message = f"初始化失败: {str(e)}"
            logger.error(f"[NetworkAdapter] {self._error_message}")
            return False

    def execute(self, analysis_type: str = "connectivity_metrics", **kwargs) -> AdapterResult:
        """
        执行网络分析

        Args:
            analysis_type: 分析类型 (connectivity_metrics/accessibility_analysis/centrality_analysis)
            **kwargs: 分析参数，可包含：
                - network_data: 网络数据（节点和边）
                - origins: 起点列表（可达性分析）
                - destinations: 终点列表（可达性分析）
                - custom_params: 自定义参数

        Returns:
            AdapterResult: 分析结果
        """
        # 检查依赖
        if not self._networkx_available:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="网络分析需要 networkx 库。请安装: pip install networkx"
            )

        if analysis_type == "connectivity_metrics":
            return self._analyze_connectivity(**kwargs)
        elif analysis_type == "accessibility_analysis":
            return self._analyze_accessibility(**kwargs)
        elif analysis_type == "centrality_analysis":
            return self._analyze_centrality(**kwargs)
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"不支持的分析类型: {analysis_type}"
            )

    def get_schema(self) -> Dict[str, Any]:
        """获取输出Schema"""
        return {
            "adapter_name": "NetworkAnalysisAdapter",
            "supported_analyses": [
                "connectivity_metrics",
                "accessibility_analysis",
                "centrality_analysis"
            ],
            "output_schemas": {
                "connectivity_metrics": {
                    "network_density": "number",
                    "connectivity_index": "number",
                    "accessibility_score": "number (optional)",
                    "average_path_length": "number (optional)",
                    "isolated_nodes": "array (optional)"
                },
                "accessibility_analysis": {
                    "origin_destination_matrix": "array",
                    "service_areas": "array (optional)"
                },
                "centrality_analysis": {
                    "degree_centrality": "dict",
                    "betweenness_centrality": "dict",
                    "closeness_centrality": "dict"
                }
            }
        }

    # ==========================================
    # 具体分析方法
    # ==========================================

    def _analyze_connectivity(self, **kwargs) -> AdapterResult:
        """
        连通度分析

        分析路网的密度、连通性、可达性等指标。
        """
        logger.info("[NetworkAdapter] 执行连通度分析")

        # 检查数据
        network_data = kwargs.get("network_data")
        if not network_data:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 network_data 参数。请提供网络数据（节点和边）。"
            )

        try:
            result = self._analyze_connectivity_real(network_data=network_data, **kwargs)

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data=result,
                metadata={
                    "analysis_type": "connectivity_metrics",
                    "data_source": "real"
                }
            )

        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"连通度分析失败: {str(e)}"
            )

    def _analyze_connectivity_real(self, network_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """使用真实NetworkX数据进行连通度分析"""
        import networkx as nx

        # 构建图
        G = nx.Graph()

        # 添加节点
        for node in network_data.get("nodes", []):
            G.add_node(node["id"], **node.get("attributes", {}))

        # 添加边
        for edge in network_data.get("edges", []):
            G.add_edge(
                edge["source"],
                edge["target"],
                weight=edge.get("weight", 1),
                **edge.get("attributes", {})
            )

        # 计算指标
        num_nodes = G.number_of_nodes()
        num_edges = G.number_of_edges()

        # 网络密度（实际边数 / 可能的最大边数）
        network_density = nx.density(G)

        # 连通性指数（基于连通分量）
        if nx.is_connected(G):
            connectivity_index = 1.0
        else:
            # 使用最大连通分量的节点占比作为连通性指数
            largest_cc_size = len(max(nx.connected_components(G), key=len))
            connectivity_index = largest_cc_size / num_nodes

        # 平均路径长度（仅当图连通时）
        if nx.is_connected(G):
            avg_path_length = nx.average_shortest_path_length(G, weight="weight")
        else:
            avg_path_length = float('inf')

        # 查找孤立节点
        isolated_nodes = [n for n in G.nodes() if G.degree(n) == 0]

        # 可达性评分（综合指标）
        accessibility_score = (network_density * 0.4 + connectivity_index * 0.6)

        return {
            "network_density": round(network_density, 4),
            "connectivity_index": round(connectivity_index, 4),
            "accessibility_score": round(accessibility_score, 4),
            "average_path_length": round(avg_path_length, 2) if avg_path_length != float('inf') else None,
            "isolated_nodes": isolated_nodes
        }

    def _analyze_accessibility(self, **kwargs) -> AdapterResult:
        """
        可达性分析

        分析起点到终点的可达性矩阵和服务区域。
        """
        logger.info("[NetworkAdapter] 执行可达性分析")

        # 检查数据
        network_data = kwargs.get("network_data")
        if not network_data:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 network_data 参数。请提供网络数据（节点和边）。"
            )

        try:
            result = self._analyze_accessibility_real(
                network_data=network_data,
                origins=kwargs.get("origins"),
                destinations=kwargs.get("destinations"),
                **kwargs
            )

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data=result,
                metadata={
                    "analysis_type": "accessibility_analysis",
                    "data_source": "real"
                }
            )

        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"可达性分析失败: {str(e)}"
            )

    def _analyze_accessibility_real(
        self,
        network_data: Dict[str, Any],
        origins: Optional[List[str]] = None,
        destinations: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """使用真实NetworkX数据进行可达性分析"""
        import networkx as nx

        # 构建图
        G = nx.Graph()

        for node in network_data.get("nodes", []):
            G.add_node(node["id"], **node.get("attributes", {}))

        for edge in network_data.get("edges", []):
            G.add_edge(
                edge["source"],
                edge["target"],
                weight=edge.get("weight", 1),
                **edge.get("attributes", {})
            )

        # 默认使用所有节点作为起点和终点
        if origins is None:
            origins = list(G.nodes())
        if destinations is None:
            destinations = list(G.nodes())

        # 计算起讫点矩阵
        od_matrix = []
        for origin in origins:
            for dest in destinations:
                try:
                    # 计算最短路径距离
                    distance = nx.shortest_path_length(G, origin, dest, weight="weight")
                    # 假设平均速度为30km/h，转换为行程时间
                    travel_time = distance / 30 * 60  # 分钟

                    od_matrix.append({
                        "origin": origin,
                        "destination": dest,
                        "distance": round(distance, 2),
                        "travel_time": round(travel_time, 1)
                    })
                except nx.NetworkXNoPath:
                    # 不可达
                    od_matrix.append({
                        "origin": origin,
                        "destination": dest,
                        "distance": None,
                        "travel_time": None
                    })

        # 计算服务区域（以关键设施为中心）
        service_areas = []
        for center in kwargs.get("centers", origins[:3]):  # 默认前3个起点作为中心
            radius = kwargs.get("service_radius", 2.0)  # 默认2公里服务半径

            # 计算服务半径内的节点
            nodes_in_radius = []
            for node in G.nodes():
                try:
                    dist = nx.shortest_path_length(G, center, node, weight="weight")
                    if dist <= radius:
                        nodes_in_radius.append(node)
                except nx.NetworkXNoPath:
                    pass

            coverage_ratio = len(nodes_in_radius) / G.number_of_nodes() if G.number_of_nodes() > 0 else 0

            service_areas.append({
                "center": center,
                "radius": radius,
                "coverage_ratio": round(coverage_ratio, 4)
            })

        return {
            "origin_destination_matrix": od_matrix,
            "service_areas": service_areas
        }

    def _analyze_centrality(self, **kwargs) -> AdapterResult:
        """
        中心性分析

        分析节点的中心性指标（度中心性、介数中心性、接近中心性）。
        """
        logger.info("[NetworkAdapter] 执行中心性分析")

        # 检查数据
        network_data = kwargs.get("network_data")
        if not network_data:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 network_data 参数。请提供网络数据（节点和边）。"
            )

        try:
            result = self._analyze_centrality_real(network_data=network_data, **kwargs)

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data=result,
                metadata={
                    "analysis_type": "centrality_analysis",
                    "data_source": "real"
                }
            )

        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"中心性分析失败: {str(e)}"
            )

    def _analyze_centrality_real(self, network_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """使用真实NetworkX数据进行中心性分析"""
        import networkx as nx

        # 构建图
        G = nx.Graph()

        for node in network_data.get("nodes", []):
            G.add_node(node["id"], **node.get("attributes", {}))

        for edge in network_data.get("edges", []):
            G.add_edge(
                edge["source"],
                edge["target"],
                weight=edge.get("weight", 1),
                **edge.get("attributes", {})
            )

        # 计算中心性指标
        degree_centrality = nx.degree_centrality(G)
        betweenness_centrality = nx.betweenness_centrality(G, weight="weight")
        closeness_centrality = nx.closeness_centrality(G, distance="weight")

        # 找出最重要的节点
        top_nodes = kwargs.get("top_n", 5)

        def get_top_nodes(centrality_dict, n=top_nodes):
            sorted_nodes = sorted(centrality_dict.items(), key=lambda x: x[1], reverse=True)
            return {node: round(value, 4) for node, value in sorted_nodes[:n]}

        return {
            "degree_centrality": get_top_nodes(degree_centrality),
            "betweenness_centrality": get_top_nodes(betweenness_centrality),
            "closeness_centrality": get_top_nodes(closeness_centrality)
        }

    def run_all_analyses(self, **kwargs) -> Dict[str, AdapterResult]:
        """
        运行所有网络分析

        Args:
            **kwargs: 分析参数

        Returns:
            包含所有分析结果的字典
        """
        return {
            "connectivity": self.execute(analysis_type="connectivity_metrics", **kwargs),
            "accessibility": self.execute(analysis_type="accessibility_analysis", **kwargs),
            "centrality": self.execute(analysis_type="centrality_analysis", **kwargs)
        }
