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
│  │  │ (加载器) │  │ (切片器) │  │ (元数据) │  │ (嵌入)   │       │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 目录结构

```
src/rag/
├── __init__.py                    # 模块入口
├── config.py                      # RAG 配置文件
├── build.py                       # 知识库构建脚本
│
├── core/                          # 核心实现
│   ├── __init__.py
│   ├── cache.py                  # 向量数据库缓存管理器
│   ├── context_manager.py        # 文档上下文管理器
│   ├── kb_manager.py             # 知识库增量管理器
│   ├── task_manager.py           # 文档处理任务管理器（并行处理）
│   ├── summarization.py          # 层次化摘要系统
│   └── tools.py                  # Agent 工具集定义
│
├── metadata/                      # 元数据管理
│   ├── __init__.py
│   ├── injector.py               # 元数据注入器
│   └── dimension_annotator.py    # 语义维度标注器
│   └── tagging_rules.py          # 标注规则配置
│
├── slicing/                       # 切片策略
│   ├── __init__.py
│   └ strategies.py              # 差异化切片策略
│
├── utils/                         # 工具函数
│   ├── __init__.py
│   └ loaders.py                 # 文档加载器（MarkItDown）
│   └ ocr_preprocessor.py        # OCR 输出预处理
│
└── visualize/                     # 可视化工具
    ├── __init__.py
    └ inspector.py               # 切片检查器
```

---

## 2. 文档处理流程

### 2.1 处理流程概览

文档处理分为 8 个阶段，每个阶段都有明确的进度节点：

| 进度 | 阶段 | 操作内容 | 预估耗时 |
|------|------|----------|----------|
| 5% | 文件类型检测 | FileTypeDetector.detect() | ~0.1s |
| 15% | 文档加载 | MarkItDownLoader.load() | 5-120s |
| 25% | OCR 预处理 | OCRPreProcessor.preprocess() | 1-5s |
| 30% | 文档类型推断 | infer_doc_type() | ~0.1s |
| 50% | 文档切片 | SlicingStrategyFactory.slice_document() | 1-5s |
| 70% | 元数据注入 | MetadataInjector.inject_batch() | 0.5-2s |
| 85% | 向量嵌入 | vectorstore.add_documents() | 1-3s |
| 100% | 索引更新 & 缓存清理 | _update_document_index() | ~0.5s |

### 2.2 文档加载器 (loaders.py)

**核心功能**: 使用 Microsoft MarkItDown 库统一处理多种文档格式。

#### 支持的文档格式

| 格式 | 扩展名 | 加载方式 | 特殊处理 |
|------|--------|----------|----------|
| Word | `.doc`, `.docx` | MarkItDown | 无 |
| PDF | `.pdf` | MarkItDown + OCR 备用 | OCR 输出预处理 |
| PowerPoint | `.ppt`, `.pptx` | MarkItDown | 无 |
| Markdown | `.md` | MarkItDown | 无 |
| Text | `.txt` | MarkItDown | 无 |

#### 文件类型检测

```python
class FileTypeDetector:
    """文件类型检测器 - 解决扩展名与实际类型不一致问题"""

    @staticmethod
    def detect(file_path: Path) -> str:
        """
        检测文件实际类型

        优先级：
        1. 文件内容魔数（Magic Number）
        2. 文件扩展名

        Returns:
            str: 文件类型标识 ('pdf', 'docx', 'pptx', 'md', 'txt')
        """
        # PDF 魔数检测
        with open(file_path, 'rb') as f:
            header = f.read(8)
            if header.startswith('%PDF'):
                return 'pdf'

        # DOCX 魔数检测（ZIP 格式，内部有特定结构）
        if file_path.suffix.lower() in ['.docx', '.pptx']:
            try:
                import zipfile
                with zipfile.ZipFile(file_path) as z:
                    if 'word/document.xml' in z.namelist():
                        return 'docx'
                    if 'ppt/presentation.xml' in z.namelist():
                        return 'pptx'
            except:
                pass

        # 默认使用扩展名
        return file_path.suffix.lower().replace('.', '')
```

#### 加载器实现

