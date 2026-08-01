# EXPLORE → KG Enrichment 闭环设计（2026-07-31）

> 本文档记录 EXPLORE agent 向 L1/L2/L3 提供空间认知、并通过 PARSE 抽取
> 报告 binding 写回 KG 的完整设计。目标：实现"每日强化"闭环 — KG 随
> 每一轮报告积累更多真实地名/特征/约束的语义绑定，让后续维度分析
> 的空间认知 brief 越来越精准。

---

## 0. 背景

### 0.1 当前问题

- KG 只有 660 个 parcels 的几何 + DLBM，没有"田坑自然村"、"黄竹自然村"、
  "公王河"等真实地名与几何的绑定
- `_optimize_semantics` 只读 KG，不写回
- `ExploreFlashAgent.bridge mode` 产出 `ExplorationInstructionCollection`，
  但不调用 `kg.memory.add_entity_annotation`
- L1/L2/L3 报告生成是重推理任务，强制 JSON 输出会损耗 10-15% 准确率
  （Tam et al. NeurIPS 2024 "Let Me Speak Freely?"）

### 0.2 已落地的 stage-0（参考上一轮交付）

- `app/modules/kg/interface.py` — stable boundary（`require_session_kg` 等）
- `app/modules/kg/manager.py` — 新增 `require_session_kg` + `get_session_version`
- `app/core/settings.py` — `GIS_EXPLORE_*` Flash LLM 配置（默认 ON，qwen-flash）
- `app/agent/explore/{contracts.py, agent.py}` — `ExploreFlashAgent` + 契约
- 9 个新测试通过（`tests/unit/test_explore_flash_agent.py`）

### 0.3 与设计文档关系

- 本文档是 `05_EXPLORE_BRIDGE.md` 的具体实现延伸
- 对应台账：`10_IMPLEMENTATION_STATUS.md`（待更新）

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│  EXPLORE 在系统里的两个位置                                          │
│    ① L1/L2/L3 维度分析之前 (BridgeAdvisor) — 提供空间认知 brief     │
│    ② Wave 末尾 (ParseAgent)           — 抽取报告 binding 写回 KG   │
└─────────────────────────────────────────────────────────────────────┘

═══ 阶段 0: Bundle + KG 初始化（一次性）═══════════════════════════════
  DataCatalog.load_village_bundle("金田村")
    → VillageBundle（660 parcels + 4 自然村 annotations + 公王河 等）
  KGManager.get_or_build_layer1(...)
    → PlanningKG（660 parcels，无中文地名 binding）
  open_kg_session(session_id, village_name, bundle)
    → KGSessionSnapshot，register_session()

═══ 阶段 1: per-dim, before analyze（BridgeAdvisor）════════════════════
  BridgeAdvisor.compose_dim_brief(session_id, dim_key, dim_layer)
    inputs:
      - VillageBundle（geometry、parcels、annotations）
      - KG cognition（get_village_cognition）
      - 当前 wave 已完成的 reports（依赖）
    output:
      SpatialCognitionBrief（纯自然语言 dataclass）：
        village_overview:    "金田村共 660 个地块，总面积约 200 公顷..."
        spatial_pattern:     "村庄沿公王河呈组团式布局，田坑位于西北..."
        spatial_constraints: "永久基本农田 81.43 公顷位于..."
        relevant_entities:   "田坑自然村 现有耕地 12.5 公顷，含 BSM:...563"
        focus_hints:         ["田坑 是产业重点", "黄竹 受生态红线约束"]
        kg_confidence:       0.78

═══ 阶段 2: per-dim, LLM 生成报告（原任务不变）════════════════════════
  prompt 顺序（_build_prompt 内追加 brief 到 reference materials 位置）：
    [原 LAND_USE_PROMPT 等]
      你是土地利用分析专家。
      **任务**：分析各类用地分布与利用效率。...[原任务]
      **参考规范**：
      {knowledge_context}
      **输入数据**：
      {raw_data}
      [NEW] **【EXPLORE 空间基础（供你分析参考）】**
        <SpatialCognitionBrief 自然语言内容>
      [ANALYSIS_RULES + entity_spec_instruction]
      **输出骨架**：[原表 + 必填字段]

  LLM 看到：
    - 上方原任务指令（不丢）
    - 中间 EXPLORE brief（作为参考事实基座）
    - 下方 ANALYSIS_RULES + 输出骨架（强结构）
  LLM 自然地把 brief 数字填进表 + 骨架段落里
  ❌ 不强制 JSON
  ❌ 不引入 focus_questions
  ❌ 不破坏 ANALYSIS_RULES

