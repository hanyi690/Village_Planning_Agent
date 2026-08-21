# EXPLORE / 证据检索设计

> 模块：`backend/app/evidence/`、`backend/app/infrastructure/rag/`
> 当前实现证据：[10_IMPLEMENTATION_STATUS_CURRENT_20260818.md](../../10_IMPLEMENTATION_STATUS_CURRENT_20260818.md)

| 文档 | 内容 | 状态 |
|---|---|---|
| [05_EXPLORE_BRIDGE.md](05_EXPLORE_BRIDGE.md) | EXPLORE 横向事实与证据探索能力定位 | TARGET |
| [23_EXPLORE_RETRIEVAL_REDESIGN.md](23_EXPLORE_RETRIEVAL_REDESIGN.md) | EXPLORE 检索体系重构：现状、设计、目标最佳 | TARGET |

当前事实：EXPLORE 不是图节点，是 gate 驱动的水平检索服务
（`evidence/retrieval/evidence_service.py`）。统一 EvidenceBundle 内部区分两类文本来源：
`local_text` 检索当前 session 的 bundle 文本、L1 source span、L1/L2/L3 报告；`rag`
只检索专业外部向量语料。二者都可作为规划 LLM 的背景，但 source、作用、可定位性和
向量服务状态必须分开记录。