```python
def _create_loader(file_path: Path, file_type: str, category: str = None):
    """
    创建文档加载器

    Args:
        file_path: 文件路径
        file_type: 文件类型
        category: 文档类别

    Returns:
        MarkItDownLoader 实例
    """
    from markitdown import MarkItDown

    converter = MarkItDown()
    # MarkItDown 会自动处理各种格式
    return MarkItDownLoader(file_path, converter, category)
```

### 2.3 OCR 预处理 (ocr_preprocessor.py)

**核心功能**: 处理扫描版 PDF 的 OCR 输出格式，清理杂乱文本。

```python
class OCRPreProcessor:
    """OCR 输出预处理器"""

    OCR_MARKERS = [
        "",  # 换页符
        "OCR", "扫描", "识别",
    ]

    def is_ocr_output(self, text: str) -> bool:
        """
        检测是否为 OCR 输出

        特征：
        - 大量换页符
        - 混乱的换行
        - 低质量的文本结构
        """
        # 换页符密度检测
        form_feed_count = text.count("")
        if form_feed_count > 5:
            return True

        # 行长度异常检测
        lines = text.split("\n")
        short_lines = sum(1 for line in lines if len(line.strip()) < 10)
        if short_lines / len(lines) > 0.5:
            return True

        return False

    def preprocess(self, text: str) -> str:
        """
        预处理 OCR 输出

        操作：
        1. 清理换页符
        2. 合理重组换行
        3. 保留表格结构
        """
        # 清理换页符
        text = text.replace("", "\n")

        # 合理重组段落
        lines = text.split("\n")
        paragraphs = []
        current_para = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_para:
                    paragraphs.append(" ".join(current_para))
                    current_para = []
            elif stripped.endswith(('。', '；', '：', '！', '？')):
                current_para.append(stripped)
                paragraphs.append(" ".join(current_para))
                current_para = []
            else:
                current_para.append(stripped)

        if current_para:
            paragraphs.append(" ".join(current_para))

        return "\n\n".join(paragraphs)
```

---

## 3. 切片策略详解

### 3.1 切片策略工厂

**文件位置**: `src/rag/slicing/strategies.py`

```python
class SlicingStrategyFactory:
    """切片策略工厂 - 根据文档类型选择合适的切片器"""

    @staticmethod
    def slice_document(
        content: str,
        doc_type: str,
        metadata: dict
    ) -> list[str]:
        """
        切片文档

        Args:
            content: 文档内容
            doc_type: 文档类型 (policy/standard/case/guide/report/textbook)
            metadata: 基础元数据

        Returns:
            list[str]: 切片列表
        """
        slicer = SLICER_MAP.get(doc_type, DefaultSlicer())
        return slicer.slice(content, metadata)
```

### 3.2 差异化切片策略

| 文档类型 | 切片策略 | 分割依据 | 切片大小 |
|----------|----------|----------|----------|
| policy | 政策条款切片 | "第X条" 条款边界 | 每条完整保留 |
| standard | 标准章节切片 | 章节编号 (4.1, 4.2) | 500-2000字 |
| case | 案例阶段切片 | 项目阶段标题 | 800-3000字 |
| guide | 指南知识点切片 | 一级标题 + 知识块 | 500-1500字 |
| report | 报告段落切片 | 一级/二级标题 | 800-2000字 |
| textbook | 教材章节切片 | 章节标题 | 1000-3000字 |
| default | 通用递归切片 | RecursiveCharacterTextSplitter | 2500字，500字重叠 |

#### 政策文档切片器

```python
class PolicySlicer(BaseSlicer):
    """
    政策文档切片器

    特点：按"第 X 条"分割，保持条款完整性
    适用：条例、规定、办法、通知等政策文件
    """

    def slice(self, text: str, metadata: dict) -> list[str]:
        # 匹配条款模式
        pattern = r'第[一二三四五六七八九十百\d]+条'

        # 找到所有条款边界
        matches = list(re.finditer(pattern, text))

        if not matches or len(matches) < 3:
            # 条款太少，使用通用切片
            return DefaultSlicer().slice(text, metadata)

        slices = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

            chunk = text[start:end].strip()
            if len(chunk) >= 100:  # 过滤太短的条款
                slices.append(chunk)

        return slices
```

#### 标准规范切片器

