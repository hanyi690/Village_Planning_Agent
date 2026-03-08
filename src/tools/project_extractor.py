"""
项目提取工具 - 从规划报告中提取项目信息

用于建设项目库维度的预提取优化，减少 LLM 输入 token 量。
"""

import asyncio
import json
import logging
import re
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


# ==========================================
# 正则提取模式
# ==========================================

# 项目关键词模式
PROJECT_PATTERNS = [
    # 匹配"项目名称：XXX"格式
    r"项目[名称]*[：:]\s*([^\n]+)",
    # 匹配"建设XXX"格式
    r"建设[（(]?([^）)\n]{2,20})[）)]?",
    # 匹配数字编号项目
    r"[（(]\d+[）)]\s*([^\n]{4,30})",
    # 匹配"新建/改造/扩建XXX"
    r"(新建|改造|扩建|修建|完善|提升|建设)([^，,。\n]{2,25})",
    # 匹配带规模的描述
    r"([^\n]{4,20})[，,]?\s*(面积|规模|长度|数量)[：:]\s*(\d+\.?\d*)\s*(㎡|平方米|km|m|处|个)",
]

# 规模提取模式
SCALE_PATTERNS = [
    r"(面积|规模|长度|数量|占地)[：:]\s*(\d+\.?\d*)\s*(㎡|平方米|km|m|处|个|亩|公顷)",
    r"(\d+\.?\d*)\s*(㎡|平方米|km|m|处|个|亩|公顷)",
]

# 时序关键词
PHASE_KEYWORDS = {
    "近期": ["近期", "2025", "2026", "一阶段", "一期", "首期"],
    "中期": ["中期", "2027", "2028", "二阶段", "二期"],
    "远期": ["远期", "2029", "2030", "2035", "三阶段", "三期", "远期"]
}


def extract_projects_by_regex(content: str) -> List[Dict[str, str]]:
    """
    使用正则表达式从规划内容中提取项目信息

    Args:
        content: 规划报告文本

    Returns:
        提取的项目列表
    """
    projects = []
    seen_names = set()

    # 按段落分割
    paragraphs = re.split(r'\n{2,}', content)

    for pattern in PROJECT_PATTERNS:
        matches = re.findall(pattern, content, re.MULTILINE)
        for match in matches:
            if isinstance(match, tuple):
                name = match[0] if match[0] else match[1] if len(match) > 1 else ""
            else:
                name = match

            name = name.strip()
            # 过滤太短或太长的名称
            if len(name) < 3 or len(name) > 50:
                continue
            # 去重
            if name in seen_names:
                continue
            seen_names.add(name)

            # 尝试提取规模
            scale = extract_scale(content, name)

            # 尝试提取时序
            phase = extract_phase(content, name)

            projects.append({
                "name": name,
                "content": "",
                "scale": scale,
                "location": "",
                "phase": phase,
                "source": "regex"
            })

    logger.debug(f"[项目提取-正则] 提取到 {len(projects)} 个项目")
    return projects


def extract_scale(content: str, project_name: str) -> str:
    """提取项目规模"""
    # 在项目名称附近查找规模信息
    context_window = 200
    idx = content.find(project_name)
    if idx == -1:
        return ""

    context = content[max(0, idx - context_window):idx + len(project_name) + context_window]

    for pattern in SCALE_PATTERNS:
        match = re.search(pattern, context)
        if match:
            if len(match.groups()) >= 3:
                return f"{match.group(2)}{match.group(3)}"
            elif len(match.groups()) >= 2:
                return f"{match.group(1)}{match.group(2)}"

    return ""


def extract_phase(content: str, project_name: str) -> str:
    """提取项目时序"""
    context_window = 300
    idx = content.find(project_name)
    if idx == -1:
        return ""

    context = content[max(0, idx - context_window):idx + len(project_name) + context_window]

    for phase, keywords in PHASE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in context:
                return phase

    return ""


# ==========================================
# LLM 提取
# ==========================================

PROJECT_EXTRACTOR_PROMPT = """你是项目信息提取专家。

**任务**：从以下规划报告中提取所有建设项目信息。

**规划内容**：
{content}

**提取要求**：
1. 提取所有明确的项目（包括建设、改造、新建、完善等）
2. 每个项目包含：
   - name: 项目名称（简练，10字以内）
   - content: 建设内容（一句话概括）
   - scale: 建设规模（如"500㎡"、"2km"等，无则填"-"）
   - location: 建设选址（具体位置，无则填"-"）
   - phase: 实施时序（近期/中期/远期，无则填"近期"）

**输出格式**：严格输出 JSON 数组，不要包含其他内容。
示例：
```json
[
  {{"name": "村部改造", "content": "建筑改造装修", "scale": "200㎡", "location": "村中心", "phase": "近期"}},
  {{"name": "道路硬化", "content": "水泥路面铺设", "scale": "2km", "location": "主干道", "phase": "近期"}}
]
```

请输出 JSON：
"""


