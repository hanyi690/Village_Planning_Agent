# RAG 知识检索系统

> **更新日期**: 2026-05-17
> **版本**: v7.0

## 一、系统概述

RAG（Retrieval-Augmented Generation）知识检索系统为乡村规划智能体提供动态知识支持。系统采用 **Small-to-Big + 层级感知** 架构，实现从精确检索到上下文返回的智能检索流程。

### 1.1 核心特性

| 特性 | 说明 |
|------|------|
| 层级切片 | 利用 Markdown 标题结构构建层级树（HierarchySlicer） |
| Small-to-Big 检索 | 检索子块，返回合并内容（含完整上下文） |
| LLM 大纲矫正 | Flash LLM 推断标题层级，修复格式错误 |
| 树形索引 | O(1) 查找父块，支持子块内容合并 |
| 元数据自动提取 | 从文件路径、文件名提取分类信息 |
| LLM Flash 类型推断 | 根据标题自动推断文档类型 |

### 1.2 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        RAG 知识检索系统                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │  文档导入    │    │  层级切片    │    │  向量存储    │              │
│  │  MinerU      │ →  │  Hierarchy   │ →  │  ChromaDB    │              │
│  │  Docling     │    │  Slicer      │    │              │              │
│  │  MarkItDown  │    │              │    │              │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│         ↓                   ↓                   ↓                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │  元数据提取  │    │  树形索引    │    │  父块缓存    │              │
│  │  Metadata    │    │  by_id       │    │  JSON Cache  │              │
│  │  Extractor   │    │  children    │    │              │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、目录结构

### 2.1 模块文件

```
backend/app/services/modules/rag/
├── service.py               # RAG 服务核心（查询生成、检索入口）
├── chunker.py               # 层级切片器（LLM 矫正 + LangChain 切片）
├── vector_store.py          # 层级向量存储（Small-to-Big + 树形索引）
├── context.py               # 文档上下文管理器
├── knowledge_manager.py     # 异步任务管理
└── utils/
    ├── document_loader.py   # 文档加载器（重导出）
    └── metadata_extractor.py # 元数据提取器
```

### 2.2 数据目录

```
data/RAG_doc/
├── 01_专业教材/
├── 02_法律法规/01_法律/
├── 03_政策文件/01_国家层面/
├── 04_技术规范/01_国家层面/
├── 05_上位规划/01_广东省/
├── 06_相关案例/
├── _doc_md/                 # 解析后的 Markdown 文件
└── _cache/                  # 缓存目录（统一管理）
    ├── outline_index/       # 层级索引缓存（JSON）
    │   └── *_index.json     # 每个文档一个索引
    ├── chroma_db/           # ChromaDB 向量数据库
    │   ├── chroma.sqlite3
    │   └── d13d545a-.../
    └── hierarchy_chunks_cache.json  # 父块缓存
```

---

## 三、核心组件详解

### 3.1 文档加载器

**文件**: `backend/app/utils/document_loader.py`

解析器选择优先级：

| 优先级 | 解析器 | 适用场景 | 特点 |
|--------|--------|----------|------|
| 1 | MinerU | 扫描版 PDF | 云端 API，高质量，支持所有格式 |
| 2 | Docling | PDF/DOCX/PPTX | 本地解析，速度快 |
| 3 | MarkItDown | 通用格式 | 降级兜底，快速解析 |

**关键函数**: `_create_loader()` 根据配置 `DOCUMENT_PARSER` 选择解析器。

```python
# 配置选择
DOCUMENT_PARSER = "mineru"  # mineru | docling | markitdown

# 使用示例
from app.utils.document_loader import _create_loader, FileTypeDetector

real_type = FileTypeDetector.detect(file_path)
loader = _create_loader(file_path, real_type, category="policies")
documents = loader.load()
```

### 3.2 层级切片器

**文件**: `backend/app/services/modules/rag/chunker.py`

#### 核心数据结构

```python
@dataclass
class HierarchyChunk:
    content: str              # 切片内容
    chunk_id: str             # 唯一 ID（source_index_hash）
    depth: int                # 标题层级 (1=章, 2=节, 3=条, 4=项)
    parent_id: Optional[str]  # 直接父块的 chunk_id
    ancestors: List[str]      # 祖先标题路径 ["章", "节", "条"]
    section_title: str        # 当前标题
    metadata: Dict            # 元数据（source, has_table, char_count, is_placeholder）
```

