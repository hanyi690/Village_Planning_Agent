# RAG 知识库系统

为 Planning Agent 提供的两阶段知识检索系统（阶段1：全文上下文 + 阶段2：层次化摘要）

## 核心功能

### 阶段1：全文上下文查询
- 保存原文档完整内容，支持按位置获取上下文
- 工具：`get_full_document()`, `get_chapter_by_header()`, `list_available_documents()`

### 阶段2：层次化摘要
- 执行摘要（200字）+ 章节摘要 + 关键要点提取
- 工具：`get_executive_summary()`, `list_chapter_summaries()`, `search_key_points()`

### 智能文档加载
- 支持 .doc/.docx/.pptx/.pdf/.md/.txt
- 自动检测伪装文件类型（如 .docx 实际是 .doc）
- 纯 Python 方案读取 .doc（olefile）

### 增量知识库管理
- 支持单个文档的增删，无需全量重建
- CLI 工具便捷管理

## 项目结构

```
src/rag/
├── build.py                    # 知识库构建入口（全量）
├── config.py                   # 配置管理
│
├── core/                       # 核心功能
│   ├── context_manager.py      # 阶段1：上下文管理
│   ├── summarization.py        # 阶段2：摘要生成
│   ├── tools.py                # LangChain 工具定义
│   ├── cache.py                # 向量库缓存
│   └── kb_manager.py           # 增量管理器
│
├── utils/
│   └── loaders.py              # 文档加载器
│
├── scripts/
│   ├── build_kb_auto.py        # 全量构建脚本
│   └── kb_cli.py               # CLI 管理工具
│
├── visualize/
│   └── inspector.py            # 切片分析工具
│
└── tests/                      # 测试套件

knowledge_base/chroma_db/       # 向量数据库输出
data/policies/                  # 政策文件（源文档）
```

## 快速开始

### 1. 准备文档

```bash
data/policies/
├── *.docx
├── *.pdf
└── *.md
```

### 2. 管理知识库

**推荐：使用 CLI 工具（增量管理）**

```bash
# 列出知识库中的文档
python -m src.rag.scripts.kb_cli list

# 添加单个文档（增量）
python -m src.rag.scripts.kb_cli add data/policies/新政策.docx

# 删除文档
python -m src.rag.scripts.kb_cli delete 新政策.docx

# 同步源目录（自动添加新文件）
python -m src.rag.scripts.kb_cli sync

# 查看统计信息
python -m src.rag.scripts.kb_cli stats
```

**首次构建（全量）**

```bash
# 自动构建（推荐）
python src/rag/scripts/build_kb_auto.py

# 交互式构建
python src/rag/build.py
```

### 3. 使用

```python
from src.rag.core.tools import knowledge_search_tool

# 检索知识
result = knowledge_search_tool.invoke({
    "query": "乡村旅游民宿政策",
    "top_k": 5,
    "context_mode": "standard"
})

# 获取完整文档（阶段1）
from src.rag.core.tools import full_document_tool
doc = full_document_tool.invoke({"source": "文件名.docx"})

# 获取摘要（阶段2）
from src.rag.core.tools import document_overview_tool
summary = document_overview_tool.invoke({"source": "文件名.docx"})
```

### 4. 增量管理（Python API）

```python
from src.rag.core.kb_manager import get_kb_manager

manager = get_kb_manager()

# 添加文档
result = manager.add_document("data/policies/新政策.docx")
print(f"添加了 {result['chunks_added']} 个切片")

# 删除文档
manager.delete_document("旧政策.docx")

# 列出文档
docs = manager.list_documents()
for doc in docs:
    print(f"{doc['source']}: {doc['chunk_count']} 切片")

# 查看统计
stats = manager.get_stats()
```

## 测试

```bash
# 集成测试
python src/rag/tests/test_rag_integration.py

# 用户场景测试
python src/rag/tests/test_user_scenario.py
```

## 配置

```bash
# .env 文件
EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
CHUNK_SIZE=2500
CHUNK_OVERLAP=500
DEFAULT_TOP_K=5
```

## 测试结果

- ✅ 文档数: 2个（policies + cases）
- ✅ 切片数: 95个
- ✅ 检索成功率: 100% (5/5)
- ✅ 跨领域融合: 政策 + 案例

详见: `RAG_INTEGRATION_TEST_REPORT.md`
