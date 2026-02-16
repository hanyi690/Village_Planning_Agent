"""
修复 dimension_config.py 的配置加载逻辑
"""
import re

# 读取原文件
with open('F:/project/Village_Planning_Agent/src/core/dimension_config.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 定义要替换的函数
old_function = r'''def _load_all_configs\(\) -> None:
    """加载所有配置文件（带缓存 + 线程安全）"""
    global _dimensions_config, _prompts_config

    # 快速路径：如果已加载，直接返回
    if _dimensions_config is not None:
        return

    # 使用锁保护配置加载
    with _config_lock:
        # 双重检查：可能在等待锁时已被其他线程加载
        if _dimensions_config is not None:
            return

        config_dir = Path\(__file__\)\.parent\.parent / "config"

        # 加载维度配置
        dimensions_path = config_dir / "dimensions\.yaml"
        with open\(dimensions_path, 'r', encoding='utf-8'\) as f:
            config_data = yaml\.safe_load\(f\)
            _dimensions_config = config_data

        # 加载 Prompt 配置
        prompts_path = config_dir / "prompts\.yaml"
        with open\(prompts_path, 'r', encoding='utf-8'\) as f:
            prompt_data = yaml\.safe_load\(f\)
            _prompts_config = prompt_data

        logger\.info\(f"\[dimension_config\] 配置加载完成: \{len\(_dimensions_config\['dimensions'\]\)\} 个维度"\)'''

new_function = '''def _load_all_configs() -> None:
    """加载所有配置文件（带缓存 + 线程安全）"""
    global _dimensions_config, _prompts_config

    # 快速路径：如果已加载，直接返回
    if _dimensions_config is not None:
        return

    # 使用锁保护配置加载
    with _config_lock:
        # 双重检查：可能在等待锁时已被其他线程加载
        if _dimensions_config is not None:
            return

        try:
            # 从 dimension_metadata.py 加载配置
            from ..config.dimension_metadata import DIMENSIONS_METADATA
            _dimensions_config = {"dimensions": DIMENSIONS_METADATA}
            _prompts_config = {}  # Prompt 不再从这里加载
            logger.info(f"[dimension_config] 配置加载完成: {len(DIMENSIONS_METADATA)} 个维度")
        except ImportError as e:
            logger.error(f"[dimension_config] 导入 dimension_metadata 失败: {e}")
            _dimensions_config = {"dimensions": {}}
            _prompts_config = {}'''

# 执行替换（使用正则表达式多行模式）
content = re.sub(old_function, new_function, content, flags=re.MULTILINE | re.DOTALL)

# 写回文件
with open('F:/project/Village_Planning_Agent/src/core/dimension_config.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ dimension_config.py 已修复")