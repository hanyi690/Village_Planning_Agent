# RAG (Retrieval-Augmented Generation) 详细实现文档

## 目录

1. [架构概述](#1-架构概述)
2. [文档处理流程](#2-文档处理流程)
3. [切片策略详解](#3-切片策略详解)
4. [元数据注入系统](#4-元数据注入系统)
5. [向量存储与检索](#5-向量存储与检索)
6. [任务管理与并行处理](#6-任务管理与并行处理)
7. [与 Agent 的集成](#7-与-agent-的集成)
8. [API 接口文档](#8-api-接口文档)
9. [配置详解](#9-配置详解)
10. [扩展与定制](#10-扩展与定制)
11. [已知问题与优化方案](#11-已知问题与优化方案)
12. [问题诊断与优化路径](#12-问题诊断与优化路径)

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
│  │  │  Tools    │  │  Cache    │  │  Context  │  │  TaskMgr  │    │   │
│  │  │  (检索工具)│  │  (向量缓存)│  │  (上下文) │  │ (并行处理)│    │   │
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
│  │  │ (加载器) │  │ (统一切片)│  │ (统一维度)│  │ (嵌入)   │       │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 目录结构（精简重构后）

```
src/rag/
├── __init__.py                    # 模块入口
├── config.py                      # RAG 配置文件
├── build.py                       # 知识库构建脚本（使用统一切片）
│
├── core/                          # 核心实现
│   ├── __init__.py
│   ├── cache.py                  # 向量数据库缓存管理器
│   ├── context_manager.py        # 文档上下文管理器
│   ├── kb_manager.py             # 知识库增量管理器
│   ├── task_manager.py           # 文档处理任务管理器（并行处理）
│   ├── vector_store.py           # Small-to-Big 向量存储架构 ✨新增
│   ├── summarization.py          # 层次化摘要系统
│   └── tools.py                  # Agent 工具集定义
│
├── metadata/                      # 元数据管理
│   ├── __init__.py
│   ├── injector.py               # 元数据注入器
│   ├── definitions.py            # 统一维度定义 ✨新增
│   ├── semantic_tagger.py        # 语义维度标注器（使用 definitions.py）
│   └── tagging_rules.py          # 标注规则（使用 definitions.py）
│
├── slicing/                       # 切片策略
│   ├── __init__.py
│   └── slicer.py                 # 统一 Markdown 切片器 ✨新增
│
├── utils/                         # 工具函数
│   ├── __init__.py
│   ├── loaders.py                # 文档加载器（含内嵌 OCR 预处理）
│   └── pdf_fallback.py           # PDF 备用解析链
│
└── visualize/                     # 可视化工具
    ├── __init__.py
    └ inspector.py               # 切片检查器
```

**重构变化说明**：

| 变化类型 | 文件 | 说明 |
|----------|------|------|
| ✨新增 | `slicing/slicer.py` | 统一 Markdown 切片器（配置驱动） |
| ✨新增 | `metadata/definitions.py` | 统一维度定义（keywords + definition） |
| ✨新增 | `core/vector_store.py` | Small-to-Big 检索架构 |
| 🔄合并 | `loaders.py` | 内嵌 OCR 预处理逻辑 |
| 🔄更新 | `build.py` | 使用统一切片策略 |
| ❌删除 | `slicing/strategies.py` | 合并入 slicer.py |
| ❌删除 | `utils/ocr_preprocessor.py` | 合并入 loaders.py |

---

## 2. 文档处理流程

### 2.1 处理流程概览

文档处理分为 7 个阶段（OCR 预处理已内嵌到加载器）：

| 进度 | 阶段 | 操作内容 | 预估耗时 |
|------|------|----------|----------|
| 5% | 文件类型检测 | FileTypeDetector.detect() | ~0.1s |
| 15% | 文档加载 | MarkItDownLoader.load() + OCR 预处理 | 5-120s |
| 30% | 文档类型推断 | infer_doc_type() | ~0.1s |
| 50% | 文档切片 | UnifiedMarkdownSlicer.slice() | 1-5s |
| 70% | 元数据注入 | MetadataInjector.inject_batch() | 0.5-2s |
| 85% | 向量嵌入 | vectorstore.add_documents() | 1-3s |
| 100% | 索引更新 & 缓存清理 | _update_document_index() | ~0.5s |

### 2.2 文档加载器 (loaders.py)

**核心功能**: 使用 Microsoft MarkItDown 库统一处理多种文档格式，**内嵌 OCR 预处理**。

#### 支持的文档格式

| 格式 | 扩展名 | 加载方式 | 特殊处理 |
|------|--------|----------|----------|
| Word | `.doc`, `.docx` | MarkItDown | 无 |
| PDF | `.pdf` | MarkItDown + OCR 备用 | OCR 预处理内嵌 |
| PowerPoint | `.ppt`, `.pptx` | MarkItDown | 无 |
| Markdown | `.md` | MarkItDown | 无 |
| Text | `.txt` | MarkItDown | 无 |

#### OCR 预处理（内嵌在 MarkItDownLoader）

```python
class MarkItDownLoader(BaseDocumentLoader):
    """使用 MarkItDown 统一加载多种文档格式"""

    # OCR 预处理配置（内嵌）
    OCR_PAGE_MARKER = r'^#{1,6}\s+Page\s+\d+'
    OCR_BLOCK_PATTERN = r'\*\[Image OCR\]\n(.*?)\n\[End OCR\]\*'

    # 教材章节 → Markdown 标题转换规则（含英文）
    CHAPTER_TO_HEADER = [
        # 英文章节（新增）
        (r'^(Chapter\s+\d+[^\n]*)', r'# \1'),
        (r'^(Section\s+\d+\.\d+[^\n]*)', r'## \1'),
        # 中文章节（原有）
        (r'^(第[一二三四五六七八九十百]+章[^\n]*)', r'# \1'),
        (r'^(第\s*\d+\s*章[^\n]*)', r'# \1'),
        (r'^(第[一二三四五六七八九十]+节[^\n]*)', r'## \1'),
        (r'^(\d+\.\d+[^\n]*)', r'### \1'),
    ]

    def _preprocess_ocr_output(self, content: str) -> str:
        """
        OCR 输出预处理（内嵌实现）

        处理操作：
        1. 移除 ## Page N 页面标记
        2. 提取 *[Image OCR] 内容块
        3. 转换教材章节标题（含英文）
        """
        # 1. 移除页面标记
        content = re.sub(self.OCR_PAGE_MARKER, '', content, flags=re.MULTILINE)

        # 2. 提取 OCR 内容块
        ocr_blocks_content = re.findall(self.OCR_BLOCK_PATTERN, content, re.DOTALL)
        content = '\n\n'.join(ocr_blocks_content) if ocr_blocks_content else content

        # 3. 转换章节标题
        for pattern, replacement in self.CHAPTER_TO_HEADER:
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

        return content.strip()
```

**新增特性**: 英文教材的 "Chapter X"、"Section X.X" 格式现在可正确识别。

---

## 3. 切片策略详解

### 3.1 统一 Markdown 切片器 (slicer.py)

**核心设计**: 配置驱动，动态策略，替代原有 5 个独立切片器类。

```python
class UnifiedMarkdownSlicer:
    """统一 Markdown 切片器 - 配置驱动，动态策略"""

    # 文档类型配置字典
    CONFIGS: Dict[str, SlicerConfig] = {
        "policy": SlicerConfig(
            split_on=[r'\n(?=第\s*[一二三四五六七八九十百千万0-9]+\s*条)'],
            chunk_size=2500,
            overlap=500,
            min_chunk=50,
        ),
        "case": SlicerConfig(
            split_on=[r'\n(?=[一二三四五六七八九十]+[、.])', r'\n(?=\d+\.[^\d])'],
            chunk_size=2000,
            overlap=400,
            min_chunk=200,
        ),
        "standard": SlicerConfig(
            split_on=[r'\n(?=\d+\.\d+(?:\.\d+)?)', r'\n(?=第\s*\d+\s*条)'],
            chunk_size=1500,
            overlap=300,
            min_chunk=80,
        ),
        "guide": SlicerConfig(
            split_on=[r'\n(?=#{1,3}\s)'],
            chunk_size=1800,
            overlap=350,
            min_chunk=150,
        ),
        "report": SlicerConfig(
            parent_child=True,  # Small-to-Big 模式
            child_size=400,
            parent_size=2000,
        ),
        "textbook": SlicerConfig(
            split_on=[r'\n(?=#{1,3}\s)', r'\n(?=第[一二三四五六七八九十百]+章)'],
            chunk_size=1800,
            overlap=350,
        ),
    }

    def slice(self, content: str, doc_type: str, metadata: Dict) -> List[Chunk]:
        """根据文档类型自动选择切分策略"""
        config = self.CONFIGS.get(doc_type, self.CONFIGS["default"])

        if config.parent_child:
            return self._slice_parent_child(content, config, metadata)  # Small-to-Big
        else:
            return self._slice_by_pattern(content, config, metadata)
```

### 3.2 差异化切片策略配置

| 文档类型 | 切片策略 | 分割依据 | 切片大小 | 特殊模式 |
|----------|----------|----------|----------|----------|
| policy | 条款切片 | "第X条" 边界 | 2500字 | - |
| case | 阶段切片 | 项目阶段标题 | 2000字 | - |
| standard | 章节切片 | 编号 (4.1, 4.2) | 1500字 | - |
| guide | 标题切片 | Markdown 标题 | 1800字 | - |
| report | **Small-to-Big** | - | 子400/父2000 | parent_child=True |
| textbook | 章节切片 | 章节标题 | 1800字 | - |

### 3.3 Small-to-Big 检索架构

**原理**: 检索小块（语义聚焦），返回大块（完整上下文）。

```python
# 切片流程（report 类型）
# 1. 先按 parent_size=2000 切分为父块
# 2. 每个父块再切分为 child_size=400 的子块
# 3. 子块存向量，父块存缓存

# 检索流程
# 1. 检索子块向量（精确命中）
# 2. 通过 parent_id 获取父块内容
# 3. 返回父块（完整上下文）
```

**优势**:
- 提高检索命中率（小块语义更聚焦）
- 提供完整上下文（返回父块而非碎片）

---

## 4. 元数据注入系统

### 4.1 统一维度定义 (definitions.py)

**核心设计**: 单一数据源，合并关键词定义和语义定义。

```python
DIMENSIONS: Dict[str, Dict] = {
    "land_use": {
        "keywords": ["用地", "土地", "三区三线", "宅基地", ...],
        "definition": "土地利用、建设用地、宅基地、三区三线相关",
    },
    "traffic": {
        "keywords": ["道路", "交通", "红线", "路网", ...],
        "definition": "道路交通、路网规划、交通设施相关",
    },
    # ... 15 个维度统一定义
}

def get_dimension_keywords() -> Dict[str, List[str]]:
    """获取维度关键词映射"""
    return {dim: data["keywords"] for dim, data in DIMENSIONS.items()}

def get_dimension_definitions() -> Dict[str, str]:
    """获取维度定义映射"""
    return {dim: data["definition"] for dim, data in DIMENSIONS.items()}
```

### 4.2 标注器引用统一定义

```python
# tagging_rules.py
from .definitions import get_dimension_keywords
DIMENSION_KEYWORDS: Dict[str, List[str]] = get_dimension_keywords()

# semantic_tagger.py
from .definitions import get_dimension_definitions
DIMENSION_DEFINITIONS: Dict[str, str] = get_dimension_definitions()
```

### 4.3 维度标注规则（15 个分析维度）

| Layer | 维度 | 关键词示例 | 定义 |
|-------|------|-----------|------|
| L1 | land_use | 用地、土地、三区三线 | 土地利用、建设用地相关 |
| L1 | traffic | 道路、交通、红线 | 道路交通、路网规划相关 |
| L1 | infrastructure | 给排水、电力、通信 | 基础设施相关 |
| L2 | location | 区位、位置、地理 | 区位条件、行政区划相关 |
| L2 | socio_economic | 经济、产业、人口 | 社会经济、产业发展相关 |
| L3 | disaster_prevention | 防灾、消防、防洪 | 防灾减灾、应急预案相关 |

---

## 5. 向量存储与检索

### 5.1 Small-to-Big 向量存储 (vector_store.py)

**新增架构**: 支持父块缓存、子块检索的 Small-to-Big 模式。

```python
class ParentChildVectorStore:
    """Small-to-Big 检索架构"""

    def add_chunks(self, chunks: List[ParentChildChunk]) -> int:
        """添加父子块：子块存向量，父块存缓存"""
        # 1. 存储父块到缓存
        for chunk in chunks:
            self._parent_cache[chunk.parent_id] = chunk.parent_content

        # 2. 创建子块 Document 并存向量
        child_docs = [Document(page_content=c.child_content, metadata={...}) for c in chunks]
        self.child_store.add_documents(child_docs)

        # 3. 持久化父块缓存
        self._save_parent_cache()

    def retrieve(self, query: str, k: int = 5) -> List[Dict]:
        """Small-to-Big 检索：检索子块，返回父块"""
        # 1. 检索子块
        child_results = self.child_store.similarity_search(query, k=k)

        # 2. 获取父块（去重）
        parent_ids_seen = set()
        parent_results = []
        for child_doc in child_results:
            parent_id = child_doc.metadata.get("parent_id")
            if parent_id and parent_id not in parent_ids_seen:
                parent_ids_seen.add(parent_id)
                parent_content = self._parent_cache.get(parent_id)
                parent_results.append({"content": parent_content, ...})

        return parent_results
```

### 5.2 检索工具集

| 工具名 | 功能描述 | 使用场景 |
|--------|----------|----------|
| `knowledge_search_tool` | 语义相似度检索 | 查找特定知识点 |
| `check_technical_indicators` | 技术指标检索 | 维度/地形过滤检索 |
| `full_document_tool` | 获取完整文档内容 | 深度阅读全篇 |
| `document_list_tool` | 列出知识库文档 | 了解资料范围 |

---

## 6. 任务管理与并行处理

### 6.1 任务管理器 (task_manager.py)

```python
class DocumentTaskManager:
    """文档处理任务管理器 - 线程池并行处理"""

    MAX_WORKERS = 4      # 最大并行文档数
    MAX_RETRIES = 3      # 最大重试次数
```

### 6.2 带进度回调的处理（使用统一切片）

```python
def add_document_with_progress(...):
    # 1. 文件类型检测 (~5%)
    progress_callback(5.0, "文件类型检测")

    # 2. 加载文档 + OCR 预处理 (~15%) - OCR 已内嵌
    progress_callback(15.0, "加载文档")

    # 3. 推断文档类型 (~30%)
    progress_callback(30.0, "推断文档类型")

    # 4. 文档切片 (~50%) - 使用 UnifiedMarkdownSlicer
    progress_callback(50.0, "文档切片")
    splits = SlicingStrategyFactory.slice_document(full_content, doc_type, metadata)

    # 5. 元数据注入 (~70%)
    progress_callback(70.0, "元数据注入完成")

    # 6. 向量嵌入 (~85%)
    progress_callback(85.0, "向量生成完成")
```

---

## 7-12. 其他章节

（与原文档保持一致，主要变化已在 1-6 章节中说明）

---

## 12.4 关键文件列表（更新）

| 文件 | 用途 | 优化相关 |
|------|------|----------|
| `src/rag/slicing/slicer.py` | 统一切片器 | Small-to-Big 模式 |
| `src/rag/metadata/definitions.py` | 统一维度定义 | 单一数据源 |
| `src/rag/core/vector_store.py` | Small-to-Big 架构 | 检索优化 |
| `src/rag/utils/loaders.py` | 文档加载器 | OCR 内嵌 |
| `src/rag/core/tools.py` | 检索工具 | Hybrid Search |
| `src/rag/config.py` | RAG 配置 | Embedding 维度 |

---

**文档版本**: 4.0
**最后更新**: 2026-04-21
**维护者**: Village Planning Agent Team