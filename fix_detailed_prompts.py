"""
修复 detailed_plan_prompts.py 中的维度映射
"""
with open('F:/project/Village_Planning_Agent/src/subgraphs/detailed_plan_prompts.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 更新维度映射
content = content.replace(
    '''        "traffic": TRAFFIC_PLANNING_PROMPT,''',
    '''        "traffic_planning": TRAFFIC_PLANNING_PROMPT,'''
)

content = content.replace(
    '''        "infrastructure": INFRASTRUCTURE_PROMPT,''',
    '''        "infrastructure_planning": INFRASTRUCTURE_PROMPT,'''
)

# 保存
with open('F:/project/Village_Planning_Agent/src/subgraphs/detailed_plan_prompts.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✓ detailed_plan_prompts.py 已更新')
print('  - traffic → traffic_planning')
print('  - infrastructure → infrastructure_planning')