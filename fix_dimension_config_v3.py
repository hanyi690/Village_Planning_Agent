"""
修复 dimension_config.py 的语法错误
"""
# 读取原文件
with open('F:/project/Village_Planning_Agent/src/core/dimension_config.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复语法错误
content = content.replace('_prompts_config = {}  # Prompt 不再从这里加载\n\n\ndef get_dimensions_config()', '_prompts_config = {}  # Prompt 不再从这里加载\n\n\ndef get_dimensions_config()')

# 写回文件
with open('F:/project/Village_Planning_Agent/src/core/dimension_config.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ dimension_config.py 语法错误已修复")