async def extract_projects_by_llm(
    content: str,
    dimension_key: str,
    max_content_length: int = 8000
) -> List[Dict[str, str]]:
    """
    使用 LLM 从规划内容中提取项目信息

    Args:
        content: 规划报告文本
        dimension_key: 维度标识
        max_content_length: 最大内容长度（超出则截取关键部分）

    Returns:
        提取的项目列表
    """
    # 截取内容，避免 token 过多
    if len(content) > max_content_length:
        # 优先保留包含项目关键词的部分
        content = extract_project_relevant_content(content, max_content_length)

    try:
        from src.core.llm_factory import create_llm
        from src.core.config import LLM_MODEL

        # 使用配置的模型
        llm = create_llm(model=LLM_MODEL, temperature=0.1, max_tokens=2000)

        prompt = PROJECT_EXTRACTOR_PROMPT.format(content=content)

        response = await llm.ainvoke(prompt)
        result_text = response.content if hasattr(response, 'content') else str(response)

        # 解析 JSON
        projects = parse_json_response(result_text)

        # 标记来源
        for p in projects:
            p["source"] = "llm"
            p["dimension"] = dimension_key

        logger.info(f"[项目提取-LLM] {dimension_key} 提取到 {len(projects)} 个项目")
        return projects

    except Exception as e:
        logger.warning(f"[项目提取-LLM] {dimension_key} 提取失败: {e}")
        return []


def extract_project_relevant_content(content: str, max_length: int) -> str:
    """提取包含项目相关信息的部分"""
    # 关键词列表
    keywords = ["项目", "建设", "新建", "改造", "工程", "设施", "近期", "中期", "远期", "面积", "规模"]

    # 按段落分割
    paragraphs = re.split(r'\n{2,}', content)

    relevant = []
    total_len = 0

    for para in paragraphs:
        # 检查段落是否包含关键词
        if any(kw in para for kw in keywords):
            if total_len + len(para) <= max_length:
                relevant.append(para)
                total_len += len(para)

    result = "\n\n".join(relevant)
    return result if result else content[:max_length]


def parse_json_response(text: str) -> List[Dict[str, str]]:
    """解析 LLM 返回的 JSON"""
    # 尝试提取 JSON 块
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if json_match:
        text = json_match.group(1)

    # 尝试提取数组
    array_match = re.search(r'\[[\s\S]*\]', text)
    if array_match:
        text = array_match.group(0)

    try:
        projects = json.loads(text)
        if isinstance(projects, list):
            return projects
    except json.JSONDecodeError:
        pass

    return []


# ==========================================
# 混合提取（正则 + LLM）
# ==========================================

async def extract_projects_hybrid(
    content: str,
    dimension_key: str,
    use_llm: bool = True
) -> List[Dict[str, str]]:
    """
    混合提取：先用正则快速提取，再用 LLM 补充完善

    Args:
        content: 规划报告文本
        dimension_key: 维度标识
        use_llm: 是否使用 LLM 补充

    Returns:
        提取的项目列表
    """
    # 1. 正则提取
    regex_projects = extract_projects_by_regex(content)

    if not use_llm:
        for p in regex_projects:
            p["dimension"] = dimension_key
        return regex_projects

    # 2. LLM 提取（如果内容足够重要且有项目相关内容）
    if any(kw in content for kw in ["项目", "建设", "新建", "改造", "工程"]):
        llm_projects = await extract_projects_by_llm(content, dimension_key)

        # 3. 合并去重
        seen_names = set(p["name"] for p in regex_projects)
        for p in llm_projects:
            if p["name"] not in seen_names:
                regex_projects.append(p)
                seen_names.add(p["name"])

    logger.info(f"[项目提取-混合] {dimension_key} 最终提取 {len(regex_projects)} 个项目")
    return regex_projects


# ==========================================
# 批量提取（用于并行处理）
# ==========================================

async def extract_projects_batch(
    dimension_reports: Dict[str, str],
    use_llm: bool = True
) -> Dict[str, List[Dict[str, str]]]:
    """
    批量提取多个维度的项目信息

    Args:
        dimension_reports: 维度 -> 报告内容
        use_llm: 是否使用 LLM

    Returns:
        维度 -> 项目列表
    """
    results = {}

    # 并行提取
    tasks = []
    for dim_key, content in dimension_reports.items():
        if content and len(content) > 100:  # 跳过空内容
            tasks.append(extract_projects_hybrid(content, dim_key, use_llm))
        else:
            tasks.append(asyncio.sleep(0, result=[]))  # 返回空列表

    # 等待所有任务完成
    extracted_lists = await asyncio.gather(*tasks, return_exceptions=True)

    for (dim_key, _), extracted in zip(dimension_reports.items(), extracted_lists):
        if isinstance(extracted, Exception):
            logger.warning(f"[项目提取-批量] {dim_key} 提取失败: {extracted}")
            results[dim_key] = []
        else:
            results[dim_key] = extracted

    return results


def format_shadow_cache_for_prompt(
    shadow_cache: Dict[str, List[Dict[str, str]]]
) -> str:
    """
    将影子缓存格式化为 Prompt 输入

    Args:
        shadow_cache: 项目影子缓存

    Returns:
        格式化的文本
    """
    parts = []

    for dim_key, projects in shadow_cache.items():
        if not projects:
            continue

        from src.config.dimension_metadata import get_detailed_dimension_names
        dim_name = get_detailed_dimension_names().get(dim_key, dim_key)

        lines = [f"### {dim_name}"]
        for p in projects:
            line = f"- {p['name']}"
            if p.get('scale') and p['scale'] != '-':
                line += f"（{p['scale']}）"
            if p.get('phase') and p['phase'] != '-':
                line += f" [{p['phase']}]"
            lines.append(line)

        parts.append("\n".join(lines))

    return "\n\n".join(parts) if parts else ""


__all__ = [
    "extract_projects_by_regex",
    "extract_projects_by_llm",
    "extract_projects_hybrid",
    "extract_projects_batch",
    "format_shadow_cache_for_prompt",
]
