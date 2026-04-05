"""
交通网络分析核心逻辑

从 NetworkAnalysisAdapter 提取的核心功能，提供连通度、可达性、中心性分析。
"""

from typing import Dict, Any, List, Optional
from ...utils.logger import get_logger

logger = get_logger(__name__)

# 检查 networkx 是否可用
try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False
    logger.warning("[network_core] networkx 不可用")


def run_network_analysis(
    analysis_type: str,
    network_data: Optional[Dict[str, Any]] = None,
    origins: Optional[List[str]] = None,
    destinations: Optional[List[str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    执行网络分析

    Args:
        analysis_type: 分析类型
            - connectivity_metrics: 连通度分析
            - accessibility_analysis: 可达性分析
            - centrality_analysis: 中心性分析
        network_data: 网络数据（节点和边）
        origins: 起点列表
        destinations: 终点列表

    Returns:
        Dict[str, Any]: 分析结果
    """
    if not NETWORKX_AVAILABLE:
        return {
            "success": False,
            "error": "网络分析需要 networkx 库。请安装: pip install networkx"
        }

    if analysis_type == "connectivity_metrics":
        return _analyze_connectivity(network_data, **kwargs)
    elif analysis_type == "accessibility_analysis":
        return _analyze_accessibility(network_data, origins, destinations, **kwargs)
    elif analysis_type == "centrality_analysis":
        return _analyze_centrality(network_data, **kwargs)
    else:
        return {"success": False, "error": f"不支持的分析类型: {analysis_type}"}


def _build_graph(network_data: Dict[str, Any]):
    """从网络数据构建 NetworkX 图"""
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

    return G


def _analyze_connectivity(network_data: Optional[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
    """连通度分析"""
    if not network_data:
        return {"success": False, "error": "缺少 network_data 参数"}

    try:
        G = _build_graph(network_data)
        num_nodes = G.number_of_nodes()

        network_density = nx.density(G)

        if nx.is_connected(G):
            connectivity_index = 1.0
            avg_path_length = nx.average_shortest_path_length(G, weight="weight")
        else:
            largest_cc_size = len(max(nx.connected_components(G), key=len))
            connectivity_index = largest_cc_size / num_nodes if num_nodes > 0 else 0
            avg_path_length = float('inf')

        isolated_nodes = [n for n in G.nodes() if G.degree(n) == 0]
        accessibility_score = network_density * 0.4 + connectivity_index * 0.6

        return {
            "success": True,
            "data": {
                "network_density": round(network_density, 4),
                "connectivity_index": round(connectivity_index, 4),
                "accessibility_score": round(accessibility_score, 4),
                "average_path_length": round(avg_path_length, 2) if avg_path_length != float('inf') else None,
                "isolated_nodes": isolated_nodes
            }
        }
    except Exception as e:
        return {"success": False, "error": f"连通度分析失败: {str(e)}"}


def _analyze_accessibility(
    network_data: Optional[Dict[str, Any]],
    origins: Optional[List[str]] = None,
    destinations: Optional[List[str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """可达性分析"""
    if not network_data:
        return {"success": False, "error": "缺少 network_data 参数"}

    try:
        G = _build_graph(network_data)

        if origins is None:
            origins = list(G.nodes())
        if destinations is None:
            destinations = list(G.nodes())

        od_matrix = []
        for origin in origins:
            for dest in destinations:
                try:
                    distance = nx.shortest_path_length(G, origin, dest, weight="weight")
                    # 速度参数化：优先从边属性获取，否则使用默认值
                    avg_speed = kwargs.get("avg_speed_kmh", 30)
                    travel_time = distance / avg_speed * 60
                    od_matrix.append({
                        "origin": origin,
                        "destination": dest,
                        "distance": round(distance, 2),
                        "travel_time": round(travel_time, 1)
                    })
                except nx.NetworkXNoPath:
                    od_matrix.append({
                        "origin": origin,
                        "destination": dest,
                        "distance": None,
                        "travel_time": None
                    })

        service_areas = []
        centers = kwargs.get("centers", origins[:3] if origins else [])
        radius = kwargs.get("service_radius", 2.0)

        for center in centers:
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
            "success": True,
            "data": {
                "origin_destination_matrix": od_matrix,
                "service_areas": service_areas
            }
        }
    except Exception as e:
        return {"success": False, "error": f"可达性分析失败: {str(e)}"}


def _analyze_centrality(network_data: Optional[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
    """中心性分析"""
    if not network_data:
        return {"success": False, "error": "缺少 network_data 参数"}

    try:
        G = _build_graph(network_data)
        top_n = kwargs.get("top_n", 5)

        degree_centrality = nx.degree_centrality(G)
        betweenness_centrality = nx.betweenness_centrality(G, weight="weight")
        closeness_centrality = nx.closeness_centrality(G, distance="weight")

        def get_top_nodes(centrality_dict, n=top_n):
            sorted_nodes = sorted(centrality_dict.items(), key=lambda x: x[1], reverse=True)
            return {node: round(value, 4) for node, value in sorted_nodes[:n]}

        return {
            "success": True,
            "data": {
                "degree_centrality": get_top_nodes(degree_centrality),
                "betweenness_centrality": get_top_nodes(betweenness_centrality),
                "closeness_centrality": get_top_nodes(closeness_centrality)
            }
        }
    except Exception as e:
        return {"success": False, "error": f"中心性分析失败: {str(e)}"}


def format_network_result(result: Dict[str, Any]) -> str:
    """格式化网络分析结果为字符串"""
    if not result.get("success"):
        return f"网络分析失败: {result.get('error', '未知错误')}"

    data = result.get("data", {})
    lines = ["交通网络分析结果："]

    if "network_density" in data:
        lines.append(f"- 网络密度: {data['network_density']}")
        lines.append(f"- 连通性指数: {data['connectivity_index']}")
        lines.append(f"- 可达性评分: {data['accessibility_score']}")

        if data.get("average_path_length"):
            lines.append(f"- 平均路径长度: {data['average_path_length']}")

        if data.get("isolated_nodes"):
            lines.append(f"- 孤立节点: {', '.join(data['isolated_nodes'])}")

    if "degree_centrality" in data:
        lines.append("- 度中心性 (Top 5):")
        for node, value in data["degree_centrality"].items():
            lines.append(f"  * {node}: {value}")

    return "\n".join(lines)