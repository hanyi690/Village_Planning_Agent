from typing import Dict

def plan_village(task: str, constraints: Dict = None) -> str:
    """
    生成分阶段村庄规划大纲（简化示例）。
    task: 规划目标描述
    constraints: 可选约束（预算、面积、时间线等）
    """
    constraints = constraints or {}
    # 简单规则化输出，实际可接入规则引擎或 GIS 服务
    return (
        f"规划目标：{task}\n\n"
        "阶段 1 — 需求与资源评估:\n"
        "- 人口与用地需求调研\n"
        "- 预算、用水用电评估\n\n"
        "阶段 2 — 总体布局与功能分区:\n"
        "- 住宅、商业、农业、公共服务分区\n"
        "- 交通与基础设施主干网\n\n"
        "阶段 3 — 详细设计与实施计划:\n"
        "- 分期施工里程碑\n"
        "- 风险与缓解措施\n\n"
        f"约束: {constraints}\n"
    )
