"""
修复 dimension_metadata.py - 重命名 Layer 3 的 traffic 和 infrastructure
"""
with open('F:/project/Village_Planning_Agent/src/config/dimension_metadata.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 替换 Layer 3 的 traffic 为 traffic_planning
# 只替换在 Layer 3 中的定义（在 dependencies 引用 Layer 1 的 traffic 之后）
old_traffic = '''    "traffic": {
        "key": "traffic",
        "name": "道路交通规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["traffic", "land_use"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄道路交通系统详细规划",
        "prompt_key": "traffic"
    },'''

new_traffic = '''    "traffic_planning": {
        "key": "traffic_planning",
        "name": "道路交通规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["traffic", "land_use"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄道路交通系统详细规划",
        "prompt_key": "traffic_planning"
    },'''

content = content.replace(old_traffic, new_traffic)

# 替换 Layer 3 的 infrastructure 为 infrastructure_planning
old_infra = '''    "infrastructure": {
        "key": "infrastructure",
        "name": "基础设施规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["infrastructure", "natural_environment"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄基础设施系统规划",
        "prompt_key": "infrastructure"
    },'''

new_infra = '''    "infrastructure_planning": {
        "key": "infrastructure_planning",
        "name": "基础设施规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["infrastructure", "natural_environment"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄基础设施系统规划",
        "prompt_key": "infrastructure_planning"
    },'''

content = content.replace(old_infra, new_infra)

# 保存
with open('F:/project/Village_Planning_Agent/src/config/dimension_metadata.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✓ dimension_metadata.py 已更新')
print('  - Layer 3 traffic → traffic_planning')
print('  - Layer 3 infrastructure → infrastructure_planning')