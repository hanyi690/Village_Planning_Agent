# RAG 模块（动态知识检索与知识库管理）

> 村庄规划知识检索：层级切片 + Small-to-Big 向量检索 + LLM 查询生成，产出可注入 Prompt 的上下文片段。
> **Updated: 2026-08-02**

---

## 一、定位

为分析 Agent 提供**外部知识检索**：根据维度配置（`dim_key`）与当前 Agent 状态，用 Flash LLM 生成检索查询 → 在 Chroma 向量库中做 Small-to-Big 层级检索 → 返回格式化上下文（法规/技术标准/案例片段）。同时承担**知识库管理**：文档入库（增量更新、文件哈希去重）、删除、统计、校验。

> 2026-05-16 重写：集成层级切片（`HierarchySlicer`）；删除旧的 `ParentChildVectorStore` 实现。索引管理逻辑于 2026-05-17 独立到 `context.py`。

---

## 二、目录结构

```
rag/
├── __init__.py                 # 导出 RagService / DocumentSummary
├── service.py                  # ★ RagService：查询生成 + 检索 + 知识库管理
├── chunker.py                  # HierarchyChunk / HierarchySlicer（LLM 大纲矫正 + LangChain 切片 + 缓存）
├── context.py                  # HierarchyTreeIndex / OutlineIndexManager / LLMOutlineCorrector / DocumentContextProvider
├── vector_store.py             # AliyunEmbeddings / VectorStoreCache / HierarchyVectorStore
├── cli.py                      # RAG 知识库管理 CLI（status/delete/reload/verify）
└── utils/
    ├── __init__.py
    ├── document_loader.py      # FileTypeDetector + _create_loader（多文件类型加载）
    └── metadata_extractor.py   # ExtractedMetadata / MetadataExtractor（元数据提取 + LLM doc_type 推断）
```

---

## 三、公开 API

```python
from app.infrastructure.rag import RagService, DocumentSummary

svc = RagService.get_instance()          # 线程安全单例

# 检索（供分析 Agent 使用）
queries = await svc.generate_queries(cfg, state)   # LLM 动态生成 4-8 条查询（分 Layer Prompt）
query   = await svc.generate_query(cfg, state)      # 单条（向后兼容）
results = await svc.search(query, top_k=3, prefer_doc_types=["policy", "standard"])
context = await svc.get_context(dim_key, state, cfg)   # 格式化上下文（含【参考N】来源标注）
text    = RagService.format_for_prompt(results)         # 静态格式化

# 知识库管理
svc.add_document(file_path, category=..., doc_type=..., terrain=...)
await svc.add_markdown_document(file_path, use_llm_inference=True)  # 针对 _doc_md/ 已解析 Markdown
svc.add_document_with_progress(file_path, progress_callback, ...)   # 异步任务进度回调
svc.list_documents() / svc.get_stats() / svc.delete_document(source_name)
```

---

## 四、核心流程

### 1. 查询生成（service.generate_queries）
- 依据 `cfg.phase_id` 判断维度层级（`layer1/2/3`），使用**分 Layer Prompt**：
  - **Layer 1（现状分析）**：侧重技术规范、数据采集方法、评价指标公式；
  - **Layer 2（通用）**：通用检索；
  - **Layer 3（详细规划）**：结合依赖摘要，检索编制标准、政策法规、相似案例；
  - **special case `superior_planning` + layer 1**：专门 Prompt，注入村庄位置（省/市/县/镇结构化字段或正则提取）与 Flash LLM 预处理的上位规划关键词。
- 批量加载依赖报告全文（`ReportStore.get_layer_reports`，避免 N+1）：全文（截断 2000 字符）+ 内容正则提取的指标/核心发现。
- Flash LLM 生成查询（`create_flash_llm(max_tokens=200, temperature=0.3)`）；失败回退 `f"{dim_name} 规划 技术标准"`。
- `_expand_query` 领域同义词扩展（村庄→农村/乡村…），最多 3 条。

### 2. 层级切片（chunker.HierarchySlicer）
```
slice(content) / slice_with_cache(file_path, source_name)
  1. _clean_content 噪声清理
  2. LLMOutlineCorrector.correct → 大纲矫正（标题层级推断）
  3. LangChain MarkdownHeaderTextSplitter → 层级切片（失败回退简单切分）
  4. _fix_orphan_headings 修复空标题节点
```
产物 `HierarchyChunk`：`content / chunk_id / depth(0=文档,1=章,2=节,3=条) / parent_id / ancestors / section_title / metadata`。