```python
class StandardSlicer(BaseSlicer):
    """
    标准规范切片器

    特点：按章节编号分割（如 4.1, 4.2, 5.1.1）
    适用：国家标准、行业规范、技术导则
    """

    def slice(self, text: str, metadata: dict) -> list[str]:
        # 匹配章节编号
        pattern = r'\n\d+\.\d+(?:\.\d+)*[\s]+[^\n]+'

        matches = list(re.finditer(pattern, text))

        if not matches:
            return DefaultSlicer().slice(text, metadata)

        # 按章节分割
        slices = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

            chunk = text[start:end].strip()
            if len(chunk) >= 200:
                slices.append(chunk)

        return slices
```

#### 案例文档切片器

```python
class CaseSlicer(BaseSlicer):
    """
    案例文档切片器

    特点：按项目阶段分割
    适用：规划案例、示范项目、实践报告
    """

    PHASE_KEYWORDS = [
        "项目背景", "规划思路", "设计理念",
        "设计方案", "规划方案", "实施方案",
        "实施过程", "建设过程", "建设成果",
        "经验总结", "启示", "成效"
    ]

    def slice(self, text: str, metadata: dict) -> list[str]:
        # 找到项目阶段标题
        phase_positions = []
        for keyword in self.PHASE_KEYWORDS:
            pattern = rf'[一二三四五六七八九十\d]*[\s、]*{keyword}'
            matches = re.finditer(pattern, text)
            for match in matches:
                phase_positions.append((match.start(), keyword))

        # 按位置排序
        phase_positions.sort(key=lambda x: x[0])

        if len(phase_positions) < 2:
            return DefaultSlicer().slice(text, metadata)

        # 按阶段分割
        slices = []
        for i, (pos, keyword) in enumerate(phase_positions):
            end = phase_positions[i + 1][0] if i + 1 < len(phase_positions) else len(text)
            chunk = text[pos:end].strip()
            if len(chunk) >= 300:
                slices.append(chunk)

        return slices
```

---

## 4. 元数据注入系统

### 4.1 元数据注入器 (injector.py)

**核心功能**: 为文档切片注入维度标签、地形类型、文档类型等元数据。

```python
class MetadataInjector:
    """元数据注入器"""

    def inject_batch(
        self,
        documents: list[Document],
        category: str = None,
        doc_type: str = None,
        dimension_tags: list[str] = None,
        terrain: str = None,
    ) -> None:
        """
        批量注入元数据

        Args:
            documents: 文档切片列表
            category: 文档类别 (手动指定或自动)
            doc_type: 文档类型
            dimension_tags: 维度标签（手动指定）
            terrain: 地形类型（手动指定）
        """
        # 1. 如果手动指定了元数据，直接使用
        if dimension_tags:
            manual_tags = ",".join(dimension_tags)
        else:
            manual_tags = None

        for doc in documents:
            # 2. 基础元数据
            doc.metadata["category"] = category or "policies"
            doc.metadata["document_type"] = doc_type or "unknown"

            # 3. 维度标签（手动优先，否则自动标注）
            if manual_tags:
                doc.metadata["dimension_tags"] = manual_tags
            else:
                auto_tags = self._extract_dimensions(doc.page_content)
                doc.metadata["dimension_tags"] = ",".join(auto_tags) if auto_tags else ""

            # 4. 地形类型
            if terrain:
                doc.metadata["terrain"] = terrain
            else:
                auto_terrain = self._extract_terrain(doc.page_content)
                doc.metadata["terrain"] = auto_terrain or "all"
```

### 4.2 维度标注规则

**文件位置**: `src/rag/metadata/tagging_rules.py`

系统定义了 24 个分析维度及其关键词映射：

