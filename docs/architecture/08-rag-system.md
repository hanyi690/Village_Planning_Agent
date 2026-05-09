# RAG知识库架构

> **更新日期**: 2026-05-08
> **版本**: v2.0 (重组后架构)

本文档详细说明RAG系统的架构设计。

## 目录

- [RAG架构分层](#rag架构分层)
- [知识库管理](#知识库管理)
- [向量存储](#向量存储)
- [检索机制](#检索机制)
- [知识库内容](#知识库内容)

---

## RAG架构分层

```
应用层: Agent Nodes() -> get_cached_knowledge()
    ↓
检索层: backend/app/modules/rag/service.py -> search_knowledge()
    ↓
存储层: backend/app/modules/rag/vector_store.py -> ChromaDB
    ↓
切片层: backend/app/utils/text_splitter.py -> RecursiveCharacterTextSplitter
    ↓
数据层: data/knowledge_base/
```

---

## 知识库管理

### KnowledgeBaseManager

```python
# backend/app/modules/rag/service.py
class KnowledgeBaseManager:
    """知识库增量管理器"""

    def add_document(self, file_path: str) -> str:
        """增量添加单个文档"""
        # 1. 加载文档
        # 2. 切片
        # 3. 注入元数据
        # 4. 存入向量库

    def delete_document(self, doc_name: str) -> bool:
        """删除指定文档"""
        collection.delete(where={"source": doc_name})

    def list_documents(self) -> List[str]:
        """列出知识库中的文档"""
        return collection.get()["metadatas"]
```

### 文档类型推断

```python
def infer_doc_type(filename: str, content: str = "") -> str:
    """
    推断文档类型
    Returns: textbook/guide/policy/standard/case/report
    """
    # 教材类：教材、原理、教程
    # 指南类：指南、手册、指导
    # 政策类：条例、规定、办法
    # 标准类：标准、规范、GB/CJJ
    # 案例类：规划、设计、方案
```

---

## 向量存储

### ChromaDB配置

```python
# backend/app/core/settings.py
CHROMA_COLLECTION_NAME = "village_planning"
CHROMA_PERSIST_DIR = "data/chroma_db"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
```

---

## 检索机制

### QueryBuilder

```python
# backend/app/modules/rag/service.py
class QueryBuilder:
    """查询构建器"""
    def build_query(self, dimension_key: str, layer: int) -> str:
        """根据维度构建查询"""
        templates = {
            "land_use": "土地利用规划 农村 建设用地标准",
            "historical_culture": "历史文化保护 传统村落",
        }
        return templates.get(dimension_key, f"{dimension_key}村庄规划")
```

### 检索参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| top_k | 3 | 返回文档数 |
| dimension | - | 维度筛选 |

---

## 知识库内容

### 目录结构

```
data/knowledge_base/
├── regulations/         # 法规知识库
├── cases/               # 案例知识库
├── standards/           # 标准知识库
```

### 文档类型分布

| 类型 | 数量 | 示例 |
|------|------|------|
| policy | 10+ | 土地管理法、城乡规划法 |
| standard | 15+ | GB50188、CJJ/T123 |
| guide | 5+ | 村庄规划编制指南 |
| case | 20+ | 各地村庄规划案例 |

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 知识库管理 | `backend/app/modules/rag/service.py` |
| 向量存储 | `backend/app/modules/rag/vector_store.py` |
| 查询构建 | `backend/app/modules/rag/service.py` |
| 切片器 | `backend/app/utils/text_splitter.py` |

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [03-layer-dimension](./03-layer-dimension.md) - RAG启用的维度
- [06-tool-system](./06-tool-system.md) - 知识检索工具