### 3. 向量存储（vector_store.HierarchyVectorStore）
- **AliyunEmbeddings**：阿里云 `text-embedding-v4`（OpenAI 兼容格式），批量 10 条/次、输入 8192 tokens（超长二次切分）、限流（`EMBEDDING_RATE_LIMIT_RPS`=25 rps，`EMBEDDING_MAX_CONCURRENT`=10 并发）+ 指数退避重试。
- **Small-to-Big 检索**（`retrieve`）：
  1. 子块向量检索（`k*2` 候选，可选 `doc_type` 过滤，不足时回退补全）→ L2 距离过滤（`RETRIEVE_SCORE_THRESHOLD`=0.7）；
  2. 树形索引（`_tree_indices`，按文档隔离，`OUTLINE_INDEX_DIR/*_index.json`）定位子块；
  3. 占位切片（`is_placeholder` 或 `char_count<50`）→ 合并子块内容（限 `MAX_MERGE_CONTENT_LENGTH`=8000）或沿祖先链找实质内容（`_resolve_via_ancestors`）；
  4. 返回 `content + metadata.ancestors（章节导航）+ parent_section_title + depth + score`。
- 父块缓存 `hierarchy_chunks_cache.json`（`OrderedDict` LRU，上限 2000）。

### 4. 上下文装配（service.get_context）
检索 top-3 → 格式化 `【参考N - doc_type】来源: ...\n内容: ...`。

---

## 五、知识库管理

**入库**（`add_document` / `add_markdown_document`）：
1. 文件哈希（MD5）增量检测：未变 → `skipped`；变化 → 先删旧版再入库。
2. 类型检测：`FileTypeDetector.detect`（pdf/markdown/word/docx/…，`utils/document_loader`）→ loader 加载全文。
3. `_infer_doc_type` 文件名关键词推断（教材/指南/政策/标准/案例/报告），或 `MetadataExtractor` LLM 推断（`add_markdown_document`）。
4. 写临时 MD 到 `OUTLINE_INDEX_DIR` → `HierarchySlicer.slice_with_cache`（缓存索引）。
5. 注入 `doc_type / category / file_hash / terrain` 元数据 → `add_hierarchy_chunks`。
6. 清空查询缓存。

**删除**（`delete_document`）：清向量库（`collection.delete(where={"source": ...})`）+ 内存树索引 + JSON 索引文件 + 临时 MD + 查询缓存。

**CLI**：
```
python -m app.infrastructure.rag.cli status | delete <source> | reload <file.md> | verify <source>
```

---

## 六、关键路径配置（app.core.settings）

| 配置 | 默认值 | 用途 |
|---|---|---|
| `RAG_DOC_DIR` | `data/RAG_doc` | 原始文档 |
| `OUTLINE_INDEX_DIR` | `data/RAG_doc/_cache/outline_index` | 大纲/层级索引 JSON |
| `CHROMA_PERSIST_DIR` | `data/RAG_doc/_cache/chroma_db_new` | 向量库持久化 |
| `CHROMA_COLLECTION_NAME` | `rural_planning` | 向量集合名 |
| `ALIYUN_EMBEDDING_MODEL` | `text-embedding-v4` | Embedding 模型 |
| `RETRIEVE_SCORE_THRESHOLD` | `0.7` | L2 距离过滤阈值 |
| `MAX_MERGE_CONTENT_LENGTH` | `8000` | 子块合并上限 |
| `EMBEDDING_RATE_LIMIT_RPS` | `25` | Embedding 限流 |
| `EMBEDDING_MAX_CONCURRENT` | `10` | Embedding 并发 |

---

## 七、消费方

- 分析 Agent（各 dimension 节点）经 `get_context(dim_key, state, cfg)` 获取知识注入，属**可选增强**——检索失败/无结果返回空串，不阻断主流程。
- CLI / API 层调用知识库管理方法（如文档上传、库状态查询）。
- 与 `services/report_store.py`（依赖摘要来源）配合使用。

---

## 八、相关文档

- `app/modules/kg/README.md` — 与 KG（符号推理）互补：RAG 提供外部文档语义，KG 提供村庄实体关系。
- `app/core/settings.py` — RAG 相关配置
- `app/services/report_store.py` — Layer 报告/摘要存储（查询生成依赖）