═══ 阶段 3: Wave 末尾（ParseAgent.extract_bindings）════════════════════
  Wave 末尾事件触发（L1-12 完成 / L2-4 完成 / L3-12 完成）：
    ParseAgent.extract_bindings(
        session_id, wave, reports={dim_key: content}
    )
    Step 1: 拼 Flash LLM prompt：
      system: "你是村庄规划报告语义抽取助手，识别真实地名/特征/约束"
      user:
        - 所有 wave 内的 L1/L2/L3 报告原文（纯文本）
        - 候选 BSM 清单（从 KG `get_parcels_semantic_list`）
      output_format: JSON schema（constrained decoding）
        {"bindings": [{
          "natural_village": "田坑自然村",
          "candidate_bsms": ["44142611020200000563", ...],
          "feature_type": "parcel" | "road" | "facility",
          "confidence": 0.85
        }]}
    Step 2: Flash LLM 输出结构化候选 binding
    Step 3: kgg write-gate 三重校验：
      a. BSM ∈ KG（`kg.g.subjects()`）
      b. 几何包含：annotation_point bbox ∩ parcel_geometry
      c. LLM confidence ≥ 0.6
    Step 4: 通过 → `SemanticMemoryStore.add_entity_annotation(round=N)`
    Step 5: 失败 → pending_review queue（持久化到 `data/kg_memory/_review/`）
    Step 6: `bump_version(session_id)`
    Step 7: `save_memory_state(session_id, round=N)`

═══ 阶段 4: 持久化与跨轮（H 子任务）══════════════════════════════════════
  存储路径：`data/kg_memory/{session_id}_round_{N}.json`
  Round N → Round N+1:
    1. `load_memory_state(session_id, round=N-1)` → 恢复 SemanticMemoryStore
    2. `KGManager._session_versions[session_id] = N-1`
    3. `bump_version` → 失效 query cache
    4. 跑 round N（重跑 PARSE，不重跑 LLM）
    5. `diff_round(previous=store_N-1, current=store_N)` → 报告

  Annotation 新字段：
    round_added: int = 1
    valid_from_round: int = 1
    valid_until_round: Optional[int] = None
    confidence: float = 1.0

  Supersede 逻辑：
    同一 entity_uri 新 binding confidence > 旧 confidence → 旧标过期

═══ 闭环（每日强化）════════════════════════════════════════════════════
  R1: 0 bindings    → 6 bindings（田坑/黄竹）
  R2: 6 bindings    → 18 bindings（+公王河，+supersede 2）
  R3: 18 bindings   → 23 bindings（+收敛）
  R∞: 触发 stop（新 binding 增量 < 5%）
```

---

## 2. 数据契约

### 2.1 `SpatialCognitionBrief`（BridgeAdvisor 输出）

```python
@dataclass
class SpatialCognitionBrief:
    """纯自然语言 dataclass，注入 L1/L2/L3 prompt"""
    village_overview: str        # 一段话描述村庄
    spatial_pattern: str         # 一段话描述布局
    spatial_constraints: str     # 一段话描述约束
    relevant_entities: str       # 一段话描述关键实体（含真实 BSM）
    focus_hints: list[str]       # 1-5 句提示（dim-aware，但**不进** prompt 主任务）
    kg_confidence: float         # 0-1，反映 KG 数据完整度
```

### 2.2 `PendingBinding`（PARSE 端）

```python
@dataclass
class PendingBinding:
    natural_village: Optional[str]  # "田坑自然村" | None
    feature_type: str               # "parcel" | "road" | "facility" | "control_line"
    candidate_bsms: list[str]
    description: str
    confidence: float
    source_report_keys: list[str]  # 来自哪个 dim_key
```

### 2.3 `EntityAnnotation`（扩展，H 子任务）

```python
@dataclass
class EntityAnnotation:
    entity_uri: str
    entity_type: str
    description: str = ""
    source_text_refs: list[str] = field(default_factory=list)
    intent_refs: list[str] = field(default_factory=list)
    # 新增（H 子任务）
    round_added: int = 1
    valid_from_round: int = 1
    valid_until_round: Optional[int] = None
    confidence: float = 1.0
