# 文档中心（Docs）

> 本文档体系的导航入口。

## 目录结构

```
docs/
├── design/          # 系统设计（"为什么"）— North Star + 设计展开
├── architecture/    # 技术实现（"在哪里、怎么跑"）
├── reference/       # 参考资料（术语表、参考文献、人工规划流程）
├── audits/          # 审计诊断（架构审计、差距分析、模块边界）
├── proposals/       # 重构提案（未落地）
├── guides/          # 操作指南（添加图层、KG 可视化等）
├── data/            # 数据文档
├── explore/         # EXPLORE/KG 探索产物（JSON 快照）
├── reports/         # 非架构产出（周报、专利）
├── weekly-reports/  # 周报（.docx）
├── superpowers/     # 计划/提案（.md）
├── 参考报告/        # 源村庄规划参考资料
└── _archive/        # 历史归档
```

> `references/`（复数）为 vendored 外部项目/规划资料库（chat2geo、DRL-urban-planning 等），非本项目文档；`RAG 知识库/` 为 RAG 向量库源文档。

## 权威链（Authority Chain）

```
代码 (backend/app/**, frontend/**)          ← 最终事实源
  ↑
design/00_SYSTEM_DESIGN.md                  ← North Star（为什么这么设计）
  ↑
design/01-10_*.md                           ← 设计问题展开
  ↑
architecture/*.md                           ← 技术实现映射
  ↑
README.md（根）                             ← 对外门面（只链接不重复）
```

- `design/` 回答**为什么**这么设计
- `architecture/` 回答代码**在哪里、怎么跑**
- `audits/` 和 `proposals/` 为诊断参考和未落地提案，**不参与**权威链

## 快速导航

| 我想... | 去哪里 |
|--------|--------|
| 理解系统设计理念 | [design/00_SYSTEM_DESIGN.md](./design/00_SYSTEM_DESIGN.md) |
| 看项目结构与实现总览 | [architecture/structure.md](./architecture/structure.md) |
| 看主图怎么跑 | [architecture/agent-graph.md](./architecture/agent-graph.md) |
| 查 API 端点 | [architecture/backend-api.md](./architecture/backend-api.md) |
| 了解前端架构 | [architecture/frontend.md](./architecture/frontend.md) |
| 查术语定义 | [reference/terminology.md](./reference/terminology.md) |
| 看闭环管线设计 | [design/04_PLANNING_PIPELINE.md](./design/04_PLANNING_PIPELINE.md) |
| 看 EXPLORE 桥接 | [design/05_EXPLORE_BRIDGE.md](./design/05_EXPLORE_BRIDGE.md) |
| 看实现状态 | [design/10_IMPLEMENTATION_STATUS.md](./design/10_IMPLEMENTATION_STATUS.md) |
| 看集成断点 | [design/09_INTEGRATION_BREAKPOINTS.md](./design/09_INTEGRATION_BREAKPOINTS.md) |

## design/ 文档索引

| 文档 | 内容 |
|------|------|
| [00_SYSTEM_DESIGN.md](./design/00_SYSTEM_DESIGN.md) | North Star 总体设计 |
| [01_LAYERED_ARCHITECTURE.md](./design/01_LAYERED_ARCHITECTURE.md) | 分层架构 |
| [02_DATA_PERSISTENCE.md](./design/02_DATA_PERSISTENCE.md) | 数据持久化 |
| [03_KG_SEMANTIC_BRIDGE.md](./design/03_KG_SEMANTIC_BRIDGE.md) | KG 语义桥接 |
| [03-kg-spatial-cognition-supplement.md](./design/03-kg-spatial-cognition-supplement.md) | KG 空间认知补充 |
| [04_PLANNING_PIPELINE.md](./design/04_PLANNING_PIPELINE.md) | 闭环规划管线 |
| [05_EXPLORE_BRIDGE.md](./design/05_EXPLORE_BRIDGE.md) | EXPLORE 桥接层 |
| [06_PARSE_EXECUTE.md](./design/06_PARSE_EXECUTE.md) | PARSE + EXECUTE |
| [07_VALIDATION_FEEDBACK.md](./design/07_VALIDATION_FEEDBACK.md) | 校验与反馈 |
| [08_DELIVERABLES_COMPLIANCE.md](./design/08_DELIVERABLES_COMPLIANCE.md) | 成果合规 |
| [09_INTEGRATION_BREAKPOINTS.md](./design/09_INTEGRATION_BREAKPOINTS.md) | 集成断点 |
| [10_IMPLEMENTATION_STATUS.md](./design/10_IMPLEMENTATION_STATUS.md) | 实现状态 |
| [11_EXPLORE_KG_ENRICHMENT.md](./design/11_EXPLORE_KG_ENRICHMENT.md) | EXPLORE KG 富化 |

## architecture/ 文档索引

| 文档 | 内容 |
|------|------|
| [README.md](./architecture/README.md) | 架构文档导航 |
| [structure.md](./architecture/structure.md) | 项目结构与实现总览 |
| [agent-graph.md](./architecture/agent-graph.md) | 当前主图与目标分层子图 |
| [backend-api.md](./architecture/backend-api.md) | 后端 API + SSE |
| [frontend.md](./architecture/frontend.md) | 前端架构 |
| [rag-system.md](./architecture/rag-system.md) | RAG 知识检索 |

## 迁移说明

> 本文档体系于 **2026-07-31** 重构，旧路径见 [`_archive/`](./_archive/)。
