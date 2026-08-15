# EXPLORE / 证据检索设计

> 模块：`backend/app/evidence/`、`backend/app/infrastructure/rag/`
> 实现盘点：[24_MODULE_OUTPUT_INVENTORY.md](../../24_MODULE_OUTPUT_INVENTORY.md)

| 文档 | 内容 | 状态 |
|---|---|---|
| [05_EXPLORE_BRIDGE.md](05_EXPLORE_BRIDGE.md) | EXPLORE 横向事实与证据探索能力定位 | TARGET |
| [23_EXPLORE_RETRIEVAL_REDESIGN.md](23_EXPLORE_RETRIEVAL_REDESIGN.md) | EXPLORE 检索体系重构：现状、设计、目标最佳 | TARGET |

当前事实：EXPLORE 不是图节点，是 gate 驱动的水平检索服务
（`evidence/retrieval/explore_service.py`）；RAG（`infrastructure/rag/`）与 EXPLORE
（`evidence/retrieval/evidence_service.py`）是两套并行证据来源。