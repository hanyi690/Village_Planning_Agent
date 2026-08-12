# RAG Utils — 文档加载与元数据提取

> **定位**：RAG 模块的内部小工具——文档加载 shim 与元数据提取。**短工具目录，无领域逻辑**。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：
- `document_loader.py`：shim，重导出 `app.utils.document_loader`（`FileTypeDetector` / `MarkItDownLoader` / `MarkdownCleaner` 等），供 rag 模块内部与旧 `services/modules/rag/service.py` 使用
- `metadata_extractor.py`：从文件路径/文件名/内容提取元数据（目录分类、序号与标题、Markdown 解析器信息），并用 Flash LLM 推断 `doc_type`

**不负责**：
- 不做向量检索 / 切片 / 索引（那是 `rag/` 根模块：`service.py` / `chunker.py` / `vector_store.py`）
- 不做知识库管理

---

## 输入/输出契约

**导出**（`rag/utils/__init__.py`）：`MetadataExtractor` / `ExtractedMetadata` / `CATEGORY_MAPPING`。

| 文件 | 入口 | 输出 |
|---|---|---|
| `metadata_extractor.py` | 文件路径 + 内容 | `ExtractedMetadata`（category / subcategory / sequence / title / doc_type） |
| `document_loader.py` | 文件/目录 | 加载器实例（shim 转发） |

---

## 依赖方向

```
rag/utils/ → app.utils.document_loader、app.core.settings、app.utils.logger
   ▲ 被 rag 模块（service）消费
```

- 允许：`app.utils`、`app.core.settings`
- 禁止：`agent` / `services` / `api` / `tools`

---

## 禁止行为

- 在 rag/utils 内做向量检索 / 层级切片（那是 rag 根模块职责）
- 新代码依赖 `document_loader.py` shim 指向已废弃的 `services/modules/rag/service.py` 路径（应直接使用 `app.utils.document_loader`）
- 把业务逻辑塞进"工具"目录（保持薄工具）