#### 树形索引结构

```python
@dataclass
class HierarchyTreeIndex:
    by_id: Dict[str, Dict]      # chunk_id -> chunk_dict（O(1) 查找）
    children: Dict[str, List]   # parent_id -> [child_ids]（子块列表）
    by_section: Dict[str, str]  # section_title -> chunk_id（标题查找）
```

#### LLM 大纲矫正

`LLMOutlineCorrector` 使用 Flash LLM 推断标题层级：

1. **提取候选标题**：支持多种格式
   - Markdown 标题（`# ## ###`）
   - 中文章节（第一章、第二节）
   - 中文数字条款（第一条、第二款）
   - 阿拉伯数字编号（1.1、2.3.4）
   - 罗马数字编号（I.、II.）

2. **LLM 推断层级**：批量处理（每批 100 个标题）
   ```python
   # 输出格式
   [{"index": 0, "level": 1, "type": "chapter"}, ...]
   ```

3. **重写 Markdown 标题**：统一为 `#` 格式

#### 缓存机制

`OutlineIndexManager` 管理 `outline_index/` 目录：

```python
@dataclass
class OutlineIndex:
    source_name: str           # 文档名称
    source_path: str           # 原始路径
    file_hash: str             # MD5 哈希（增量更新）
    created_at: str            # 创建时间
    heading_count: int         # 标题数量
    chunk_count: int           # 切片数量
    level_distribution: Dict   # 层级分布 {1: 5, 2: 12, 3: 20}
    corrected_content: str     # 矫正后的 Markdown
    chunks: List[Dict]         # 切片列表
    tree_index: Dict           # 树形索引（by_id, children, by_section）
```

**增量更新**：文件哈希变化时才重新处理。

#### 空标题节点修复

`_fix_orphan_headings()` 方法处理层级结构缺陷：

1. **检测条件**：
   - `char_count < 50`（内容很短）
   - 无子节点
   - 内容仅标题

2. **修复策略**：
   - 利用编号连续性（2 → 2.1）判断父子关系
   - 将短标题与后续节点合并
   - 更新 `ancestors` 和 `parent_id`

### 3.3 层级向量存储

**文件**: `backend/app/services/modules/rag/vector_store.py`

#### Small-to-Big 检索流程

```
Query → 向量搜索 → 命中子块 → 树形索引查找 → 合并内容 → 返回
```

#### 核心检索方法 `retrieve()`

```python
def retrieve(self, query: str, k: int = 5, score_threshold: float = 1.5) -> List[Dict]:
    """
    Small-to-Big 检索
    
    流程：
    1. 向量搜索命中子块
    2. 从树形索引获取完整信息
    3. 判断是否需要合并子块内容：
       - is_placeholder=True：占位切片，需合并
       - char_count < 50：只有标题，需合并
    4. 合并所有子块内容返回
    """
```

#### 树形索引加载

```python
def load_all_tree_indices(self) -> None:
    """加载所有 outline_index 中的树形索引"""
    # 合并所有 *_index.json 的 tree_index
    combined_by_id = {}
    combined_children = {}
    combined_by_section = {}
```

#### 父块缓存

```python
# 内存缓存
_parent_cache: OrderedDict[str, str]  # chunk_id -> content
_parent_metadata: OrderedDict[str, Dict]  # chunk_id -> metadata

# LRU 淘汰
MAX_PARENT_CACHE_SIZE = 2000

# 持久化
PARENT_CACHE_FILE = "hierarchy_chunks_cache.json"
```

### 3.4 元数据提取器

**文件**: `backend/app/services/modules/rag/utils/metadata_extractor.py`

#### 提取来源

| 来源 | 字段 | 示例 |
|------|------|------|
| 目录路径 | category, subcategory, level | 专业教材、法律法规/法律/国家 |
| 文件名 | seq, title, standard_no | 01、村庄规划用地分类指南、GB/T 32000-2024 |
| 文档内容 | parser, parse_time | mineru、2.5s |
| LLM Flash | doc_type, keywords | textbook、["用地分类", "规划指标"] |

#### 类别映射

