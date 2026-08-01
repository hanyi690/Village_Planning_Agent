# v4 实施计划：金田村"产业空间布局规划图"（KG+语义驱动 · 系统内闭环）

## 已确认决策
- 功能区类别：LLM 从 **DB L3 报告**【功能分区表】动态提取（颜色 LLM 自由给）→ session 词汇表（轮内闭集）
- 面图层：L3 报告 4 区功能分区表（生态保护区/农田保护区/村庄建设区/林业发展区）
- 输入全系统内（DB 报告 + KG + bundle，不碰 docs/ 外部文档）
- L1 闭环：扩展现有 wave 末尾钩子（extract_bindings → 实体语义增强）
- L2 纯粹化：移除 intent_targets 注入，L3 自洽（detailed.py 已验证空时降级 N/A）
- PARSE：扩展现有 parse()（结构化表格解析，同一 SpatialPlanningIntent 契约）
- EXPLORE：收缩为 KG 探索（实体提及+候选），加 project 域
- PNG 为主；先面后点（项目点落位二期）

## 任务分解
| # | 任务 | 文件 |
|---|---|---|
| P0 | 词汇表基础设施：register_vocabulary + CustomZoningGenerator 接受 Vocabulary 对象 | `vocabularies/loader.py`、`custom_zone_generator.py` |
| P1 | 移除 L2 intent_targets 注入（保留 L1 _landuse_metrics） | `analysis/node.py` |
| P2 | EXPLORE project 域（ExploreDomain + _DOMAIN_KEYWORDS） | `explore/contracts.py`、`explore/agent.py` |
| P3 | PARSE 表格解析：分区表→ZoneTarget、项目表→项目意图 | `gis/parse/agent.py` |
| P4 | extract_bindings 实体语义增强（分区/项目/约束实体→EntityAnnotation） | `gis/parse/agent.py` |
| P5 | LLM 词汇表提取器：L3 分区表→session Vocabulary（自由色） | 新增 `extract_vocabulary_from_reports` |
| P6 | Binder + format_bound_intent 本地化（handoff）+ CustomZoneTarget | `spatial_entity_binder.py`、`format_bound_intent.py` |
| P7 | EXECUTE 接线 CustomZoningGenerator → custom_functional_zone 双图层 | `execute/agent.py` |
| P8 | render_integrated_map 适配（路径/SID/词汇表图例） | `render_integrated_map.py` |
| P9 | CLI + 端到端验证（含 dispose_async_engine 修进程挂住） | `scripts/run_planning_pipeline.py` |

## 数据流
```
DB village_data → L1×12（KG 认知作输入）→ [wave 钩子: EXPLORE→PARSE→KG 实体语义增强]
  → L2×4（纯粹定位）→ L3×12（自洽：功能分区表/项目库/空间结构）
  → PARSE：表格→intent → LLM 词汇表提取：L3 分区表→session vocab（自由色）
  → Binder：EXPLORE 候选 + KG（ResidentialCluster/村名注解）→ BSM 集
  → EXECUTE：CustomZoningGenerator（三线拦截）→ L4 FunctionalZone（4 区面）
  → render → PNG（图例=词汇表色）
```

## 验收
- P3：分区表→zone_targets 单测；P5：4 区提取+hex 校验；P7：custom_functional_zone 层+三线拦截
- P9 端到端：PNG ≥1920×1080、图例与图面一致、KG L3 可查（FunctionalZone derived_from BSM）、进程正常退出

## 二期（不做）
项目点落位（兼容矩阵）、execute_queries 激活、SpatialReferenceSpec 两段式