```python
DIMENSION_KEYWORDS = {
    # Layer 1 - 基础分析维度
    "land_use": ["用地", "土地", "三区三线", "宅基地", "建设用地", "耕地", "农用地"],
    "traffic": ["道路", "交通", "公路", "街道", "停车场", "交通组织"],
    "infrastructure": ["给排水", "电力", "通信", "燃气", "供热", "管网", "基础设施"],
    "public_services": ["公共服务", "学校", "医院", "养老", "文化站", "健身设施"],
    "ecological_green": ["生态", "绿化", "景观", "水体", "湿地", "绿地率"],
    "historical_culture": ["遗产", "文物", "古建筑", "传统建筑", "历史文化", "风貌"],
    "disaster_prevention": ["防灾", "避难", "消防", "洪水", "地质灾害", "应急"],
    "natural_environment": ["自然环境", "地形", "地貌", "气候", "水文", "土壤"],
    "location": ["区位", "位置", "周边", "距离", "可达性", "交通区位"],
    "socio_economic": ["人口", "经济", "产业", "收入", "就业", "社会"],
    "villager_wishes": ["村民意愿", "需求", "诉求", "意愿调查", "问卷调查"],
    "superior_planning": ["上位规划", "总体规划", "国土空间规划", "约束条件"],
    "architecture": ["建筑", "民居", "农房", "住宅", "建筑风格", "建筑布局"],
    "public_facilities": ["设施", "配套", "服务设施", "公共设施", "基础设施配套"],
    "safety": ["安全", "消防", "治安", "应急通道", "避难场所"],
    "industry": ["产业", "农业", "旅游", "民宿", "产业园", "集体经济"],
    "heritage": ["遗产", "文物", "古建筑", "传统风貌", "历史建筑"],
}
```

### 4.3 语义维度标注器

**文件位置**: `src/rag/metadata/dimension_annotator.py`

**核心功能**: 使用 LLM 进行语义理解，自动标注维度标签。

```python
class DimensionAnnotator:
    """语义维度标注器 - 使用 LLM 自动识别维度"""

    def __init__(self, model_name: str = "deepseek-flash"):
        self.llm = create_llm(model_name)

    def annotate(self, text: str, available_dimensions: list[str]) -> list[str]:
        """
        语义标注维度

        Args:
            text: 文本内容
            available_dimensions: 可用维度列表

        Returns:
            list[str]: 匹配的维度标签列表
        """
        prompt = f"""
分析以下文本，判断它涉及哪些规划维度。

可用维度：{', '.join(available_dimensions)}

文本内容：
{text[:500]}

请返回相关的维度标签（JSON 数组格式）。
"""

        response = self.llm.invoke(prompt)
        # 解析 JSON 返回
        return self._parse_response(response)
```

---

## 5. 向量存储与检索

### 5.1 向量存储缓存 (cache.py)

**核心功能**: 懒加载向量数据库和 Embedding 模型，管理查询缓存。

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
        if self._embedding_model is None:
            provider = EMBEDDING_PROVIDER

            if provider == "local":
                self._embedding_model = HuggingFaceEmbeddings(
                    model_name=EMBEDDING_MODEL_NAME,
                    model_kwargs={'device': 'cpu'},
                    encode_kwargs={'normalize_embeddings': True}
                )
            elif provider == "aliyun":
                self._embedding_model = DashScopeEmbeddings(
                    model=ALIYUN_EMBEDDING_MODEL,
                    dashscope_api_key=ALIYUN_API_KEY
                )

        return self._embedding_model

    def get_vectorstore(self) -> Chroma:
        """
        懒加载 Chroma 向量数据库

        Returns:
            Chroma: 向量数据库实例
        """
        if self._vectorstore is None:
            embedding = self.get_embedding_model()

            self._vectorstore = Chroma(
                collection_name=CHROMA_COLLECTION_NAME,
                embedding_function=embedding,
                persist_directory=str(CHROMA_PERSIST_DIR)
            )

        return self._vectorstore