```python
CATEGORY_MAPPING = {
    "01_专业教材": ("专业教材", "", ""),
    "02_法律法规/01_法律": ("法律法规", "法律", "国家"),
    "02_法律法规/02_地方性法规": ("法律法规", "地方性法规", "地方"),
    "03_政策文件/01_国家层面": ("政策文件", "国家政策", "国家"),
    "04_技术规范/01_国家层面": ("技术规范", "国家标准", "国家"),
    "05_上位规划/01_广东省": ("上位规划", "", "广东省"),
    "06_相关案例": ("相关案例", "", ""),
}
```

#### LLM Flash 类型推断

```python
async def infer_doc_type_with_llm(title: str, content: str) -> Dict:
    """
    使用 LLM Flash 推断文档类型
    
    类型规则：
    - textbook: 教材、原理、教程、导论
    - guide: 指南、手册、指导、规程
    - policy: 条例、规定、办法、通知、意见
    - standard: 标准、规范（GB、CJJ 等）
    - case: 规划、设计、方案、案例
    - report: 一般报告
    """
```

### 3.5 RAG 服务

**文件**: `backend/app/services/modules/rag/service.py`

#### 核心方法

| 方法 | 功能 | 参数 |
|------|------|------|
| `generate_queries()` | LLM 生成多条检索查询 | cfg, state |
| `search()` | 向量搜索 | query, top_k, parent_level |
| `add_document()` | 添加文档（增量） | file_path, category, doc_type |
| `add_markdown_document()` | 导入 Markdown | file_path, use_llm_inference |
| `get_context()` | 获取格式化上下文 | dim_key, state, cfg |
| `format_for_prompt()` | 格式化检索结果 | results |

#### 分层查询生成

```python
def _build_query_prompt(dim_name, task_desc, layer, dependency_summaries) -> str:
    """
    根据 Layer 构建不同的 Prompt
    
    Layer 1（现状分析）：
    - 侧重技术方法和标准规范
    - 检索：技术规范、数据采集方法、评价指标
    
    Layer 3（详细规划）：
    - 侧重规划编制标准和案例
    - 检索：用地指标、设施配置标准、政策法规
    """
```

#### 查询缓存

```python
_query_cache: Dict[str, List[str]] = {}
_query_cache_ttl: int = 3600  # 1 小时

# 缓存键：维度 + 依赖列表 + layer
cache_key = hashlib.md5(f"{dim_key}:{deps_str}".encode()).hexdigest()
```

---

## 四、完整处理流程

