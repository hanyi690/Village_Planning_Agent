# 项目结构与实现（Project Structure & Implementation）

> 回答"整个项目怎么组织、各部分实现在哪里"。这是 `docs/` 下的**结构总览**，是代码与各模块 README 之间的导航层。
> 结构变更后请同步更新本文档与根 `README.md` 的目录树。
> **Updated: 2026-08-03**（同步 2026-08-03 死代码清理：移除废弃 legacy GIS 构建器、`backend/scripts/`、多个零引用模块）

---

## 一、顶层布局

```
Village_Planning_Agent/
├── backend/            # FastAPI + LangGraph 后端（Python 3.13+）
├── frontend/           # Next.js 14 + React + MapLibre 前端
├── data/               # RAG 源文档（data/policies/）+ GIS 数据（data/gis/）
├── docs/               # 文档体系（见 docs/README.md）
├── scripts/            # 数据获取/知识库导入脚本（fetch_nrsis/ingest_standards/query_kg 等）
├── output/             # 运行产出（GIS 图层 / 预览 PNG / 导出文件，按 session 写入）
├── logs/               # 运行日志（planning.log / planning.error.log，按日轮转）
├── requirements.txt    # 后端依赖
├── docker-compose.yml  # 容器编排（后端 8003 / 前端 3003）
└── README.md           # 对外门面（只链接不重复）
```

> `backend/scripts/`（一次性诊断脚本）已于 2026-08-03 移除；根目录 `scripts/`（数据/知识库工具）保留。

---

## 二、后端分层架构

**五层模块单向依赖**（`app/modules/`）+ 三个横向粘合层：

```
                    ┌──────────────────────────────────────┐
                    │  Agent 编排层  app/agent/ (LangGraph) │
                    │  conversation → analyze / tools /    │
                    │  explore / gis_agent → completion    │
                    └───────────────┬──────────────────────┘
                                    │ 调用
        ┌───────────────────────────┼───────────────────────────┐
        │                           ▼                           │
   ┌────┴─────┐             ┌───────────────┐           ┌────────┴───────┐
   │ services │             │   modules/    │           │    api/       │
   │ 业务服务  │◄───────────►│ 五层业务模块    │◄─────────►│  HTTP 入口     │
   │ 粘合层    │             │               │           │  (FastAPI)    │
   └────┬─────┘             └───────────────┘           └────────┬───────┘
        │                                                        │
   ┌────┴─────┐              ┌───────────────┐              ┌────┴───────┐
   │ database │              │   core/       │              │   tools/  │
   │ SQLModel │              │ LLM/SSE/Trace │              │ 工具系统    │
   └──────────┘              └───────────────┘              └────────────┘
```

### 五层模块（`app/modules/`，依赖方向 `schema → data → spatial_ops → kg`，`rag` 横向）

| 层 | 目录 | 定位 | 关键文件 |
|----|------|------|----------|
| ① 类型契约 | `schema/` | 四种形态（vector/raster/table/document）类型模型 + 编码系统（DLBM/GHYTBM/TUGUI/VNE）+ `layer_registry.yaml` SSOT | `types/`, `encodings/`, `contracts/` |
| ② 数据获取 | `data/` | Catalog/Source/Connection 三层 + 5 内置 IngestAdapter + providers（amap/baidu/tencent/tianditu/osm） | `catalog/`, `adapters/`, `providers/`, `sources/` |
| ③ 空间分析 | `spatial_ops/` | 唯一允许空间计算的地方：grounding/bridge/constraint_compiler/parcel_ops/land_balance/road_planner | `grounding.py`, `bridge.py`, `map_layers.py` |
| ④ 知识图谱 | `kg/` | RDF 图 + SemanticMemoryStore 双态；4 层构建（L1 实体/L2 关系/L3 意图/L4 规划）+ 查询 API | `builder/`, `queries/`, `service.py`, `interface.py` |
| (横向) 检索 | `rag/` | HierarchicalSlicer + Small-to-Big 检索 + ChromaDB + `RagService` | `service.py`, `chunker.py`, `vector_store.py` |
| (辅助) 文本 | `parsing/` | 文本→结构化工具集（表格/摘要/地名/行政区划/语义） | `tables.py`, `summary_generator.py`, `gazetteer.py` |
| (辅助) 生成 | `planning_text/` | 22 条规划文本生成 + 导出（MD/JSON/DOCX）+ RAG 附录 | `generator.py`, `section_builder.py`, `llm_styler.py` |
| (辅助) 模板 | `prompts/` | L1/L2/L3 分层 Prompt + PARSE 保留模板 | `analysis.py`, `concept.py`, `detailed.py` |

### 编排与入口层

| 目录 | 定位 | 关键文件 |
|------|------|----------|
| `api/` | HTTP 入口：session 核心 API + GIS 开发测试 + 天地图瓦片代理 | `routes.py`, `session_routes.py`, `gis_test_routes.py`, `schemas.py` |
| `services/` | 会话级业务服务（SSE 管理器/运行时/检查点/报告/快照）+ 道路规划服务 | `sse.py`, `runtime.py`, `checkpoint.py`, `report_store.py`, `modules/gis/road/` |
| `agent/` | LangGraph 主图（6 节点）+ 各子 Agent | `graph.py`, `routing.py`, `state.py` + `conversation/ analysis/ explore/ completion/ gis/` |
| `tools/` | 工具系统（registry + access/gis 工具包 + intent 工具） | `registry.py`, `tools.py`, `intent_tools.py`, `access/`, `gis/` |
| `core/` | 全局基础设施（LLM 工厂 / SSE 事件 / LangSmith 追踪 / 环境配置） | `llm.py`, `events.py`, `tracing.py`, `settings.py` |
| `config/` | 领域配置（`phases.yaml` 28 维度 + 依赖/波次计算） | `phases.yaml`, `loader.py`, `dependency.py` |
| `database/` | 异步 SQLite 持久层（SQLModel + aiosqlite，WAL） | `engine.py`, `models.py`, `operations.py` |
| `utils/` | 通用工具（GeoJSON/坐标/文档加载/SSE/日志/重试） | `geojson_utils.py`, `geo_utils.py`, `document_loader.py`, `logger.py` |