```

### 5.2 检索工具集 (tools.py)

**核心功能**: 提供 7 种检索工具供 Agent 调用。

| 工具名 | 功能描述 | 使用场景 |
|--------|----------|----------|
| `list_documents` | 列出知识库中所有可用文档 | 任务开始时了解资料范围 |
| `document_overview_tool` | 获取单个文档的执行摘要 | 快速了解文档核心内容 |
| `chapter_content_tool` | 获取章节详细内容 | 深度阅读特定章节 |
| `knowledge_search_tool` | 语义相似度检索 | 查找特定知识点 |
| `key_points_search_tool` | 搜索文档关键要点 | 精确查找核心信息 |
| `full_document_tool` | 获取完整文档内容 | 深度阅读全篇 |
| `check_technical_indicators` | 技术指标检索 | 维度/地形过滤检索 |

#### 核心检索工具实现

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
    # 获取向量存储
    vectorstore = get_vector_cache().get_vectorstore()

    # 构建元数据过滤条件
    filter_dict = _build_metadata_filter(dimension, terrain, doc_type)

    # 执行相似度检索
    results = vectorstore.similarity_search(
        query=query,
        k=top_k,
        filter=filter_dict
    )

    # 扩展上下文
    context_manager = DocumentContextManager()
    context_chars = CONTEXT_CHARS.get(context_mode, 300)

    expanded_results = []
    for doc in results:
        if context_chars > 0:
            expanded_text = context_manager.get_context_around_chunk(doc, context_chars)
            expanded_results.append((expanded_text, doc.metadata))
        else:
            expanded_results.append((doc.page_content, doc.metadata))

    # 格式化输出
    return format_search_results(expanded_results)
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
        # 维度标签是逗号分隔的字符串，使用 $contains 或 $in
        filter_dict["dimension_tags"] = {"$contains": dimension}

    if terrain:
        filter_dict["terrain"] = terrain

    if doc_type:
        filter_dict["document_type"] = doc_type

    return filter_dict
```

---

## 6. 任务管理与并行处理

### 6.1 任务管理器 (task_manager.py)

**核心功能**: 线程池并行处理文档，支持进度追踪和失败重试。

```python
class DocumentTaskManager:
    """
    文档处理任务管理器

    使用线程池并行处理文档，支持进度追踪和失败重试。
    """

    MAX_WORKERS = 4      # 最大并行文档数
    MAX_RETRIES = 3      # 最大重试次数

    def submit(
        self,
        file_path: str,
        process_func: Callable,
        **kwargs
    ) -> str:
        """
        提交文档处理任务

        Args:
            file_path: 文件路径
            process_func: 处理函数
            **kwargs: 额外参数

        Returns:
            str: 任务 ID
        """
        task_id = self._generate_task_id()

        # 创建任务记录
        task = TaskProgress(
            task_id=task_id,
            filename=Path(file_path).name,
            status=TaskStatus.PENDING,
            current_step="等待处理",
        )

        self._tasks[task_id] = task

        # 提交到线程池
        future = self._executor.submit(
            self._execute_task,
            task_id, file_path, process_func, kwargs
        )
        self._futures[task_id] = future

        return task_id

    def get_task(self, task_id: str) -> Optional[TaskProgress]:
        """获取单个任务状态"""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[TaskProgress]:
        """获取所有任务列表"""
        return list(self._tasks.values())
```

### 6.2 任务状态定义

```python
class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待处理
    PROCESSING = "processing"    # 正在处理
    COMPLETED = "completed"      # 完成
    FAILED = "failed"            # 失败（重试后）
    RETRYING = "retrying"        # 重试中

@dataclass
class TaskProgress:
    """任务进度信息"""
    task_id: str
    filename: str
    status: TaskStatus
    progress: float = 0.0        # 0.0 - 100.0
    current_step: str = "等待处理"
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

### 6.3 带进度回调的处理

```python
def add_document_with_progress(
    self,
    file_path: str,
    progress_callback: Callable[[float, str], None],
    category: Optional[str] = None,
    doc_type: Optional[str] = None,
    dimension_tags: Optional[List[str]] = None,
    terrain: Optional[str] = None,
) -> Dict[str, Any]:
    """
    增量添加文档（带进度回调）

    用于异步任务管理器调用，支持进度追踪。

    Args:
        file_path: 文档路径
        progress_callback: 进度回调函数 (progress: float, step: str)
        ...
    """
    # 1. 文件类型检测 (~5%)
    progress_callback(5.0, "文件类型检测")
    real_type = FileTypeDetector.detect(path)

    # 2. 加载文档 (~15%)
    progress_callback(15.0, "加载文档")
    documents = loader.load()

    # 3. OCR 预处理 (~25%)
    progress_callback(25.0, "OCR 预处理")
    if ocr_processor.is_ocr_output(full_content):
        full_content = ocr_processor.preprocess(full_content)

    # 4. 推断文档类型 (~30%)
    progress_callback(30.0, "推断文档类型")
    doc_type = infer_doc_type(source_name, full_content)

    # 5. 文档切片 (~50%)
    progress_callback(50.0, "文档切片")
    splits = SlicingStrategyFactory.slice_document(...)

    # 6. 元数据注入 (~70%)
    progress_callback(70.0, "元数据注入完成")
    injector.inject_batch(...)

    # 7. 向量嵌入 (~85%)
    progress_callback(85.0, "向量生成完成")
    vectorstore.add_documents(split_docs)

    # 8. 完成 (~100%)
    progress_callback(100.0, "完成")