### 4.1 构建（入库）流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           文档入库流程                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. 文档加载                                                            │
│     ┌──────────┐    ┌──────────┐    ┌──────────┐                       │
│     │ 原始文件 │ →  │ 解析器   │ →  │ Markdown │                       │
│     │ PDF/DOCX │    │ MinerU   │    │ 内容     │                       │
│     └──────────┘    └──────────┘    └──────────┘                       │
│                                                                         │
│  2. 元数据提取                                                          │
│     ┌──────────┐    ┌──────────┐    ┌──────────┐                       │
│     │ 文件路径 │ →  │ Metadata │ →  │ category │                       │
│     │ 文件名   │    │ Extractor│    │ title    │                       │
│     └──────────┘    └──────────┘    │ doc_type │                       │
│                                      └──────────┘                       │
│                                                                         │
│  3. 层级切片                                                            │
│     ┌──────────┐    ┌──────────┐    ┌──────────┐                       │
│     │ Markdown │ →  │ LLM 矫正 │ →  │ LangChain│                       │
│     │ 内容     │    │ 大纲层级 │    │ 切片     │                       │
│     └──────────┘    └──────────┘    └──────────┘                       │
│          ↓                                    ↓                          │
│     ┌──────────┐                       ┌──────────┐                    │
│     │ 清理噪声 │                       │ 树形索引 │                    │
│     │ 目录/注释│                       │ by_id   │                    │
│     └──────────┘                       │ children │                    │
│                                        └──────────┘                    │
│                                                                         │
│  4. 向量存储                                                            │
│     ┌──────────┐    ┌──────────┐    ┌──────────┐                       │
│     │ 切片列表 │ →  │ Embedding │ →  │ ChromaDB │                       │
│     │ Hierarchy│    │ Model    │    │ 向量库   │                       │
│     │ Chunk    │    └──────────┘    └──────────┘                       │
│     └──────────┘          ↓                ↓                            │
│                     ┌──────────┐    ┌──────────┐                       │
│                     │ 向量缓存 │    │ 父块缓存 │                       │
│                     └──────────┘    └──────────┘                       │
│                                                                         │
│  5. 索引持久化                                                          │
│     ┌──────────────────────────────────────────┐                        │
│     │ outline_index/*.json                    │                        │
│     │ - file_hash（增量更新）                 │                        │
│     │ - tree_index（by_id, children）         │                        │
│     │ - chunks 列表                           │                        │
│     └──────────────────────────────────────────┘                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 检索流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           知识检索流程                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. 查询生成                                                            │
│     ┌──────────┐    ┌──────────┐    ┌──────────┐                       │
│     │ 维度配置 │ →  │ LLM Flash│ →  │ 多条查询 │                       │
│     │ 依赖状态 │    │ 生成查询 │    │ 4-8 条   │                       │
│     └──────────┘    └──────────┘    └──────────┘                       │
│                                                                         │
│  2. 向量搜索                                                            │
│     ┌──────────┐    ┌──────────┐    ┌──────────┐                       │
│     │ 查询文本 │ →  │ Embedding │ →  │ ChromaDB │                       │
│     │         │    │ 向量化   │    │ 相似搜索 │                       │
│     └──────────┘    └──────────┘    └──────────┘                       │
│                                            ↓                            │
│                                     ┌──────────┐                        │
│                                     │ 命中子块 │                        │
│                                     │ + 分数   │                        │
│                                     └──────────┘                        │
│                                                                         │
│  3. 树形索引查找                                                        │
│     ┌──────────┐    ┌──────────┐    ┌──────────┐                       │
│     │ 子块 ID  │ →  │ tree_index│ →  │ 完整信息 │                       │
│     │         │    │ by_id    │    │ ancestors│                       │
│     └──────────┘    └──────────┘    │ children │                       │
│                                      └──────────┘                       │
│                                                                         │
│  4. 内容合并（Small-to-Big）                                            │
│     ┌──────────────────────────────────────────┐                        │
│     │ 判断是否需要合并：                       │                        │
│     │ - is_placeholder=True → 合并子块         │                        │
│     │ - char_count < 50 → 合并子块             │                        │
│     │ - 否则 → 返回子块本身                    │                        │
│     └──────────────────────────────────────────┘                        │
│                     ↓                                                    │
│     ┌──────────────────────────────────────────┐                        │
│     │ 合并逻辑：                               │                        │
│     │ merged_content = chunk.content           │                        │
│     │ for child_id in children[chunk_id]:      │                        │
│     │     merged_content += child.content      │                        │
│     └──────────────────────────────────────────┘                        │
│                                                                         │
│  5. 结果格式化                                                          │
│     ┌──────────────────────────────────────────┐                        │
│     │ {                                       │                        │
│     │   "content": "合并后的内容",            │                        │
│     │   "score": 0.85,                        │                        │
│     │   "metadata": {                         │                        │
│     │     "ancestors": ["章", "节"],          │                        │
│     │     "depth": 3,                         │                        │
│     │     "section_title": "2.1.1 条款",      │                        │
│     │     "source": "文档名.md"                │                        │
│     │   }                                     │                        │
│     │ }                                       │                        │
│     └──────────────────────────────────────────┘                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 五、使用指南

### 5.1 命令行导入

```bash
# 预览文件列表（不导入）
python scripts/import_rag_documents.py --dry-run

# 导入所有文档
python scripts/import_rag_documents.py

# 限制导入数量
python scripts/import_rag_documents.py --limit 10

# 指定导入目录
python scripts/import_rag_documents.py --dir data/RAG_doc/04_技术规范

# 不使用 LLM Flash 推断类型
python scripts/import_rag_documents.py --no-llm
```

### 5.2 API 使用

```python
from app.services.modules.rag.service import RagService

# 获取单例实例
rag = RagService.get_instance()

# 导入 Markdown 文档
result = await rag.add_markdown_document(
    "data/RAG_doc/_doc_md/01_专业教材/01 村庄规划原理.md",
    use_llm_inference=True,
)

# 向量搜索
results = await rag.search("历史文化保护规划技术规范", top_k=5)

# 获取格式化上下文（用于 Prompt 注入）
context = rag.format_for_prompt(results)

# 获取知识库统计
stats = rag.get_stats()
```

### 5.3 分层检索控制

```python
# Layer 级别控制（最高优先级）
# 在 phases.yaml 中配置
layer1:
  rag_enabled: true   # 现状分析层：启用
layer2:
  rag_enabled: false  # 规划思路层：禁用
layer3:
  rag_enabled: true   # 详细规划层：启用

# Session 级别控制
session.rag_enabled = False

# Dimension 级别控制
dimension.rag_query = "用地分类标准"
```

---

## 六、配置说明

### 6.1 环境变量

```bash
# 文档解析器
DOCUMENT_PARSER=mineru          # mineru | docling | markitdown
MINERU_TOKEN=xxx                # MinerU API Token

# Embedding 配置
EMBEDDING_PROVIDER=local        # local | aliyun
EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
EMBEDDING_DEVICE=cpu            # cpu | cuda | mps

# 阿里云 Embedding
DASHSCOPE_API_KEY=xxx
ALIYUN_EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024

# 向量数据库
CHROMA_COLLECTION_NAME=rural_planning
CHROMA_PERSIST_DIR=data/RAG_doc/_cache/chroma_db

# 切片配置
CHUNK_SIZE=2500
CHUNK_OVERLAP=500

# 查询缓存
QUERY_CACHE_TTL=3600            # 秒
```

### 6.2 目录路径映射

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `RAG_DOC_DIR` | `data/RAG_doc` | 知识库根目录 |
| `OUTLINE_INDEX_DIR` | `data/RAG_doc/_cache/outline_index` | 层级索引缓存 |
| `CHROMA_PERSIST_DIR` | `data/RAG_doc/_cache/chroma_db` | 向量数据库 |

---

## 七、关键文件索引

| 功能 | 文件路径 | 核心类/函数 |
|------|----------|-------------|
| 层级切片器 | `chunker.py` | `HierarchySlicer`, `LLMOutlineCorrector` |
| 树形索引 | `chunker.py` | `HierarchyTreeIndex`, `OutlineIndexManager` |
| 向量存储 | `vector_store.py` | `HierarchyVectorStore`, `retrieve()` |
| RAG 服务 | `service.py` | `RagService`, `generate_queries()` |
| 元数据提取 | `utils/metadata_extractor.py` | `MetadataExtractor` |
| 文档加载 | `app/utils/document_loader.py` | `_create_loader()`, `MarkItDownLoader` |
| 导入脚本 | `scripts/import_rag_documents.py` | `import_document()` |

---

## 八、已知问题与解决方案

### 8.1 空标题节点问题

**现象**: 检索返回只有标题的切片（如 `2 历史文化街区保护规划`）

**原因**: 
- Markdown 标题标记错误（`# 2` 和 `# 2.1` 被误设为同级）
- LLM 大纲矫正未能正确推断父级关系

**解决方案**: `_fix_orphan_headings()` 方法（chunker.py 第 888-953 行）
- 检测短标题节点（char_count < 50）
- 利用编号连续性判断父子关系
- 合并到后续节点

### 8.2 检索词不匹配问题

**现象**: 查询词与实际检索词不符

**原因**: 
- LLM 查询生成结果被缓存
- 查询缓存键未包含足够上下文

**解决方案**:
- 检查 `_query_cache` 是否过期
- 确认缓存键包含维度 + 依赖 + layer

### 8.3 内容截断问题

**现象**: 返回内容只有前 200 字符

**原因**: 
- `RetrievedChunk.content_preview` 截断
- SSE 事件中 `snippet` 截断

**解决方案**: 
- 检查 `vector_store.py` 的 `retrieve()` 方法
- 确认返回的是 `content` 而非 `content_preview`

---

## 九、更新历史

| 日期 | 版本 | 更新内容 |
|------|------|----------|
| 2026-05-17 | v7.0 | 完整重写文档，补充树形索引、Small-to-Big 流程 |
| 2026-05-16 | v6.0 | 重写层级切片，集成 LLM 大纲矫正 |
| 2026-05-16 | v5.0 | 新增 MetadataExtractor + LLM Flash |
| 2026-05-16 | v4.0 | 删除不适配文件，简化架构 |