```

---

## 3. 子任务清单（7 个，总计 ~840 行）

| #              | 文件                                     | 类型  | 行数              | 关键约束                                                                                                                         |
| -------------- | ---------------------------------------- | ----- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| A              | `scripts/run_pipeline_real_jintian.py` | 新增  | ~120              | 基于`experiments/run.py baseline`；village_data 自动从 `MinerU_markdown_泗水镇金田村现状报告_*.md` 读入                      |
| B              | `app/agent/explore/bridge_advisor.py`  | 新增  | ~180              | 输出纯自然语言 SpatialCognitionBrief；**不输出 focus_questions**；**不强制 JSON**                                    |
| C              | `app/agent/gis/parse/agent.py`         | patch | ~220              | 新增`extract_bindings(natural_language_reports)`；调 Flash LLM；kgg write-gate 3 重校验                                        |
| D              | `app/agent/analysis/node.py`           | patch | ~50               | `_optimize_semantics` 调 BridgeAdvisor；`_build_prompt` 在 reference materials 位置追加 brief；**不改 L1 prompt 模板** |
| E              | `app/agent/completion/node.py`         | patch | ~30               | Wave 末尾触发`ParseAgent.extract_bindings`                                                                                     |
| F              | ~~删除~~                                | —    | 0                 | 不修改 L1 prompt 模板，不注入 JSON                                                                                               |
| G              | `scripts/verify_explore_kgenrich.py`   | 新增  | ~120              | 端到端验证 + 报告产出                                                                                                            |
| H              | `app/modules/kg/memory.py`             | patch | ~120              | `from_dict` 恢复 + `round_added/valid_*` 字段 + `supersede()` + `diff_round()` + 文件持久化 helpers                      |
| **总计** |                                          |       | **~840 行** |                                                                                                                                  |

### 3.1 执行顺序（依赖）

```
1. H（memory 持久化）             ← 基础设施，最早做
2. B（BridgeAdvisor）              ← 提供空间认知 brief
3. D（analysis/node.py patch）    ← 把 brief 注入 prompt
4. C（ParseAgent.extract）         ← 从报告抽取 binding
5. E（completion 触发 PARSE）      ← Wave 末尾触发
6. A（pipeline runner）            ← 真实数据跑一遍
7. G（verify script）              ← 端到端验证
```

---

## 4. 决策记录（关键 trade-off 与结论）

### 4.1 为什么 brief 是自然语言（不强 JSON）

- L1/L2/L3 报告生成 = **重推理任务**，强制 JSON 损耗 10-15% 准确率
  （Tam et al. NeurIPS 2024 "Let Me Speak Freely?"）
- L3 已有 `GIS_TOOL_GUIDE` 段做"自然语言空间认知注入"（含 `{landuse_metrics_farmland}`
  等），这是已建立的先例，我们沿用
- 解析/抽取 = **轻量任务**，PARSE 端用 JSON 完全可以（research 显示抽取任务
  JSON 无副作用甚至更好）

### 4.2 为什么 brief 不包含 focus_questions

- L1 prompt 模板有严格骨架（land_use 要求"用地结构表 4 行 + 耕地详情 +
  林地详情 + ..."），focus_questions 会**抢注意力**让 LLM 漏填表
- 反例：villager_wishes 固定 4 类诉求，focus_questions 会引导 LLM 编第 5 类
- 结论：brief 只作为"参考事实基座"，不引入新任务

### 4.3 为什么 brief 注入位置在 reference materials

- 现有 L1 prompt 模板：`{knowledge_context}` 和 `{professional_data_section}`
  都在 reference materials 位置
- brief 性质相同（已知事实 / 参考材料）
- 注入位置：`get_layer1_prompt(...)` 调用之后，输出骨架之前
- LLM 看到顺序：原任务指令 → 参考材料（含 brief）→ 写作规则 + 输出骨架
- 不抢 LLM 对原任务的注意力

### 4.4 为什么 PARSE 用 Flash LLM（不用主分析 LLM）

- 主分析 LLM（qwen3.7-plus）用于推理密集任务，PARSE 是抽取任务
- Flash LLM（qwen-flash）便宜 ~10x，抽取准确率足够
- `GIS_EXPLORE_LLM_ENABLED` 默认 ON，可环境关停

### 4.5 为什么只在 Wave 末尾调 PARSE（不是 per-dim）

- per-dim 调用 = 28 次/层，浪费 LLM
- Wave 末尾一次性调 = 1 次/层 × 3 = 3 次
- 所有并行节点已落库，无竞争
- 失败 / 校验失败入 pending_review queue，下次 wave 末尾再尝试

### 4.6 为什么 H 仅做 memory 持久化（不做 DB 表 / 重跑脚本）

- 本次范围最小化
- DB 表方案需要 fastapi + schema 改动，环境约束
- JSON 文件 + `from_dict()` 已能满足"重启不丢"需求
- 重跑脚本核心是 `run_enrich_round.py`，但其核心 API（`extract_bindings`）
  已在本设计中；CLI 包装留给下一轮

### 4.7 为什么 brief 用 LLM 生成而非纯规则

- "田坑 含哪几个 BSM" 需要 LLM 推理：地块分布 + 自然村位置 + 描述文本
- 纯规则（bbox 包含）会漏掉 "田坑南部" 这种方向描述
- 用主分析 LLM 还是 Flash LLM？**Flash LLM**（extract 任务，便宜够用）
- 详细方案在 B 子任务设计

---

## 5. 风险与缓解

| 风险                                     | 缓解                                                                                                |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------- |
| LLM 把 brief 当成新任务                  | prompt 位置在 reference materials，与`{knowledge_context}` 同级；不引入新动词（任务/分析/总结等） |
| PARSE 误绑定（错误 BSM → 错误田坑）     | kgg write-gate 三重校验：KG 存在 + 几何包含 + LLM confidence ≥ 0.6；失败入 pending_review          |
| 跨 wave 并发写 memory                    | Wave 末尾单点触发，所有并行节点已落库；`KGManager._session_versions` 串行                         |
| 重启 memory 丢失                         | H 子任务加 JSON 持久化 +`from_dict()` 恢复                                                        |
| L3 prompt 已有 GIS_TOOL_GUIDE 冲突       | H 不动 L3 prompt；D 仅在 L1 注入；L2/L3 单独处理（如需要）                                          |
| ChunkedMetadata 解析失败（早期方案遗留） | 本设计已撤掉 chunk_metadata；LLM 输出纯文本，PARSE 独立抽取                                         |

---

## 6. 不变量保证

| 不变量                  | 保证方式                                                         |
| ----------------------- | ---------------------------------------------------------------- |
| L1 prompt 模板不动      | D 仅在`get_layer1_prompt(...)` 之后追加 brief 段               |
| 原 LLM 任务指令不被覆盖 | brief 在 reference materials 位置（参考 GIS_TOOL_GUIDE 先例）    |
| 单轮仍能跑（向后兼容）  | H 的`round_added` 默认 = 1，旧 `to_dict` 数据自动兼容        |
| 重启后能恢复            | `from_dict()` + 文件持久化 + `bump_version` 失效 query cache |
| 失败不丢                | supersede 失败 → 入 pending_review；写盘失败 → 抛出 + alert    |
| 不引入新 DB schema      | H 用 JSON 文件，不动`operations.py` / `models.py`            |

---

## 7. 验证标准

### 7.1 阶段 0 单轮验证（G 子任务）

- [ ] A 跑成功 → DB 有 28 份报告（12 L1 + 4 L2 + 12 L3）
- [ ] B 能生成 SpatialCognitionBrief（包含 田坑/黄竹/公王河 等真实地名）
- [ ] D 注入 brief 后 LLM 报告含真实 BSM（如 `44142611020200000563`）
- [ ] E Wave 末尾触发 PARSE
- [ ] C 抽取 binding → 至少 5 条 田坑/黄竹 binding 写入 KG
- [ ] G 端到端验证 + 报告落到 `docs/explore/jintian-kgenrich-{timestamp}.json`

### 7.2 阶段 1 重启持久化（H 子任务）

- [ ] `save_memory_state` 写出 JSON 文件
- [ ] `load_memory_state` 恢复后 `get_entity_semantics(uri)` 返回正确
- [ ] 跨进程：跑完 A → 重启 Python → `load_memory_state` → KG cognition 含田坑

### 7.3 阶段 2 重跑（手动）

- [ ] Round 2 重跑 PARSE（不重跑 LLM）
- [ ] `diff_round()` 输出新 binding 数量 + supersede 数量
- [ ] 收敛检测：新 binding 增量 < 5% → stop

---

## 8. 未来扩展（不在本次范围）

- `run_enrich_round.py` CLI 脚本（手动重跑入口）
- `kg_enrichment_history` DB 表（更结构化的审计日志）
- `diff_kg_rounds.py` 独立可视化脚本
- 一致性报告（ConsistencyReport — L4 校核模式）
- 桥接模式 ExploreFlashAgent.bridge 完整产出 `ExplorationInstructionCollection`
- `spatial_entity_binder.py` + `format_bound_intent.py`（GIS 桥接）

---

## 9. 关联文档

- `docs/design/05_EXPLORE_BRIDGE.md` — EXPLORE 设计主文档
- `docs/design/10_IMPLEMENTATION_STATUS.md` — 实现状态台账（待更新）
- `docs/design/09_INTEGRATION_BREAKPOINTS.md` — 集成断点
- `.opencode/plans/layout-map-generation-20260731.md` — GIS 桥接完整 plan
- stage-0 交付文件：
  - `app/agent/explore/{agent.py, contracts.py, __init__.py}`
  - `app/modules/kg/interface.py`
  - `app/modules/kg/manager.py`（patch）
  - `app/core/settings.py`（patch）