```

---

## 7. 与 Agent 的集成

### 7.1 Agent 工具注册

RAG 检索工具在 Agent 系统中注册为 LangChain 工具：

```python
# src/rag/core/tools.py

from langchain_core.tools import tool
from src.tools.registry import ToolRegistry

# 注册到工具注册表
@ToolRegistry.register("knowledge_search")
@tool
def knowledge_search_tool(query: str, ...) -> str:
    """语义相似度检索工具"""
    ...

@ToolRegistry.register("document_overview")
@tool
def document_overview_tool(source: str) -> str:
    """获取文档概览"""
    ...
```

### 7.2 Agent 节点调用流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent 调用 RAG 流程                           │
└─────────────────────────────────────────────────────────────────────┘

  用户输入: "分析用地布局维度"
        │
        ↓
  ┌─────────────┐
  │  dimension_node │  规划维度分析节点
  │             │  → 确定 dimension = "land_use"
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │  Tool Registry │  查找可用工具
  │             │  → knowledge_search_tool (knowledge_search)
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │  knowledge_search_tool │  执行检索
  │             │  参数:
  │             │    query = "用地布局原则和要求"
  │             │    dimension = "land_use"
  │             │    top_k = 5
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │  ChromaDB   │  向量相似度检索
  │             │  filter = {"dimension_tags": {"$contains": "land_use"}}
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │  Context Manager │  扩展上下文
  │             │  → 为每个切片添加 300 字上下文
  └─────────────┘
        │
        ↓
  ┌─────────────┐
  │  LLM        │  基于检索结果生成分析内容
  │             │  → 生成维度分析报告
  └─────────────┘
        │
        ↓
  维度分析报告: "用地布局应遵循以下原则..."
```

### 7.3 维度节点集成示例

```python
# src/subgraphs/dimension_node.py

def analyze_dimension(state: AgentState, dimension: str) -> str:
    """
    分析单个维度

    Args:
        state: Agent 状态
        dimension: 维度键名

    Returns:
        str: 维度分析内容
    """
    # 1. 获取知识检索工具
    search_tool = ToolRegistry.get("knowledge_search")

    # 2. 构建检索查询
    query = f"{get_dimension_name(dimension)} 规划原则和要求"

    # 3. 执行检索
    knowledge_result = search_tool.invoke({
        "query": query,
        "dimension": dimension,
        "top_k": 8,
        "context_mode": "expanded"
    })

    # 4. 获取其他相关工具结果（如 GIS 数据）
    gis_result = ""
    if dimension in GIS_REQUIRED_DIMENSIONS:
        gis_tool = ToolRegistry.get("gis_data_fetch")
        gis_result = gis_tool.invoke({"dimension": dimension})

    # 5. 组装 Prompt
    prompt = DIMENSION_ANALYSIS_PROMPT.format(
        dimension_name=get_dimension_name(dimension),
        village_data=state.village_data,
        knowledge_context=knowledge_result,
        gis_context=gis_result,
    )

    # 6. LLM 生成
    response = llm.invoke(prompt)

    return response.content
```

### 7.4 检索结果格式化

```python
def format_search_results(results: List[Tuple[str, dict]]) -> str:
    """
    格式化检索结果

    输出格式：
    【知识片段 1】
    来源: 《村庄规划用地布局指南》第3章
    维度: land_use, traffic
    内容: ...
    """
    formatted = []

    for i, (content, metadata) in enumerate(results, 1):
        source = metadata.get("source", "未知来源")
        dimensions = metadata.get("dimension_tags", "")
        terrain = metadata.get("terrain", "")

        fragment = f"""【知识片段 {i}】
来源: {source}
维度: {dimensions}
地形: {terrain}
内容: {content[:500]}...
"""
        formatted.append(fragment)

    return "\n\n".join(formatted)
```

