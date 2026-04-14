# RAG (Retrieval-Augmented Generation) 详细实现文档

## 目录

1. [架构概述](#1-架构概述)
2. [核心模块详解](#2-核心模块详解)
3. [数据流与调用流程](#3-数据流与调用流程)
4. [配置详解](#4-配置详解)
5. [使用示例](#5-使用示例)
6. [API 接口文档](#6-api-接口文档)
7. [扩展与定制](#7-扩展与定制)

---

## 1. 架构概述

### 1.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Village Planning Agent                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │  用户查询   │ →  │  Agent     │ →  │   LLM       │                 │
│  └─────────────┘    │  Orchestrator│    │  Response   │                 │
│                     └─────────────┘    └─────────────┘                 │
│                            ↓                                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      RAG 系统核心                                │   │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐    │   │
│  │  │  Tools    │  │  Cache    │  │  Context  │  │  Summary  │    │   │
│  │  │  (检索工具)│  │  (向量缓存)│  │  (上下文) │  │  (摘要)   │    │   │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘    │   │
│  │         ↓              ↓              ↓              ↓          │   │
│  │  ┌─────────────────────────────────────────────────────────┐   │   │
│  │  │              ChromaDB Vector Store                      │   │   │
│  │  │  ┌─────────────────────────────────────────────────┐    │   │   │
│  │  │  │  Embeddings (BAAI/bge-small-zh-v1.5)             │    │   │   │
│  │  │  └─────────────────────────────────────────────────┘    │   │   │
│  │  └─────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                            ↑                                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      知识库构建流程                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │   │
│  │  │ Loader   │→ │ Slicer   │→ │ Metadata │→ │ Embedder │       │   │
│  │  │ (加载器) │  │ (切片器) │  │ (元数据) │  │ (嵌入)   │       │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 目录结构

```
src/rag/
├── __init__.py                    # 模块入口，导出主要类和函数
├── config.py                      # RAG 配置文件
├── build.py                       # 知识库构建脚本
│
├── core/                          # 核心实现
│   ├── __init__.py               # 核心模块导出
│   ├── cache.py                  # 向量数据库缓存管理器
│   ├── context_manager.py        # 文档上下文管理器
│   ├── kb_manager.py             # 知识库增量管理器
│   ├── summarization.py          # 层次化摘要系统
│   └── tools.py                  # Agent 工具集定义
│
├── metadata/                      # 元数据管理
│   ├── __init__.py
│   ├── injector.py               # 元数据注入器
│   └── tagging_rules.py          # 标注规则配置
│
├── slicing/                       # 切片策略
│   ├── __init__.py
│   └ strategies.py             # 差异化切片策略
│
├── utils/                         # 工具函数
│   ├── __init__.py
│   └ loaders.py                # 文档加载器
│
├── service/                       # API 服务
│   ├── __init__.py
│   ├── main.py                   # FastAPI 服务入口
│   ├── api/
│   │   ├── __init__.py
│   │   └ routes.py             # API 路由定义
│   ├── core/
│   │   ├── __init__.py
│   │   └ config.py             # 服务配置
│   └ schemas/
│       ├── __init__.py
│       └ chat.py               # 请求/响应模型
│
├── visualize/                     # 可视化工具
│   ├── __init__.py
│   └ inspector.py              # 切片检查器
│
├── scripts/                       # 脚本工具
│   ├── __init__.py
│   ├── build_kb_auto.py          # 自动构建脚本
│   └ kb_cli.py                 # 命令行工具
│
└── tests/                         # 测试文件
    ├── test_rag.py
    ├── test_rag_integration.py
    ├── test_summarization.py
    ├── test_context_features.py
    ├── test_e2e_planning.py
    └── test_planning_integration.py
```

---

## 2. 核心模块详解

### 2.1 向量存储缓存 (cache.py)

**文件位置**: `src/rag/core/cache.py`

**核心功能**: 懒加载向量数据库和 Embedding 模型，管理查询缓存。

#### 主要类和方法

```python
class VectorStoreCache:
    """向量数据库缓存管理器 - 单例模式"""

    _instance: Optional["VectorStoreCache"] = None
    _embedding_model: Optional[Embeddings] = None
    _vectorstore: Optional[Chroma] = None

    def get_embedding_model(self) -> Embeddings:
        """
        懒加载 Embedding 模型

        支持两种 Provider:
        - local: HuggingFaceEmbeddings (BAAI/bge-small-zh-v1.5)
        - aliyun: DashScope API (text-embedding-v4)

        Returns:
            Embeddings: 嵌入模型实例
        """

    def get_vectorstore(self) -> Chroma:
        """
        懒加载 Chroma 向量数据库

        Returns:
            Chroma: 向量数据库实例
        """

    def cache_query_result(
        self,
        query: str,
        results: list[Document],
        context_params: dict
    ) -> None:
        """
        缓存查询结果

        Args:
            query: 查询文本
            results: 检索结果列表
            context_params: 上下文参数（维度、地形等）
        """

    def get_cached_query(
        self,
        query: str,
        context_params: dict
    ) -> Optional[list[Document]]:
        """
        获取缓存的查询结果
        """
```

#### 使用示例

```python
from src.rag.core.cache import VectorStoreCache

# 获取单例实例
cache = VectorStoreCache()

# 获取向量数据库
vectorstore = cache.get_vectorstore()

# 执行检索
results = vectorstore.similarity_search(
    query="村庄规划用地布局要求",
    k=5,
    filter={"dimension_tags": {"$in": ["land_use"]}}
)
```

---

### 2.2 检索工具集 (tools.py)

**文件位置**: `src/rag/core/tools.py`

**核心功能**: 提供 7 种检索工具供 Agent 调用。

#### 工具清单

| 工具名 | 功能描述 | 使用场景 |
|--------|----------|----------|
| `list_documents` | 列出知识库中所有可用文档 | 任务开始时了解资料范围 |
| `document_overview_tool` | 获取单个文档的执行摘要 | 快速了解文档核心内容 |
| `chapter_content_tool` | 获取章节详细内容 | 深度阅读特定章节 |
| `knowledge_search_tool` | 语义相似度检索 | 查找特定知识点 |
| `key_points_search_tool` | 搜索文档关键要点 | 精确查找核心信息 |
| `full_document_tool` | 获取完整文档内容 | 深度阅读全篇 |
| `check_technical_indicators` | 技术指标检索 | 维度/地形过滤检索 |

#### 核心工具实现

```python
@tool
def knowledge_search_tool(
    query: str,
    top_k: int = 5,
    context_mode: str = "standard",
    dimension: Optional[str] = None,
    terrain: Optional[str] = None,
    doc_type: Optional[str] = None
) -> str:
    """
    语义相似度检索工具

    Args:
        query: 搜索查询文本
        top_k: 返回结果数量 (默认 5)
        context_mode: 上下文模式
            - minimal: 仅匹配片段
            - standard: 片段 + 300字上下文
            - expanded: 片段 + 500字上下文
        dimension: 维度过滤 (如 "land_use", "traffic")
        terrain: 地形过滤 (如 "mountain", "plain")
        doc_type: 文档类型过滤

    Returns:
        str: 格式化的检索结果
    """
```

#### 元数据过滤构建

```python
def _build_metadata_filter(
    dimension: Optional[str],
    terrain: Optional[str],
    doc_type: Optional[str]
) -> dict:
    """
    构建 ChromaDB 元数据过滤条件

    ChromaDB 使用 MongoDB 风格的查询语法:
    - $in: 包含在列表中
    - $eq: 等于
    - $contains: 包含字符串

    Returns:
        dict: 过滤条件字典
    """
    filter_dict = {}

    if dimension:
        # 支持多维度标签匹配
        filter_dict["dimension_tags"] = {"$in": [dimension]}

    if terrain:
        filter_dict["terrain"] = terrain

    if doc_type:
        filter_dict["document_type"] = doc_type

    return filter_dict
```

---

### 2.3 文档上下文管理器 (context_manager.py)

**文件位置**: `src/rag/core/context_manager.py`

**核心功能**: 从原始文档中获取切片周围的上下文。

```python
class DocumentContextManager:
    """文档上下文管理器"""

    def __init__(self, knowledge_base_path: Path):
        """
        Args:
            knowledge_base_path: 知识库根目录
        """
        self.knowledge_base_path = knowledge_base_path
        self._document_cache: dict[str, str] = {}

    def get_context_around_chunk(
        self,
        chunk: Document,
        context_chars: int = 300
    ) -> str:
        """
        获取切片周围的上下文文本

        Args:
            chunk: 文档切片
            context_chars: 上下文字符数

        Returns:
            str: 扩展后的文本（切片 + 上下文）
        """
        # 1. 从缓存或文件加载原始文档
        source = chunk.metadata.get("source")
        original_text = self._load_document(source)

        # 2. 定位切片位置
        chunk_text = chunk.page_content
        start_idx = original_text.find(chunk_text)

        if start_idx == -1:
            return chunk_text  # 找不到则返回原切片

        # 3. 计算上下文范围
        context_start = max(0, start_idx - context_chars)
        context_end = min(len(original_text), start_idx + len(chunk_text) + context_chars)

        # 4. 返回扩展文本
        return original_text[context_start:context_end]
```

---

### 2.4 层次化摘要系统 (summarization.py)

**文件位置**: `src/rag/core/summarization.py`

**核心功能**: 为文档生成多层次摘要，支持高效浏览。

```python
class DocumentSummarizer:
    """层次化文档摘要生成器"""

    def __init__(self, llm: Optional[BaseLLM] = None):
        """
        Args:
            llm: LLM 实例（默认使用配置的模型）
        """
        self.llm = llm or create_llm()

    def generate_executive_summary(
        self,
        document: Document,
        max_length: int = 200
    ) -> str:
        """
        生成文档执行摘要

        Args:
            document: 文档对象
            max_length: 摘要最大长度（字符）

        Returns:
            str: 200字左右的执行摘要
        """

    def generate_chapter_summaries(
        self,
        document: Document
    ) -> list[ChapterSummary]:
        """
        生成章节摘要列表

        Returns:
            list[ChapterSummary]: 每章约300字的摘要
        """

    def generate_key_points(
        self,
        document: Document,
        num_points: int = 15
    ) -> list[str]:
        """
        提取文档关键要点

        Args:
            document: 文档对象
            num_points: 要点数量 (10-15)

        Returns:
            list[str]: 关键要点列表
        """
```

---

### 2.5 知识库管理器 (kb_manager.py)

**文件位置**: `src/rag/core/kb_manager.py`

**核心功能**: 知识库增量更新和版本管理。

```python
class KnowledgeBaseManager:
    """知识库增量管理器"""

    def __init__(self, vectorstore: Chroma):
        self.vectorstore = vectorstore
        self.metadata_db = self._init_metadata_db()

    def add_document(
        self,
        document_path: Path,
        category: str,
        force_rebuild: bool = False
    ) -> dict:
        """
        添加单个文档到知识库

        Args:
            document_path: 文档路径
            category: 文档类别 (policies/cases/standards/domain/local)
            force_rebuild: 是否强制重建

        Returns:
            dict: 添加结果统计
        """

    def remove_document(self, source: str) -> bool:
        """从知识库移除文档"""

    def get_document_status(self, source: str) -> dict:
        """获取文档状态（是否已入库、切片数量等）"""

    def sync_knowledge_base(self) -> dict:
        """同步知识库（检查新增/修改/删除）"""
```

---

### 2.6 切片策略 (strategies.py)

**文件位置**: `src/rag/slicing/strategies.py`

**核心功能**: 差异化文档切片策略，保持语义完整性。

#### 切片策略类

```python
class PolicySlicer(BaseSlicer):
    """
    政策文档切片器

    特点: 按"第 X 条"分割，保持条款完整性
    """

    def slice(self, text: str) -> list[Document]:
        # 匹配条款模式: "第X条"、"第一条"、"第1条"
        pattern = r'第[一二三四五六七八九十\d]+条'

        # 按条款分割，每个条款作为一个切片
        sections = re.split(pattern, text)

        # 为每个切片添加条款编号元数据
        ...

class CaseSlicer(BaseSlicer):
    """
    案例文档切片器

    特点: 按项目阶段分割（立项、规划、实施、验收）
    """

    def slice(self, text: str) -> list[Document]:
        # 匹配项目阶段标题
        phase_patterns = [
            "项目背景", "规划思路", "设计方案",
            "实施过程", "建设成果", "经验总结"
        ]
        ...

class StandardSlicer(BaseSlicer):
    """
    标准规范切片器

    特点: 按章节编号分割（如 4.1, 4.2, 5.1.1）
    """

    def slice(self, text: str) -> list[Document]:
        # 匹配章节编号: 4.1, 4.1.1, 4.1.1.1
        pattern = r'\d+\.\d+(?:\.\d+)*'
        ...

class GuideSlicer(BaseSlicer):
    """
    指南手册切片器

    特点: 按知识点分割，每个知识块完整
    """

class DefaultSlicer(BaseSlicer):
    """
    通用切片器

    使用 RecursiveCharacterTextSplitter
    默认: chunk_size=2500, chunk_overlap=500
    """
```

#### 切片策略选择

```python
SLICER_MAPPING = {
    "policies": PolicySlicer,
    "cases": CaseSlicer,
    "standards": StandardSlicer,
    "guides": GuideSlicer,
    "default": DefaultSlicer,
}

def get_slicer(document_type: str) -> BaseSlicer:
    """根据文档类型获取切片器"""
    return SLICER_MAPPING.get(document_type, DefaultSlicer)()
```

---

### 2.7 文档加载器 (loaders.py)

**文件位置**: `src/rag/utils/loaders.py`

**核心功能**: 统一文档加载接口，支持多种格式。

#### 支持的文档格式

| 格式 | 扩展名 | 加载方式 |
|------|--------|----------|
| Word | `.doc`, `.docx` | MarkItDown |
| PDF | `.pdf` | MarkItDown |
| PowerPoint | `.ppt`, `.pptx` | MarkItDown |
| Excel | `.xls`, `.xlsx` | MarkItDown |
| 其他 | `.epub`, `.html`, `.md`, `.txt` | MarkItDown |

#### 核心加载器实现

```python
class MarkItDownLoader(BaseDocumentLoader):
    """
    统一文档加载器

    使用 Microsoft MarkItDown 库，将所有格式转换为 Markdown
    """

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.converter = MarkItDown()

    def load(self) -> list[Document]:
        """
        加载文档并转换为 Document 对象列表

        Returns:
            list[Document]: 文档列表
        """
        # 使用 MarkItDown 转换
        result = self.converter.convert(str(self.file_path))

        # 创建 Document 对象
        doc = Document(
            page_content=result.text_content,
            metadata={
                "source": str(self.file_path),
                "file_type": self.file_path.suffix,
                "title": self._extract_title(result.text_content),
            }
        )

        return [doc]
```

---

### 2.8 元数据注入器 (injector.py)

**文件位置**: `src/rag/metadata/injector.py`

**核心功能**: 为文档切片注入维度、地形、类型等元数据。

```python
class MetadataInjector:
    """元数据注入器"""

    def inject_metadata(
        self,
        documents: list[Document],
        source: Path,
        category: str
    ) -> list[Document]:
        """
        为文档切片注入元数据

        Args:
            documents: 文档切片列表
            source: 文档源路径
            category: 文档类别

        Returns:
            list[Document]: 注入元数据后的文档列表
        """
        for doc in documents:
            # 1. 基础元数据
            doc.metadata["source"] = str(source)
            doc.metadata["category"] = category
            doc.metadata["document_type"] = self._detect_doc_type(doc)

            # 2. 维度标签（基于关键词匹配）
            dimension_tags = self._extract_dimensions(doc.page_content)
            doc.metadata["dimension_tags"] = dimension_tags

            # 3. 地形标签
            terrain_tags = self._extract_terrain(doc.page_content)
            doc.metadata["terrain"] = terrain_tags

            # 4. 其他元数据
            doc.metadata["chunk_index"] = idx
            doc.metadata["total_chunks"] = len(documents)

        return documents

    def _extract_dimensions(self, text: str) -> list[str]:
        """
        从文本中提取维度标签

        使用 tagging_rules.py 中定义的关键词匹配
        """
        dimensions = []
        for dim, keywords in DIMENSION_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                dimensions.append(dim)
        return dimensions
```

---

## 3. 数据流与调用流程

### 3.1 知识库构建流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                        知识库构建流程                                │
└─────────────────────────────────────────────────────────────────────┘

  原始文档 (docs/policies/xxx.docx)
        │
        ↓
  ┌─────────────┐
  │   Loader    │  MarkItDownLoader.load()
  │  (文档加载) │  → 转换为 Markdown 文本
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │   Slicer    │  PolicySlicer.slice()
  │  (切片处理) │  → 按条款分割，保持完整性
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │  Metadata   │  MetadataInjector.inject_metadata()
  │  (元数据注入)│  → 添加维度、地形、类型标签
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │   Embedder  │  HuggingFaceEmbeddings.embed_documents()
  │  (向量嵌入) │  → 生成 1024 维向量
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │ ChromaDB    │  vectorstore.add_documents()
  │  (持久化)   │  → 存储到 knowledge_base/chroma_db/
  └─────────────┘
```

#### 构建脚本调用

```bash
# 构建全部知识库
python -m src.rag.build --all

# 构建指定类别
python -m src.rag.build --category policies

# 重建指定文档
python -m src.rag.build --file docs/policies/land_use.docx --force

# 查看知识库状态
python -m src.rag.scripts.kb_cli status
```

### 3.2 检索调用流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                        检索调用流程                                  │
└─────────────────────────────────────────────────────────────────────┘

  用户查询: "山区村庄规划用地布局要求"
        │
        ↓
  ┌─────────────┐
  │   Agent     │  解析查询意图
  │ Orchestrator│  → 确定需要调用 knowledge_search_tool
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │   Tool      │  knowledge_search_tool.invoke()
  │  (工具调用) │  参数: query, top_k=5, dimension="land_use", terrain="mountain"
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │   Cache     │  VectorStoreCache.get_vectorstore()
  │  (获取缓存) │  → 返回 Chroma 实例
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │ ChromaDB    │  similarity_search()
  │  (向量检索) │  filter = {"dimension_tags": {"$in": ["land_use"]}, "terrain": "mountain"}
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │  Context    │  DocumentContextManager.get_context_around_chunk()
  │  (上下文)   │  → 扩展每个切片的上下文 (300字)
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │  Formatter  │  格式化输出
  │  (格式化)   │  → 返回结构化的知识片段列表
  └─────────────┘
        │
        ↓
  格式化结果:
  ┌─────────────────────────────────────────────────────────────────┐
  │ 【知识片段 1】                                                  │
  │ 来源: 《村庄规划用地布局指南》第3章                              │
  │ 相关度: 0.85                                                   │
  │ 维度: land_use, traffic                                        │
  │ 内容: 山区村庄用地布局应遵循"依山就势"原则...                   │
  │                                                                 │
  │ 【知识片段 2】                                                  │
  │ 来源: 《浙江省村庄规划编制导则》第15条                           │
  │ 相关度: 0.78                                                   │
  │ 维度: land_use                                                 │
  │ 内容: 山地地形村庄规划应严格控制建设用地规模...                 │
  └─────────────────────────────────────────────────────────────────┘
```

### 3.3 Agent 调用示例

```python
from langchain.agents import AgentExecutor
from src.rag.core.tools import (
    list_documents,
    knowledge_search_tool,
    document_overview_tool
)

# 创建 Agent
tools = [
    list_documents,
    knowledge_search_tool,
    document_overview_tool,
]

agent = create_react_agent(
    llm=create_llm(),
    tools=tools,
    prompt=PLANNING_AGENT_PROMPT
)

agent_executor = AgentExecutor(agent=agent, tools=tools)

# 执行查询
result = agent_executor.invoke({
    "input": "山区村庄规划用地布局有哪些要求？"
})

# 输出
print(result["output"])
```

---

## 4. 配置详解

### 4.1 RAG 配置文件

**文件位置**: `src/rag/config.py`

```python
"""
RAG 系统配置文件
"""

from pathlib import Path
from src.core.config import PROJECT_ROOT

# ==================== 向量数据库配置 ====================

VECTOR_DB_TYPE: str = "chroma"  # chroma | faiss | qdrant

CHROMA_PERSIST_DIR: Path = PROJECT_ROOT / "knowledge_base" / "chroma_db"
FAISS_INDEX_DIR: Path = PROJECT_ROOT / "knowledge_base" / "faiss_index"
QDRANT_HOST: str = "localhost"
QDRANT_PORT: int = 6333

# ==================== Embedding 配置 ====================

EMBEDDING_PROVIDER: str = "local"  # local | aliyun

# Local (HuggingFace)
EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIMENSIONS: int = 1024

# Aliyun (DashScope)
ALIYUN_EMBEDDING_MODEL: str = "text-embedding-v4"
ALIYUN_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")

# ==================== 检索配置 ====================

DEFAULT_TOP_K: int = 5
RETRIEVE_SCORE_THRESHOLD: float = 0.7

# 上下文模式字符数
CONTEXT_CHARS = {
    "minimal": 0,
    "standard": 300,
    "expanded": 500,
}

# ==================== 切片配置 ====================

CHUNK_SIZE: int = 2500
CHUNK_OVERLAP: int = 500

# 文档类别目录
KB_CATEGORIES = ["policies", "cases", "standards", "domain", "local"]

# ==================== 缓存配置 ====================

QUERY_CACHE_MAX_SIZE: int = 100
QUERY_CACHE_TTL_SECONDS: int = 3600  # 1小时
```

### 4.2 主配置文件

**文件位置**: `src/core/config.py`

```python
"""
项目主配置文件
"""

# ==================== LLM 配置 ====================

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "deepseek")
LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE: float = 0.7
LLM_MAX_TOKENS: int = 8192

# LLM 提供商配置
LLM_PROVIDERS = {
    "deepseek": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    "zhipuai": {
        "api_key_env": "ZHIPUAI_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
    },
}

# ==================== LangSmith 追踪 ====================

LANGCHAIN_TRACING_V2: str = os.getenv("LANGCHAIN_TRACING_V2", "false")
LANGCHAIN_API_KEY: str = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "village-planning")

# ==================== RAG 配置 ====================

RAG_ENABLED: bool = True
VECTOR_STORE_DIR: str = "vectordb"

# ==================== 知识库配置 ====================

KNOWLEDGE_BASE_DIR: Path = PROJECT_ROOT / "knowledge_base"
DOCUMENTS_DIR: Path = PROJECT_ROOT / "docs"
```

### 4.3 元数据标注规则

**文件位置**: `src/rag/metadata/tagging_rules.py`

```python
"""
元数据标注规则

定义 24 个分析维度的关键词映射
"""

DIMENSION_KEYWORDS = {
    "land_use": ["用地", "土地", "三区三线", "宅基地", "建设用地", "耕地"],
    "traffic": ["道路", "交通", "红线", "公路", "街道", "停车场"],
    "infrastructure": ["给排水", "电力", "通信", "燃气", "供热", "管网"],
    "public_facilities": ["公共服务", "学校", "医院", "养老", "文化站", "健身"],
    "environment": ["环境", "生态", "绿化", "景观", "水体", "污水处理"],
    "housing": ["住房", "住宅", "民居", "建筑", "农房", "危房改造"],
    "industry": ["产业", "农业", "旅游", "民宿", "产业园", "就业"],
    "heritage": ["遗产", "文物", "古建筑", "传统建筑", "历史文化"],
    "disaster": ["防灾", "避难", "消防", "洪水", "地质灾害", "应急"],
    "safety": ["安全", "消防", "治安", "应急通道", "避难场所"],
    # ... 共 24 个维度
}

TERRAIN_KEYWORDS = {
    "mountain": ["山区", "山地", "丘陵", "高原", "坡地", "山谷"],
    "plain": ["平原", "盆地", "平坦", "低地", "平原地区"],
    "hill": ["丘陵", "岗地", "台地", "丘陵地区"],
    "coastal": ["沿海", "滨海", "海岛", "海岸", "港口"],
    "riverside": ["沿江", "滨河", "水乡", "河岸", "湖边"],
}

DOCUMENT_TYPE_KEYWORDS = {
    "policy": ["政策", "法规", "条例", "办法", "规定", "通知"],
    "standard": ["标准", "规范", "导则", "技术标准", "编制要求"],
    "case": ["案例", "实例", "规划案例", "实践案例"],
    "guide": ["指南", "手册", "指引", "操作指南"],
    "report": ["报告", "研究", "分析报告", "调研报告"],
}
```

---

## 5. 使用示例

### 5.1 基础检索示例

```python
from src.rag.core.tools import knowledge_search_tool

# 基础查询
result = knowledge_search_tool.invoke({
    "query": "村庄规划用地布局要求",
    "top_k": 5
})

# 带过滤的查询
result = knowledge_search_tool.invoke({
    "query": "山区村庄规划用地布局要求",
    "top_k": 5,
    "dimension": "land_use",
    "terrain": "mountain",
    "context_mode": "expanded"
})

print(result)
```

### 5.2 查看知识库文档

```python
from src.rag.core.tools import list_documents, document_overview_tool

# 列出所有文档
docs = list_documents.invoke({})
print(docs)

# 获取文档概览
overview = document_overview_tool.invoke({
    "source": "policies/land_use_guide.docx"
})
print(overview)
```

### 5.3 检查技术指标

```python
from src.rag.core.tools import check_technical_indicators

# 检查特定维度的技术指标
result = check_technical_indicators.invoke({
    "dimension": "land_use",
    "query": "宅基地面积标准"
})

print(result)
```

### 5.4 知识库管理

```python
from src.rag.core.kb_manager import KnowledgeBaseManager
from src.rag.core.cache import VectorStoreCache

# 获取管理器
cache = VectorStoreCache()
vectorstore = cache.get_vectorstore()
kb_manager = KnowledgeBaseManager(vectorstore)

# 添加文档
result = kb_manager.add_document(
    document_path=Path("docs/policies/new_policy.docx"),
    category="policies"
)
print(f"添加了 {result['chunks_added']} 个切片")

# 查看文档状态
status = kb_manager.get_document_status("policies/new_policy.docx")
print(status)

# 同步知识库
sync_result = kb_manager.sync_knowledge_base()
print(f"新增: {sync_result['added']}, 更新: {sync_result['updated']}, 删除: {sync_result['removed']}")
```

### 5.5 构建知识库

```bash
# 全量构建
python -m src.rag.build --all

# 按类别构建
python -m src.rag.build --category policies
python -m src.rag.build --category cases

# 单文档构建
python -m src.rag.build --file docs/policies/land_use.docx

# 强制重建（覆盖已有）
python -m src.rag.build --file docs/policies/land_use.docx --force

# 查看状态
python -m src.rag.scripts.kb_cli status

# 查看统计
python -m src.rag.scripts.kb_cli stats
```

---

## 6. API 接口文档

### 6.1 API 服务启动

```bash
# 启动 RAG 服务
cd src/rag/service
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

### 6.2 API 端点列表

#### 对话接口

```
POST /api/chat/planning
```

**请求体**:
```json
{
  "query": "山区村庄规划用地布局有哪些要求？",
  "context": {
    "dimension": "land_use",
    "terrain": "mountain",
    "location": "浙江省"
  },
  "stream": true
}
```

**响应** (流式):
```json
{
  "event": "token",
  "data": "山区村庄规划用地布局应遵循以下原则..."
}
```

#### 知识库接口

```
GET /api/knowledge/documents
```

**响应**:
```json
{
  "documents": [
    {
      "source": "policies/land_use_guide.docx",
      "category": "policies",
      "chunks": 45,
      "dimensions": ["land_use", "traffic"],
      "last_updated": "2024-04-08T10:30:00Z"
    }
  ]
}
```

```
GET /api/knowledge/summary/{source}
```

**响应**:
```json
{
  "source": "policies/land_use_guide.docx",
  "executive_summary": "本指南系统阐述了村庄规划用地布局的原则...",
  "key_points": [
    "用地布局应遵循'依山就势'原则",
    "严格控制建设用地规模",
    ...
  ],
  "chapters": [
    {
      "title": "用地布局原则",
      "summary": "..."
    }
  ]
}
```

#### 检索接口

```
POST /api/knowledge/search
```

**请求体**:
```json
{
  "query": "宅基地面积标准",
  "top_k": 5,
  "dimension": "land_use",
  "terrain": null,
  "context_mode": "standard"
}
```

**响应**:
```json
{
  "results": [
    {
      "content": "宅基地面积标准应不超过120平方米...",
      "source": "policies/land_use_guide.docx",
      "chunk_index": 23,
      "score": 0.85,
      "metadata": {
        "dimension_tags": ["land_use", "housing"],
        "terrain": null
      }
    }
  ]
}
```

---

## 7. 扩展与定制

### 7.1 添加新的切片策略

```python
# src/rag/slicing/strategies.py

class CustomSlicer(BaseSlicer):
    """自定义切片器"""

    def __init__(self, chunk_size: int = 2500, overlap: int = 500):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def slice(self, text: str) -> list[Document]:
        """
        自定义切片逻辑

        Args:
            text: 原始文本

        Returns:
            list[Document]: 切片列表
        """
        # 实现自定义切片逻辑
        ...

# 注册切片器
SLICER_MAPPING["custom"] = CustomSlicer
```

### 7.2 添加新的维度关键词

```python
# src/rag/metadata/tagging_rules.py

DIMENSION_KEYWORDS["new_dimension"] = [
    "关键词1",
    "关键词2",
    "关键词3",
]
```

### 7.3 更换 Embedding 模型

```python
# src/rag/config.py

EMBEDDING_PROVIDER = "aliyun"  # 切换到云端
ALIYUN_EMBEDDING_MODEL = "text-embedding-v4"

# 或使用其他本地模型
EMBEDDING_MODEL_NAME = "BAAI/bge-large-zh-v1.5"
EMBEDDING_DIMENSIONS = 1024
```

### 7.4 更换向量数据库

```python
# src/rag/config.py

VECTOR_DB_TYPE = "qdrant"
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333

# 需要在 cache.py 中添加 Qdrant 支持逻辑
```

---

## 附录

### A. 关键文件路径汇总

| 功能模块 | 文件路径 |
|----------|----------|
| RAG 配置 | `src/rag/config.py` |
| 向量缓存 | `src/rag/core/cache.py` |
| 检索工具 | `src/rag/core/tools.py` |
| 知识库管理 | `src/rag/core/kb_manager.py` |
| 上下文管理 | `src/rag/core/context_manager.py` |
| 摘要生成 | `src/rag/core/summarization.py` |
| 切片策略 | `src/rag/slicing/strategies.py` |
| 文档加载 | `src/rag/utils/loaders.py` |
| 元数据注入 | `src/rag/metadata/injector.py` |
| 标注规则 | `src/rag/metadata/tagging_rules.py` |
| 知识库构建 | `src/rag/build.py` |
| API 服务 | `src/rag/service/api/routes.py` |
| LLM 工厂 | `src/core/llm_factory.py` |
| 主配置 | `src/core/config.py` |

### B. 环境变量配置

```bash
# .env 文件

# LLM 配置
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
OPENAI_API_KEY=sk-xxx
ZHIPUAI_API_KEY=xxx

# Embedding 配置 (可选)
DASHSCOPE_API_KEY=xxx

# LangSmith 追踪 (可选)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=xxx
LANGCHAIN_PROJECT=village-planning
```

### C. 依赖包列表

```toml
# pyproject.toml

[project.dependencies]
langchain = ">=0.1.0"
langchain-community = ">=0.0.20"
chromadb = ">=0.4.0"
sentence-transformers = ">=2.2.0"
markitdown = ">=0.0.1"
fastapi = ">=0.100.0"
uvicorn = ">=0.23.0"
pydantic = ">=2.0.0"
```

---

**文档版本**: 1.0
**最后更新**: 2024-04-09
**维护者**: Village Planning Agent Team