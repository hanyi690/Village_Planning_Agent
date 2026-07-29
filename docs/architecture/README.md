# 架构文档导航

本目录包含 Village Planning Agent 系统的架构文档。

> **更新日期**: 2026-07-29（归档重组）
> **模块结构**: `app/modules/{schema,data,spatial_ops,kg}` 四层架构

---

## 文档结构

```
docs/architecture/
├── README.md                                    # 本文档 — 导航入口
│
├── core/                                        # 核心架构（6篇）
│   ├── 05-frontend-state.md                     # 前端状态管理（唯一前端架构文档）
│   ├── 01-system-overview.md                    # [DEPRECATED] 系统总览
│   ├── 02-agent-core.md                         # [DEPRECATED] Agent 核心
│   ├── 03-layer-dimension.md                    # [DEPRECATED] 维度配置
│   ├── 04-backend-api.md                        # [DEPRECATED] 后端 API
│   └── 06-tool-system.md                        # [DEPRECATED] 工具系统
│
├── infrastructure/                              # 基础设施（4篇）
│   ├── 08-rag-system.md                         # RAG 知识检索系统
│   ├── 10-deployment-guide.md                   # 配置与部署指南
│   ├── 09-database-schema.md                    # [DEPRECATED] 数据库 Schema
│   └── 12-error-handling.md                     # [DEPRECATED] 错误处理
│
├── quality/                                     # 质量保障（2篇）
│   ├── 13-performance.md                        # [DEPRECATED] 性能优化
│   └── 14-testing.md                            # [DEPRECATED] 测试架构
│
├── reference/                                   # 参考资料（3篇）
│   ├── terminology.md                           # 术语表
│   ├── gis-cross-reference.md                   # GIS 子系统交叉引用
│   └── file-index.md                            # [DEPRECATED] 文件路径索引
│
├── explorations/                                # 探索方案（1篇）
│   └── RAG_DIFFERENTIATED_CHUNKING_AND_RETRIEVAL.md
│
└── archive/                                     # 历史归档（1篇）
    └── 10-frontend-components.md                # 已被 05 覆盖
```

> 标记 `[DEPRECATED]` 的文档已添加过时警告横幅。当前架构以本文档和模块 README 为准。

---

## 核心架构概览

### 目录结构

```
village-planner/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── api/                 # API 路由层
│   │   ├── agent/               # LangGraph Agent
│   │   │   ├── graph.py         # StateGraph 定义
│   │   │   ├── state.py         # AgentState 定义
│   │   │   ├── routing.py       # 路由逻辑
│   │   │   ├── nodes/           # 节点实现
│   │   │   └── gis/             # GIS Agent (PARSE + EXECUTE)
│   │   ├── config/              # 配置层
│   │   ├── core/                # 核心基础设施
│   │   ├── database/            # 数据持久层
│   │   ├── modules/             # 业务模块（四层架构）
│   │   │   ├── schema/          # 类型契约层（零依赖）
│   │   │   │   ├── types/       # Pydantic v2 类型化模型 + layer_registry
│   │   │   │   ├── encodings/   # 编码体系（6 套 YAML + DictionaryCenter）
│   │   │   │   ├── contracts/   # 跨层契约
│   │   │   │   └── output/      # 汇交输出（gdb/tables/colors）
│   │   │   ├── data/            # 数据获取与管理层
│   │   │   │   ├── catalog/     # DataCatalog + sources.yaml
│   │   │   │   ├── sources/     # DataSourceDriver
│   │   │   │   ├── connections/ # API 连接管理
│   │   │   │   ├── adapters/    # Ingest adapters
│   │   │   │   └── ingest.py    # raw → typed models
│   │   │   ├── spatial_ops/     # 空间分析层（shapely/geopandas）
│   │   │   │   ├── geometry.py  # 几何计算
│   │   │   │   ├── bridge.py    # ConstraintIndex + 跨类型关系
│   │   │   │   └── context.py   # ContextBlock 计算
│   │   │   └── kg/              # 知识图谱层（rdflib）
│   │   │       ├── builder/     # @kg_builder 注册表 + PlanningKG
│   │   │       ├── queries/     # SPARQL + semantic + cognition
│   │   │       ├── ontology.py  # PLN/GEO 命名空间 + EntityTypes
│   │   │       ├── manager.py   # KGManager（三层缓存）
│   │   │       └── memory.py    # SemanticMemoryStore
│   │   ├── services/            # 服务层
│   │   ├── tools/               # 工具层
│   │   └── utils/               # 工具函数
│   └── schemas.py
│
├── frontend/
│   └── src/
│       ├── app/                 # Next.js App Router
│       └── features/
│           └── planning/        # 规划功能模块
│               ├── api/         # API 客户端
│               ├── components/  # React 组件
│               ├── hooks/       # React Hooks
│               ├── store/       # Zustand Store
│               ├── types/       # TypeScript 类型
│               └── utils/       # 工具函数
│
├── data/
│   ├── RAG_doc/                 # 知识库文档与缓存
│   └── gis/                     # GIS 数据
│
├── docs/
│   ├── architecture/            # 架构文档（本目录）
│   └── gis/                     # GIS 子系统设计文档
│
└── tests/
```

---

## 快速导航

| 文档 | 核心内容 | 状态 |
|------|----------|------|
| [core/05-frontend-state](./core/05-frontend-state.md) | Zustand、三栏布局、SSE 批处理 | 活跃 |
| [infrastructure/08-rag-system](./infrastructure/08-rag-system.md) | 知识检索、层级切片、Small-to-Big | 活跃 |
| [infrastructure/10-deployment-guide](./infrastructure/10-deployment-guide.md) | 配置部署、Docker、LLM（qwen3.5-plus） | 活跃 |
| [reference/terminology](./reference/terminology.md) | 术语定义、SSE 事件类型、命名约定 | 活跃 |
| [reference/gis-cross-reference](./reference/gis-cross-reference.md) | GIS 子系统入口索引 | 活跃 |

> `[DEPRECATED]` 文档仅作历史参考，包含技术决策演进记录。

---

## 关键设计决策

| 决策 | 结论 | 确认日期 |
|------|------|----------|
| 默认 LLM | qwen3.5-plus（阿里云 DashScope） | 2026-07-29 |
| 前端架构文档 | 以 `05-frontend-state.md` 为唯一来源 | 2026-07-29 |
| 版本体系 | 放弃独立版本号，统一用日期标记 | 2026-07-29 |
| 模块路径 | `app/modules/{schema,data,spatial_ops,kg}` | 持续 |

---

## 相关资源

- [GIS 子系统文档](../gis/INDEX.md) — GIS 设计、审计、集成、重构提案
- [术语表](./reference/terminology.md) — 所有术语定义
- [GIS 交叉引用](./reference/gis-cross-reference.md) — architecture ↔ gis 桥梁
