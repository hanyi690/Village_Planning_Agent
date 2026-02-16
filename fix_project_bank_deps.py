"""
修复 project_bank 的依赖关系
"""
with open('F:/project/Village_Planning_Agent/src/config/dimension_metadata.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 更新 project_bank 的依赖列表
old_deps = '''            "layer3_plans": [
                "industry",
                "spatial_structure",
                "land_use_planning",
                "settlement_planning",
                "traffic",
                "public_service",
                "infrastructure",
                "ecological",
                "disaster_prevention",
                "heritage",
                "landscape"
            ]'''

new_deps = '''            "layer3_plans": [
                "industry",
                "spatial_structure",
                "land_use_planning",
                "settlement_planning",
                "traffic_planning",
                "public_service",
                "infrastructure_planning",
                "ecological",
                "disaster_prevention",
                "heritage",
                "landscape"
            ]'''

content = content.replace(old_deps, new_deps)

# 保存
with open('F:/project/Village_Planning_Agent/src/config/dimension_metadata.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✓ project_bank 依赖关系已更新')
print('  - traffic → traffic_planning')
print('  - infrastructure → infrastructure_planning')