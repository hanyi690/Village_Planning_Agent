# agent/explore 子包（EXPLORE 能力引擎）

> 文本 → 探索指令 / 空间认知：桥接 agent（Flash LLM 可选，文本分块 → 6 域分类 → BSM 识别）+ 确定性维度认知 / 概要索引。
> **Updated: 2026-08-02**

---

## 一、定位

为 PARSE / Binder 提供**证据与候选实体引用**（不产出最终几何），并为 L1/L2/L3 维度分析提供**确定性空间认知**（无 LLM 调用）。两层实现并存：

1. **桥接 agent**（`ExploreFlashAgent` / `explore_planning_text`）——文本 → `ExplorationInstructionCollection`，供下游 Binder / PARSE 消费；
2. **维度认知 / 概要索引**（`build_report_summary_index` / `build_spatial_cognition`）——由分析节点 `_optimize_semantics` 直接调用。

> 来源：本实现移植自 `origin/agent/kg-schema-gis-handoff-20260730` 分支（commit 25e24847），迁移到 `app/agent/explore/`；本地 `summaries.py` 继续提供确定性维度认知。

---

## 二、目录结构

```
explore/
├── __init__.py        # 导出 ExploreFlashAgent / SessionKGQuery / explore_planning_text / 契约 / 概要函数
├── agent.py           # ★ ExploreFlashAgent：确定性基线的探索 agent（Flash LLM 可选）
├── bridge_advisor.py  # BridgeAdvisor：组合维度 brief（L1 注入 reference 位置）
├── contracts.py       # ExplorationInstruction / ExplorationInstructionCollection（Pydantic 契约）
└── summaries.py       # build_report_summary_index / build_spatial_cognition（确定性空间认知）
```

---

## 三、桥接 agent（agent.py）

**`ExploreFlashAgent`**（构造廉价，Flash LLM 由 `GIS_EXPLORE_LLM_ENABLED` 门控）：
```
explore(planning_text) -> ExplorationInstructionCollection
  1. require_session_kg：前置 KG 就绪检查（防止陈旧/most-recent 图）
  2. _chunks：\f 分页 + markdown 标题分块
  3. _domain_for：8 域关键词计数分类（road/facility/landuse/zone/regulation/axis/project/…）
  4. _BSM_RE 提取 BSM / 标识码
  5. _mentions：引号短语 + 地名/设施名词 → 稳定别名（BSM 由模型捕获，不虚构）
  6. _action_for：按域+关键词推断动作（widen/repair/new_connection/road_requirement/create/preserve/constrain/plan）
  7. 每块产出 ExplorationInstruction（含 evidence_text / domain / action / entity_mentions /
     candidate_bsm_list / constraints / confidence：有 BSM 0.82 / 无 0.55 /
     requires_human_confirmation：无 BSM 时 True）
```

**`explore_planning_text`**：便捷入口（可写 JSON 输出文件）。**`SessionKGQuery`**：只能查当前 session 的 KG（不可跨会话回退）的模板查询门面。

---

## 四、维度认知（summaries.py + bridge_advisor.py）

- `build_spatial_cognition(session_id, dim_key, dim_layer) -> {prompt_section, ...}`：为每维度提供 KG 空间认知 + 报告概要索引（无 LLM）。
- `build_report_summary_index(...)`：概要索引构建。
- `BridgeAdvisor.compose_dim_brief(dim_key, dim_layer) → brief`：组合 L1 维度 brief（自然语言，注入 reference 位置），`format_brief_section` 转 Prompt 片段。

> 消费方：`analysis/node.py::_optimize_semantics`（KG 语义 + 空间统计 + 候选集标注）与 `_build_explore_brief`。工具定义在 `app.tools.access`（共享工具层，`ToolRegistry.for_agent("explore")` 注册）。

---

## 五、输入输出契约

```
ExploreFlashAgent.explore(planning_text) → ExplorationInstructionCollection
  {session_id, village_name, kg_session_ref, instructions: [ExplorationInstruction]}
  ExplorationInstruction: {instruction_id "EXP-NNNN", source_chunk_id, section_title,
    source_page, evidence_text, domain, action, entity_mentions, entity_types,
    requested_bundle_queries, candidate_bsm_list, constraints, confidence, requires_human_confirmation}

build_spatial_cognition(session_id, dim_key, dim_layer) → {prompt_section, ...}
```

---

## 六、相关文档

- `../analysis/README.md` — 维度分析（消费空间认知）
- `../gis/parse/README.md` — PARSE（下游消费者）
- `app/modules/kg/README.md` — KG（require_session_kg / query_session_template）
- `app/tools/access/` — 共享访问工具层
- `app/services/modules/gis/road/README.md` — 道路规划 Stage 管线（探索/确认交互）
