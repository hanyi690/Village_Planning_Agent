"""
LLM styler: FlashLLM-driven generation for S-GENERATE articles.

Uses built-in format rules (no external reference document dependency).
Only uses FlashLLM - no main-model fallback. On failure, returns a
generic placeholder.
"""

import asyncio
import logging
from typing import Dict

from .content_extractor import ExtractedData

logger = logging.getLogger(__name__)

_FEW_SHOT_MAP = {1: 'background', 7: 'positioning', 19: 'guarantee', 20: 'guarantee', 21: 'guarantee', 22: 'supervision'}

_BUILTIN_RULES = {
    "格式": "法定文本，使用规范条文语言",
    "风格": "不使用「应该」「建议」等模糊表述，用自然段落叙述",
    "内容": "结合村庄背景中的具体数据",
    "输出": "只输出条文内容，不要包含「第X条 标题」",
}


class LLMStyler:

    def __init__(self, data: ExtractedData, *,
                 village_name: str = "",
                 planning_period: str = "2022-2035年"):
        self.data = data
        self.village_name = village_name
        self.planning_period = planning_period

    async def generate(self, num: int) -> str:
        ctx = self._build_context(num)
        prompt = self._build_prompt(num, ctx)
        return await self._call_llm(prompt)

    async def generate_all(self) -> Dict[int, str]:
        article_nums = [1, 7, 19, 20, 21, 22]
        tasks = [self.generate(num) for num in article_nums]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        output = {}
        for num, result in zip(article_nums, results):
            if isinstance(result, Exception):
                logger.warning(f"[LLMStyler] Article {num} failed: {result}")
                output[num] = self._fallback()
            else:
                output[num] = result
        return output

    def _build_context(self, num: int) -> str:
        parts = []
        if num == 1:
            # 村庄基本情况
            loc_parts = [self.data.province, self.data.city, self.data.county, self.data.town]
            location = ''.join(p for p in loc_parts if p) or "所在地区"
            parts.append(f"村庄名称：{self.village_name or '本村'}")
            parts.append(f"所在位置：{location}")
            parts.append(f"规划期限：{self.planning_period}")
            # 法律依据（合并三类）
            all_legal = []
            if self.data.legal_basis_national:
                all_legal.extend(self.data.legal_basis_national[:5])
            if self.data.legal_basis_provincial:
                all_legal.extend(self.data.legal_basis_provincial[:5])
            if self.data.legal_basis_planning:
                all_legal.extend(self.data.legal_basis_planning[:3])
            if all_legal:
                parts.append(f"编制依据：{'；'.join(all_legal)}")
            # 规划定位（可选）
            if self.data.planning_positioning:
                parts.append(f"规划定位：{self.data.planning_positioning[:200]}")
        elif num == 7:
            if self.data.planning_positioning:
                parts.append(f"规划定位：\n{self.data.planning_positioning[:800]}")
            if self.data.development_goal:
                parts.append(f"发展目标：{self.data.development_goal[:500]}")
            if self.data.resource_endowment:
                parts.append(f"资源禀赋：{self.data.resource_endowment[:500]}")
            if self.data.planning_strategies:
                parts.append(f"规划策略：{self.data.planning_strategies[:500]}")
        else:
            loc_parts = []
            for loc in [self.data.province, self.data.city, self.data.county, self.data.town]:
                if loc:
                    loc_parts.append(loc)
            location_str = ''.join(loc_parts) if loc_parts else "所在省/市/县/镇"
            parts.append(f"项目名称：{self.village_name or '村庄'}规划（{self.planning_period}）")
            parts.append(f"项目概况：村庄位于{location_str}，下辖{self.data.village_count}个自然村")
            if self.data.population_resident:
                parts.append(f"常住人口：{self.data.population_resident}人，户籍人口：{self.data.population_registered}人")
            if self.data.total_area_ha:
                parts.append(f"村域总面积：{self.data.total_area_ha:.2f}公顷")
            if self.data.planning_positioning:
                parts.append(f"规划定位：{self.data.planning_positioning[:300]}")
            if self.data.development_goal:
                parts.append(f"发展目标：{self.data.development_goal[:200]}")
            parts.append(f"耕地保有量：{self.data.farmland_ha:.2f}公顷")
            parts.append(f"森林覆盖率：{self.data.forest_coverage_pct}%")
            parts.append(f"自然村数量：{self.data.village_count}个")
        return '\n'.join(parts)

    def _build_prompt(self, num: int, ctx: str) -> str:
        rules = '\n'.join(f"- {k}: {v}" for k, v in _BUILTIN_RULES.items())
        titles = {1: "规划背景", 7: "村庄发展定位和目标", 19: "加强组织领导", 20: "驻村编制规划",
                  21: "严格用途管制", 22: "加强监督检查"}
        title = titles.get(num, "")
        return f"""你是乡村规划专家，请撰写村庄规划法定文本的一条条文。

## 格式规则
{rules}

## 背景
{ctx}

## 任务
撰写"第{num}条 {title}"的完整条文内容。

要求：
1. 严格参照法定文本的语言风格
2. 不使用"应该""建议""需要注意"等模糊表述
3. 用自然段落叙述
4. 结合村庄背景中的具体内容
5. 只输出条文内容，不要包含"第X条 标题"这一行"""

    async def _call_llm(self, prompt: str) -> str:
        try:
            from app.core.llm import create_flash_llm
            llm = create_flash_llm(max_tokens=800, temperature=0.3)
            resp = await llm.ainvoke(prompt)
            return (resp.content if hasattr(resp, 'content') else str(resp)).strip()
        except Exception as e:
            logger.warning(f"[LLMStyler] Flash LLM failed ({type(e).__name__}: {e})")
        return self._fallback()

    def _fallback(self) -> str:
        return "（规划实施保障措施将根据审批意见进一步细化。）"
