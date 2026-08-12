# prompts 模块（Prompt 模板库）

> 村庄规划 Agent 的全部分层 Prompt 模板：L1 现状分析（12 维）/ L2 规划思路（4 维）/ L3 详细规划（12 维）专业 Prompt + PARSE 结构化提取 Prompt。
> **Updated: 2026-08-02**

---

## 一、定位

集中管理所有 Agent 使用的 LLM 提示词模板，按子图分层组织。不执行逻辑，仅提供"模板 + 组装函数"。消费方为 `app/agent/analysis/node.py::_build_prompt`（L1/L2/L3 按维度取模板）与 `app/tools/gis/extract.py`（PARSE 表格提取）。

> ⚠️ **架构现状**：`parse_prompts.py` 的 6 个 Prompt 是按**旧 PARSE ReAct StateGraph**（classify → extract → validate_and_merge）设计的。当前 PARSE 已改为规则解析器（见 `agent/gis/parse/README.md`），这些 Prompt 中仅 `EXTRACT_TABLES_PROMPT` 仍被 `tools/gis/extract.py` 直接引用；其余为保留模板（LLM 增强路线可复用）。
> `prompts/l1/`（L1 聚合重构版）已于 2026-08-03 随死代码清理移除——`node.py` 始终使用 `prompts.analysis`，`l1/` 从未被引用。

---

## 二、目录结构

```
prompts/
├── __init__.py             # 仅导出 parse_prompts（PARSE 专用）
├── analysis.py             # ★ L1 现状分析：12 维 Prompt + ANALYSIS_RULES
├── concept.py              # L2 规划思路：4 维 Prompt + GLOBAL_CONCEPT_RULES
├── detailed.py             # ★ L3 claims：12 维 Prompt + WRITING_RULES + GIS_TOOL_GUIDE + claims schema guide
└── parse_prompts.py        # PARSE 结构化提取 6 Prompt + format_spatial_context_for_prompt
```

---

## 三、三层 Prompt 体系

### L1 现状分析（analysis.py）
- **12 维度**：`location`（区位与对外交通）、`socio_economic`（社会经济）、`villager_wishes`（村民意愿）、`superior_planning`（上位规划）、`natural_environment`（自然环境）、`land_use`（土地利用）、`traffic`（道路交通）、`public_services`（公共服务设施）、`infrastructure`（基础设施）、`ecological_green`（生态绿地）、`architecture`（建筑）、`historical_culture`（历史文化）。
- `ANALYSIS_RULES`：写作规则（冒号格式、自然段落、禁止章节/条目编号、数值带单位、markdown 表格必须含分隔行、【主题】段落标记）。
- L1 report projections may retain a separate evidence table for historical report display; it is not an L3 execution input.
- `get_dimension_prompt(dimension_key, raw_data, village_name, professional_data, task_description, constraints, knowledge_context, revision_instruction, has_images, natural_villages)`。

### L2 规划思路（concept.py）
- **4 维度**：`RESOURCE_ENDOWMENT_PROMPT`（资源禀赋）、`PLANNING_POSITIONING_PROMPT`（规划定位）、`DEVELOPMENT_GOALS_PROMPT`（发展目标）、`PLANNING_STRATEGIES_PROMPT`（规划策略）。
- `GLOBAL_CONCEPT_RULES`：只写结论性内容、禁止套话、每个定位/策略一行、数据必须具体。
- `get_dimension_prompt` / `get_specialized_data`（按维度从 state 取结构化数据）。

### L3 详细规划（detailed.py）
- **12 维度**：`industry`（产业）、`traffic_planning`（道路交通）、`public_service`（公共服务）、`infrastructure_planning`（基础设施）、`ecological`（生态）、`disaster_prevention`（防灾减灾）、`heritage`（历史文化）、`landscape`（风貌）、`project_bank`（项目库）、`spatial_structure`（空间结构）、`land_use_planning`（土地利用）、`settlement_planning`（居民点）。
- `WRITING_RULES`：法规条文式直陈（输出将组装为法定文本 .docx 条文）、禁止模糊词、清单必须表格。
- **GIS_TOOL_GUIDE（P0-3）**：注入现状用地指标（耕地/建设用地/生态红线）与规划目标（农田保护区/村庄建设区/生态保护区），引导空间布局维度引用，含设施服务半径标准（教育 500m / 医疗 300m / 养老 600m / 村委会 500m / 市场 1000m）。
- `CLAIMS_OUTPUT_GUIDE`：L3 只输出 `PlanningClaimSet`，不输出 Markdown、BSM、几何或 `ClassificationDecision`。
- `get_dimension_prompt(dimension_key, revision_instruction, **kwargs)`。

---

## 四、PARSE Prompt（parse_prompts.py）

6 个结构化 Prompt（旧 ReAct 图设计，Pydantic 结构化输出）：
`CLASSIFY_SECTIONS_PROMPT` / `EXTRACT_REGULATIONS_PROMPT` / `EXTRACT_TABLES_PROMPT` / `EXTRACT_PROJECTS_PROMPT` / `EXTRACT_TARGETS_PROMPT` / `VALIDATE_AND_MERGE_PROMPT`。

`format_spatial_context_for_prompt(context_blocks, detail_level)`：把 `ContextBlock` 列表格式化为 LLM 注入文本（"空间工作记忆"，让 PARSE 理解"村东"等空间指称）：
- `minimal`（~500 字符，分类用）：村元信息 + 自然村名；
- `standard`（~4000 字符，提取用）：+ 用地分布 + 保护分区；
- `full`（~12000 字符，校验用）：+ 空间关系 + 分区邻接。

> 现状：`EXTRACT_TABLES_PROMPT` 被 `tools/gis/extract.py` 引用；其余模板在当前规则解析器下未调用（保留备 LLM 增强）。

---

## 五、输入输出契约

```
输出（组装函数统一签名风格）:
  get_dimension_prompt(dimension_key, ...) -> str   # 模板填充后的完整 Prompt
  list_dimensions() -> List[{key, name}]            # 维度清单（API 下拉/校验用）
  format_spatial_context_for_prompt(context_blocks, detail_level) -> str
```

- 公共注入参数：`{raw_data} {village_name} {task_description} {constraints} {knowledge_context} {professional_data_section}`。
- 级联修订：`revision_instruction` 前缀注入（独立参数，不混入 knowledge_context）。
- 多模态：`has_images=True` 追加「上传图片分析指引」段。
- L3 claims：只由 `agent/l3_plan/worker.py` 以 structured output 调用；L1/L2 report projection 保持独立。

---

## 六、相关文档

- `app/agent/analysis/node.py` — 消费方（`_build_prompt` 按 layer 选模板）
- `app/tools/gis/extract.py` — 消费方（`EXTRACT_TABLES_PROMPT`）
- `app/agent/gis/parse/README.md` — PARSE 当前为规则解析器（Prompt 为保留模板）
