# 当前 RAG 实现

> 本文只描述当前 RAG 入口和边界；分层检索、差异化 chunking 等方案仍属于专题设计或
> 提案，不能在本文写成已启用能力。

## 1. 代码入口

```text
backend/app/infrastructure/rag/
├── cli.py              管理命令
├── service.py          检索服务
├── context.py          查询上下文
├── chunker.py          文档切分
├── vector_store.py     向量存储适配
└── utils/              文档加载和元数据
```

RAG 由 L1/L2/L3 运行时按配置选择性调用；它只提供专业外部文档证据，不拥有规划事实、
空间决策或工作流状态。KG、Bundle、报告和空间查询是不同的证据来源，不能因为都进入
prompt 就当作同一存储。会话内文本的无向量检索由
`backend/app/evidence/retrieval/retrievers/local_text_retriever.py` 负责，不属于 RAG。

## 2. 管理命令

在仓库根目录按当前 Python 环境运行：

```powershell
python -m app.infrastructure.rag.cli status
python -m app.infrastructure.rag.cli reload <file_path>
python -m app.infrastructure.rag.cli verify <source_name>
python -m app.infrastructure.rag.cli delete <source_name>
```

命令的参数和返回以 `backend/app/infrastructure/rag/cli.py` 为准；本文不复制完整 CLI
帮助文本。

## 3. 边界和状态

- 文档加载、切分、embedding 和向量检索属于 infrastructure adapter。
- 结果必须带 source/metadata，供上层写入 evidence/provenance。
- RAG 结果可以支持分析，不能直接生成 `PlanningProgram`、分类、坐标或 `ParcelChange`。
- 没有命中、来源冲突、provider 不可用或索引过期必须显式报告；不能用空结果冒充“没有证据”。
- 向量服务到期/不可用时，`rag` 只产生 `external_rag_unavailable` 状态；本地 bundle、KG、
  L1、L2/L3 报告检索仍独立运行，不能把本地结果标记为 `rag`。
- 当前 RAG 与 KG/evidence 的完整跨阶段血缘仍是 `PARTIAL`，以状态台账为准。

## 4. 相关文档

- 目标证据边界：[design/05_EXPLORE_BRIDGE.md](../design/modules/explore/05_EXPLORE_BRIDGE.md)
- KG 与空间桥接：[design/03_KG_SEMANTIC_BRIDGE.md](../design/modules/kg-place/03_KG_SEMANTIC_BRIDGE.md)
- 当前证据状态：[design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md](../design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md)