---

## 8. API 接口文档

### 8.1 同步上传接口

```
POST /api/knowledge/documents
```

**请求**: multipart/form-data
- `file`: 上传文件
- `category`: 文档类别 (可选)
- `doc_type`: 文档类型 (可选)
- `dimension_tags`: 维度标签 (逗号分隔，可选)
- `terrain`: 地形类型 (可选)

**响应**:
```json
{
  "status": "processing",
  "message": "文件已上传，正在后台处理",
  "source": "规划导则.pdf"
}
```

### 8.2 异步上传接口（并行处理）

```
POST /api/knowledge/documents/async
```

**响应**:
```json
{
  "task_id": "a1b2c3d4",
  "filename": "规划导则.pdf",
  "status": "pending",
  "message": "文件已提交，任务 ID: a1b2c3d4"
}
```

### 8.3 任务状态查询

```
GET /api/knowledge/tasks/{task_id}
```

**响应**:
```json
{
  "task_id": "a1b2c3d4",
  "filename": "规划导则.pdf",
  "status": "processing",
  "progress": 45.0,
  "current_step": "元数据注入",
  "error_message": null,
  "retry_count": 0,
  "created_at": "2024-04-15T10:00:00",
  "started_at": "2024-04-15T10:00:05"
}
```

### 8.4 任务列表

```
GET /api/knowledge/tasks
```

**响应**:
```json
[
  {
    "task_id": "a1b2c3d4",
    "filename": "规划导则.pdf",
    "status": "processing",
    "progress": 45.0,
    ...
  },
  {
    "task_id": "e5f6g7h8",
    "filename": "案例汇编.docx",
    "status": "completed",
    "progress": 100.0,
    ...
  }
]
```

### 8.5 文档列表

```
GET /api/knowledge/documents
```

**响应**:
```json
[
  {
    "source": "规划导则.pdf",
    "chunk_count": 45,
    "doc_type": "pdf",
    "dimension_tags": ["land_use", "traffic"],
    "terrain": "mountain",
    "category": "policies"
  }
]
```

---

## 9. 配置详解

### 9.1 RAG 配置文件

**文件位置**: `src/rag/config.py`

```python
# 向量数据库配置
VECTOR_DB_TYPE = "chroma"
CHROMA_PERSIST_DIR = PROJECT_ROOT / "knowledge_base" / "chroma_db"
CHROMA_COLLECTION_NAME = "village_planning_kb"

# Embedding 配置
EMBEDDING_PROVIDER = "local"  # local | aliyun
EMBEDDING_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIMENSIONS = 1024

# 检索配置
DEFAULT_TOP_K = 5
RETRIEVE_SCORE_THRESHOLD = 0.7
CONTEXT_CHARS = {"minimal": 0, "standard": 300, "expanded": 500}

# 切片配置
CHUNK_SIZE = 2500
CHUNK_OVERLAP = 500
KB_CATEGORIES = ["policies", "cases", "standards", "domain", "local"]

# 知识库数据目录
DATA_DIR = PROJECT_ROOT / "knowledge_base" / "data"
```

---

## 10. 扩展与定制

### 10.1 添加新的切片策略

```python
# src/rag/slicing/strategies.py

class CustomSlicer(BaseSlicer):
    """自定义切片器"""

    def slice(self, text: str, metadata: dict) -> list[str]:
        # 实现自定义切片逻辑
        ...

# 注册切片器
SLICER_MAP["custom_type"] = CustomSlicer()
```

### 10.2 添加新的维度关键词

```python
# src/rag/metadata/tagging_rules.py

DIMENSION_KEYWORDS["new_dimension"] = [
    "关键词1", "关键词2", "关键词3"
]
```

### 10.3 更换 Embedding 模型

```python
# src/rag/config.py

EMBEDDING_PROVIDER = "aliyun"
ALIYUN_EMBEDDING_MODEL = "text-embedding-v4"
```

---

**文档版本**: 2.0
**最后更新**: 2024-04-15
**维护者**: Village Planning Agent Team