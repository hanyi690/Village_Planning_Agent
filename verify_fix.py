"""
验证维度键名修复
"""
from src.config.dimension_metadata import get_dimension_config
from src.subgraphs.detailed_plan_prompts import get_dimension_prompt

# 验证 Layer 1
traffic_l1 = get_dimension_config('traffic')
print(f'✓ Layer 1 traffic: layer={traffic_l1["layer"]}, name={traffic_l1["name"]}')

# 验证 Layer 3
traffic_l3 = get_dimension_config('traffic_planning')
print(f'✓ Layer 3 traffic_planning: layer={traffic_l3["layer"]}, name={traffic_l3["name"]}')

# 验证 Prompt 映射
prompt = get_dimension_prompt('traffic_planning', 'test', 'test', 'test', 'test')
print(f'✓ traffic_planning prompt: {len(prompt)} 字符')

# 验证 infrastructure
infra_l1 = get_dimension_config('infrastructure')
print(f'✓ Layer 1 infrastructure: layer={infra_l1["layer"]}, name={infra_l1["name"]}')

infra_l3 = get_dimension_config('infrastructure_planning')
print(f'✓ Layer 3 infrastructure_planning: layer={infra_l3["layer"]}, name={infra_l3["name"]}')

print('\n✓ 所有验证通过！')