from typing import Tuple

def generate_simple_map(layout_spec: str) -> str:
    """
    根据 layout_spec 返回一个简单的文本地图占位符。
    layout_spec: 有关分区和关键要素的描述。
    """
    # 这是占位输出，实际可以生成 GeoJSON / SVG /调用 folium 等库
    ascii_map = (
        "+--------------------+\n"
        "|  Park   |  Housing  |\n"
        "|---------+-----------|\n"
        "| School  |  Market   |\n"
        "+--------------------+\n"
    )
    return f"基于描述的简易平面图:\n{ascii_map}\n说明: {layout_spec}"
