"""
修复 dimension_config.py - 简化版
"""
# 读取原文件
with open('F:/project/Village_Planning_Agent/src/core/dimension_config.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到 _load_all_configs 函数并替换
new_lines = []
in_function = False
function_started = False

for i, line in enumerate(lines):
    if 'def _load_all_configs()' in line:
        in_function = True
        new_lines.append(line)
        new_lines.append('    """加载所有配置文件（带缓存 + 线程安全）"""\n')
        new_lines.append('    global _dimensions_config, _prompts_config\n')
        new_lines.append('\n')
        new_lines.append('    # 快速路径：如果已加载，直接返回\n')
        new_lines.append('    if _dimensions_config is not None:\n')
        new_lines.append('        return\n')
        new_lines.append('\n')
        new_lines.append('    # 使用锁保护配置加载\n')
        new_lines.append('    with _config_lock:\n')
        new_lines.append('        # 双重检查：可能在等待锁时已被其他线程加载\n')
        new_lines.append('        if _dimensions_config is not None:\n')
        new_lines.append('            return\n')
        new_lines.append('\n')
        new_lines.append('        try:\n')
        new_lines.append('            # 从 dimension_metadata.py 加载配置\n')
        new_lines.append('            from ..config.dimension_metadata import DIMENSIONS_METADATA\n')
        new_lines.append('            _dimensions_config = {"dimensions": DIMENSIONS_METADATA}\n')
        new_lines.append('            _prompts_config = {}  # Prompt 不再从这里加载\n')
        new_lines.append('            logger.info(f"[dimension_config] 配置加载完成: {len(DIMENSIONS_METADATA)} 个维度")\n')
        new_lines.append('        except ImportError as e:\n')
        new_lines.append('            logger.error(f"[dimension_config] 导入 dimension_metadata 失败: {e}")\n')
        new_lines.append('            _dimensions_config = {"dimensions": {}}\n')
        new_lines.append('            _prompts_config = {}\n')
        # 跳过旧函数的剩余部分
        while i + 1 < len(lines):
            i += 1
            if lines[i].strip() and not lines[i].startswith('    ') and lines[i].strip() != '':
                # 函数结束，添加当前行并跳出
                new_lines.append('\n')
                new_lines.append(lines[i])
                break
    elif in_function and line.strip() == '':
        continue  # 跳过旧函数的空行
    elif in_function:
        continue  # 跳过旧函数的其他行
    else:
        new_lines.append(line)

# 写回文件
with open('F:/project/Village_Planning_Agent/src/core/dimension_config.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("✓ dimension_config.py 已修复（简化版）")