---

## 三、LangGraph 主图（6 节点）

`create_unified_planning_graph()`（`backend/app/agent/graph.py`）构建 6 节点主图：

```
START → conversation ──► analyze_dimension ──► layer_completion_check ──► (Send) analyze_dimension ...
              │                ▲                          │
              ├─► execute_tools─┘                          ├─► explore ──► gis_agent ──► END
              ├─► gis_agent ──► END                       └─► conversation / END
              └─► END (闲聊/问答)
```

| 节点 | 实现 | 职责 |
|------|------|------|
| `conversation` | `conversation/node.py` | 中央路由（LLM 绑工具，推进意图/工具/回复） |
| `execute_tools` | `tools/execute_node.py` | 并行执行非路由工具 + SSE |
| `analyze_dimension` | `analysis/node.py` | L1/L2/L3 维度分析（RAG + KG + DataPipeline + LLM 流式） |
| `layer_completion_check` | `completion/node.py` | 层完成检测 + step_mode interrupt + bundle 快照 + KG enrichment |
| `explore` | `explore/node.py` | EXPLORE 认知引擎（phase=completed 时触发一次，产出概要索引/指令） |
| `gis_agent` | `graph.py` | PARSE（规则解析）+ LAYOUT（确定性管线）+ SSE 推送 |

详见 [`agent-graph.md`](agent-graph.md) 与 `backend/app/agent/README.md`。

---

## 四、一次完整规划会话的实现路径

```
POST /api/sessions
  → api/session_routes.py（上传解析入库）
  → services/runtime.py::PlanningRuntimeService.start_session
      → graph.astream（6 节点主图）
          → L1 现状分析（12 维并行 Send）
          → L2 规划思路（4 维波次）
          → L3 详细规划（12 维波次，P8 INSTRUCTION 段）
          → layer_completion_check（快照 + KG enrichment）
          → explore（EXPLORE 桥接，仅非 step_mode）
          → gis_agent（PARSE → LAYOUT → 图层）
      → services/sse.py 推送全部事件
  → services/report_store.py 持久化报告
  → modules/planning_text 生成 22 条规划文本（DOCX 导出）
```

数据流链路（模块间）：

```
api/session_routes ──► services/runtime ──► agent/graph（主图）
   │                        │
   ▼                        ▼
database/operations   modules/parsing（摘要/表格）
   ▲                        │
   └── services/report_store┘
                              │
                              ▼
              modules/schema（契约） ◄── modules/data（获取） ◄── modules/spatial_ops（空间计算）
                              │                                        ▲
                              ▼                                        │
                        modules/kg（KG 桥接）◄──────────────────────────┘
                              │
                              ▼
                        agent/gis（PARSE + LAYOUT + EXECUTE）
                              │
                              ▼
                        services/sse（SSE 推前端）
```

---

## 五、实现状态要点

| 领域 | 状态 | 说明 |
|------|------|------|
| 主图 | 6 节点 | EXPLORE 已提升为主图节点（2026-08 完成） |
| PARSE | 规则解析器 | 确定性解析（`agent/gis/parse/agent.py`），非 ReAct；LLM 增强经 `GIS_PARSE_LLM_ENABLED` 门控 |
| EXECUTE | P1 完成 | Worker-Evaluator 7 节点图 + MIP 分配 + 道路 Stage 0-6 |
| KG | v5.0 | 4 层构建 + SemanticMemoryStore 双态 + GeoSPARQL 对齐 |
| 道路规划 | 两套引擎 | `spatial_ops/road_planner.py`（execute/agent 用）与 `services/modules/gis/road/planner.py`（execute/road 用），已知重复，未合并 |
| 报告 | 版本化 | `dimension_reports` 表 + P8 INSTRUCTION 分离 + 时间旅行 |

---

## 六、README 导航

各层/模块均有 README，作为本文档的细粒度展开：

| 层/模块 | README |
|---------|--------|
| Agent 主图 | [`backend/app/agent/README.md`](../../backend/app/agent/README.md) |
| GIS Agent | [`backend/app/agent/gis/README.md`](../../backend/app/agent/gis/README.md) |
| PARSE / EXECUTE | [`../../backend/app/agent/gis/parse/README.md`](../../backend/app/agent/gis/parse/README.md) / [`../../backend/app/agent/gis/execute/README.md`](../../backend/app/agent/gis/execute/README.md) |
| 五层模块 | `backend/app/modules/{schema,data,spatial_ops,kg,rag}/README.md` |
| 服务层 | [`backend/app/services/README.md`](../../backend/app/services/README.md) |
| API 层 | [`backend/app/api/README.md`](../../backend/app/api/README.md) |
| 配置/核心/数据库 | `backend/app/{config,core,database}/README.md` |

> 各模块 README 与本文档共同构成"结构 → 模块 → 文件"的三级导航链。
