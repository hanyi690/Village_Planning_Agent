# Operations

> Status: CURRENT
> Authority: Current local startup, configuration categories, health/degradation behavior and verification entry points.

## 1. Local startup

仓库根 README 给出的当前最短启动方式是：

```powershell
pip install -r requirements.txt
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端从 `frontend/` 使用其 package manifest 安装依赖并运行 `npm run dev`。后端就绪检查使用 `/health` 和 `/api/health`；真实返回字段以 OpenAPI/代码为准。

启动时 FastAPI lifespan 初始化 composition、runtime graph、artifact/event 依赖和其他资源。初始化证据见 [`backend/app/bootstrap/lifespan.py`](../../backend/app/bootstrap/lifespan.py) 与 [`composition.py`](../../backend/app/bootstrap/composition.py)。

## 2. Configuration categories

运维配置按责任分组，不在本文复制 secret 或完整环境变量表：

- application/API：host、port、CORS、logging；
- persistence：database、checkpoint、artifact/event stores；
- LLM providers：provider、model、endpoint、credentials、timeouts/rate limits；
- professional RAG/embedding：corpus/cache、provider/model、opt-in 和连接参数；
- evidence/external search：允许的来源、预算、timeout；
- spatial/KG：数据快照、CRS、KG/bundle 构建和查询 adapter；
- workflow：重试、HITL、validation/replay budgets。

配置读取以 `backend/app/core/settings.py`、`backend/app/config/` 和 composition code 为准。文档不得包含真实 key。

## 3. RAG and embedding health

professional RAG 当前通过 [`backend/app/infrastructure/rag/service.py`](../../backend/app/infrastructure/rag/service.py) 和 [`vector_store.py`](../../backend/app/infrastructure/rag/vector_store.py) 使用外部 embedding；provider 未配置、额度到期或显式未 opt-in 时 dense recall 不可用。RAG retriever 会记录可用性日志。

这不应关闭整个检索系统。当前独立的 local text、report、KG、bundle、artifact/history retrievers 位于 [`backend/app/evidence/retrieval/`](../../backend/app/evidence/retrieval/)。运行日志和诊断必须区分：

```text
professional_rag_available
embedding_available
local_text_available
kg_available
bundle_available
external_search_available
```

如果 embedding 暂时失效，允许继续结构化、词法、本地报告、KG 和空间证据路径；结果必须标注 dense 通道缺失，不得声称与全通道同等召回。不得用外部 web 静默替代项目内 authoritative geometry。

## 4. Degraded operation

| Failure | Allowed behavior | Forbidden behavior |
|---|---|---|
| embedding/RAG unavailable | 继续 local/report/KG/bundle/artifact；记录 coverage 风险 | 把整个 evidence 写成空，或假称完整 |
| external search unavailable | 使用本地来源并报告 external requirement unavailable | 伪造最新政策或缓存日期 |
| KG unavailable | 使用显式 bundle IDs/attributes；保留语义歧义 | 从名称直接创造 geometry |
| bundle/snapshot unavailable | 停止可执行 grounding | 用报告文字或 RAG 生成坐标 |
| solver timeout | 返回 bounded/timeout certificate 和已有可行方案 | 把当前最好值宣称 optimal |
| worker failure | 中止正式原子提交，保留诊断 | 部分提交后继续正式交付 |
| validation failure | 路由到责任阶段或人工门 | 由 validator 静默修复 |

LLM structured-output 诊断必须区分 context overflow、output truncation、missing tool call、schema invalid 和 timeout。MiniMax M2.7 OpenAI-compatible 调用不得把“没有 tool call”解释为 token 超限；structured path 使用 `reasoning_split=true`，只有明确 `finish_reason=length` 才允许一次有界扩容。日志、SSE 和 workflow failure 只记录稳定错误码与异常类型，不记录 provider 正文或 reasoning。

## 5. Tests and diagnostics

快速契约/核心检查：

```powershell
python -m pytest backend/tests/contracts backend/tests/core -q
```

端到端检查：

```powershell
python -m pytest backend/tests/e2e -q
```

针对文档收敛：

```powershell
cd backend
pytest -q -o addopts='' tests/contracts/test_documentation_convergence.py
```

测试通过只证明对应范围。涉及地图、resume、RAG 退化、solver 或正式交付时，还需要固定 snapshot 的 integration/e2e artifact 和目标 benchmark 指标。

## 6. Operational release gate

发布前至少核验：配置无 secret 泄漏；OpenAPI/SSE schema 与代码一致；embedding-off 路径可诊断；checkpoint/resume 幂等；artifact lineage 可查询；失败不会生成正式 delivery；目标链新增契约均有 migration/compatibility test。完整质量门见 [`04_EVALUATION_AND_ACCEPTANCE.md`](../design/04_EVALUATION_AND_ACCEPTANCE.md)。
