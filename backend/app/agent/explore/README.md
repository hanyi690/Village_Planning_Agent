# agent/explore 子包（EXPLORE 能力引擎）

> 文本 → 探索指令 / 证据：桥接 agent（Flash LLM 可选，文本分块 → 6 域分类 → BSM 识别）+ 确定性证据服务（retrieve_evidence）。
> **Updated: 2026-08-02**

---

## 一、定位

为 PARSE / Binder 提供**证据与候选实体引用**（不产出最终几何），并为 L1/L2/L3 维度分析提供**确定性证据注入**（无 LLM 调用）。两层实现并存：

1. **桥接 agent**（`ExploreFlashAgent` / `explore_planning_text`）——文本 → `ExplorationInstructionCollection`，供下游 Binder / PARSE 消费；
2. **证据服务**（`retrieve_evidence` / `render_evidence_prompt_section`）——由分析节点直接调用（替代已废弃的 `_optimize_semantics` + `_build_explore_brief` 路径）。

> 来源：本实现移植自 `origin/agent/kg-schema-gis-handoff-20260730` 分支（commit 25e24847），迁移到 `app/agent/explore/`；本地 `service.py` 提供确定性证据服务。

---

## 二、目录结构

```
explore/
├── __init__.py        # 导出 ExploreFlashAgent / SessionKGQuery / explore_planning_text / 契约 / 证据服务
├── agent.py           # ★ ExploreFlashAgent：确定性基线的探索 agent（Flash LLM 可选）
├── contracts.py       # ExplorationInstruction / ExplorationInstructionCollection（Pydantic 契约）
└── service.py         # retrieve_evidence / render_evidence_prompt_section（确定性证据服务）
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

## 四、输入输出契约

```
ExploreFlashAgent.explore(planning_text) → ExplorationInstructionCollection
  {session_id, village_name, kg_session_ref, instructions: [ExplorationInstruction]}
  ExplorationInstruction: {instruction_id "EXP-NNNN", source_chunk_id, section_title,
    source_page, evidence_text, domain, action, entity_mentions, entity_types,
    requested_bundle_queries, candidate_bsm_list, constraints, confidence, requires_human_confirmation}
```

---

## 五、相关文档

- `../analysis/README.md` — 维度分析（消费空间认知）
- `../gis/parse/README.md` — PARSE（下游消费者）
- `app/modules/kg/README.md` — KG（require_session_kg / query_session_template）
- `app/tools/access/` — 共享访问工具层
- `app/services/modules/gis/road/README.md` — 道路规划 Stage 管线（探索/确认交互）
