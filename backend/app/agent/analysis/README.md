# agent/analysis 子包（维度分析）

> L1/L2/L3 三层维度分析节点：DataPipeline 工具编排 + RAG 检索 + EXPLORE 空间认知 + 流式 LLM + 结构化摘要，报告即时落库。
> **Updated: 2026-08-02**

---

## 一、定位

主图 `analyze_dimension` 节点的实现。被 LangGraph `Send` API 并行分发（每维度一个实例），执行"配置 → 工具 → RAG → 依赖 → Prompt → 流式生成 → 摘要 → 落库 → 状态更新"全流程。

---

## 二、目录结构

```
analysis/
├── __init__.py        # 导出 analyze_dimension / DIMENSION_NAMES
├── node.py            # ★ analyze_dimension（970 行）+ Prompt 组装 + 依赖加载 + 语义优化
├── pipeline.py        # DataPipeline：统一工具执行管线（TOOL_REGISTRY 分发）
└── formatters.py      # generate_professional_data_section（工具结果 → Prompt 文本）
```

---

## 三、分析流程（analyze_dimension，11 步）

```
1. 配置获取（get_dimension_config，缺失返回错误消息）
2. SSE DIMENSION_START
3. RAG 并行（_run_rag）：
   - 从 checkpoint 读最新 config（Send 冻结快照，须重读 PATCH）
   - rag_layer_config[layer] & rag_enabled 双开关 + cfg.rag_query 才启用
   - 修订场景走 knowledge_cache 缓存命中；否则 LLM 生成多查询（跨维度查询缓存去重）
   - 检索合并去重（content 前缀）、过滤纯标题切片、SSE RAG_RESULT
4. 依赖加载（DB 轮询）：
   - 同层依赖：轮询 get_latest（max 30s 修订 / 120s 常规）+ get_latest_report 回退；失败抛 DependencyError
   - 跨层：L2 依赖 L1、L3 依赖 L1+L2（顺序调用避免 SQLite 连接问题）
5. DataPipeline 工具执行（dim_layer>=2 且配置了 tools）：
   - 从依赖维度加载结构化摘要 → get_dimension_schema 校验 → merged_metrics（state["_dep_metrics"]）
   - get_professional_data → formatters 格式化
5.5 EXPLORE 空间认知（_optimize_semantics → build_spatial_cognition，L1/L2/L3 均注入；land_use/superior_planning 附编码候选集提示）
5.6 EXPLORE brief（_build_explore_brief → BridgeAdvisor.compose_dim_brief，L1 注入 reference 位置）
6. 组装 Prompt（_build_prompt，按层选模板，P8 注入自然村名单）
7. 流式 LLM + SSE（100ms 节流 DIMENSION_DELTA；超时 LLM_STREAM_TIMEOUT → 错误）
8. 结构化摘要（_generate_summary → modules.parsing.summary_generator）
9. 准备 pending_report（批次写库缓冲）+ DIMENSION_COMPLETE SSE
10. 状态更新（messages + completed_dimensions + pending_reports + layer_char_counts；L1 注入 _landuse_metrics）
11. 立即落库（bulk_save，并行节点可从 DB 回退路径取依赖）
```

---

## 四、关键细节

- **P0-1 数据流闭环**：L1 完成后 `_extract_landuse_metrics` 提取现状用地指标（land_use 优先 → superior_planning 约束下限 → ecological）注入 `_landuse_metrics`；L3 Prompt 消费（`GIS_TOOL_GUIDE`）。
- **L2 纯粹化（v4）**：L2 只产规划定位，不再注入 `intent_targets` 面积意向（L3 自洽）。
- **修订**：级联修订时注入「级联修订指令」前缀（独立参数）；完成后回写 `revision_completed_dims` + `revision_impact_tree`（fan-in 保留）。
- **P8 自然村名单**：`_extract_natural_villages` 从 L1 socio_economic 报告提取已知 12 村闭集（`kg.enrichment.bindings._KNOWN_NATURAL_VILLAGES`），注入 L3 INSTRUCTION 位置列引导。
- **Prompt 选择**：`prompts.analysis`（L1）/ `prompts.concept`（L2）/ `prompts.detailed`（L3）。
- **数据安全**：LLM 失败/超时返回错误消息 + SSE，不崩溃图。

---

## 五、输入输出契约

```
输入:  state（含 dimension_key / session_id / config / completed_dimensions / is_revision / revision_*）

输出:  messages（AIMessage = 报告全文，metadata.dimension_key）
       completed_dimensions: {layerN: [dim_key]}
       pending_reports: [{session_id, dimension_key, layer, version, report_id,
                          content, summary, revision_trigger, knowledge_sources, generated_at}]
       layer_char_counts: {layer: chars}
       _landuse_metrics: {farmland_ha, construction_ha, ecological_ha}（L1）
       revision_completed_dims / revision_impact_tree（修订时）
```

报告立即写入 `ReportStore`；`completion` 节点负责批次兜底写入与层级推进。

---

## 六、相关文档

- `../README.md` — 主图与编排
- `../explore/README.md` — 空间认知（KG 语义 / brief）
- `app/modules/prompts/README.md` — 三层 Prompt 模板
- `app/modules/parsing/README.md` — 结构化摘要生成
- `app/tools/` — TOOL_REGISTRY 工具层
