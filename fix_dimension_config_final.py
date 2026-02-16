"""
修复 dimension_config.py - 最终版
"""
# 读取原文件
with open('F:/project/Village_Planning_Agent/src/core/dimension_config.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到并替换 _load_all_configs 函数
output = []
skip_until_next_def = False

for i, line in enumerate(lines):
    if 'def _load_all_configs()' in line:
        # 开始替换
        output.append('def _load_all_configs() -> None:\n')
        output.append('    """加载所有配置文件（带缓存 + 线程安全）"""\n')
        output.append('    global _dimensions_config, _prompts_config\n')
        output.append('\n')
        output.append('    # 快速路径：如果已加载，直接返回\n')
        output.append('    if _dimensions_config is not None:\n')
        output.append('        return\n')
        output.append('\n')
        output.append('    # 使用锁保护配置加载\n')
        output.append('    with _config_lock:\n')
        output.append('        # 双重检查：可能在等待锁时已被其他线程加载\n')
        output.append('        if _dimensions_config is not None:\n')
        output.append('            return\n')
        output.append('\n')
        output.append('        try:\n')
        output.append('            # 从 dimension_metadata.py 加载配置\n')
        output.append('            from ..config.dimension_metadata import DIMENSIONS_METADATA\n')
        output.append('            _dimensions_config = {"dimensions": DIMENSIONS_METADATA}\n')
        output.append('            _prompts_config = {}  # Prompt 不再从这里加载\n')
        output.append('            logger.info(f"[dimension_config] 配置加载完成: {len(DIMENSIONS_METADATA)} 个维度")\n')
        output.append('        except ImportError as e:\n')
        output.append('            logger.error(f"[dimension_config] 导入 dimension_metadata 失败: {e}")\n')
        output.append('            _dimensions_config = {"dimensions": {}}\n')
        output.append('            _prompts_config = {}\n')
        skip_until_next_def = True
    elif skip_until_next_def:
        # 跳过旧函数的内容，直到遇到下一个函数定义
        if line.strip().startswith('def ') and 'get_dimensions_config' in line:
            skip_until_next_def = False
            output.append(line)
    else:
        output.append(line)

# 写回文件
with open('F:/project/Village_Planning_Agent/src/core/dimension_config.py', 'w', encoding='utf-8') as f:
    f.writelines(output)

print("✓ dimension_config.py 已修复（最终版）")