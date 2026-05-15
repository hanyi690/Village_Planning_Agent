# RAG 知识库架构

本文档详细说明 RAG 知识检索系统的架构设计及在维度执行中的使用方式。

> **更新日期**: 2026-05-15
> **版本**: v5.0

## 目录

- [概述](#概述)
- [文档切片策略](#文档切片策略)
- [知识库组成](#知识库组成)
- [向量存储架构](#向量存储架构)
- [检索 Query 生成](#检索-query-生成)
- [分层检索机制](#分层检索机制)
- [元数据注入](#元数据注入)
- [知识检索工具集](#知识检索工具集)
- [关键文件路径](#关键文件路径)

---

## 概述

RAG（Retrieval-Augmented Generation）系统为村庄规划 Agent 提供专业知识检索能力，支持法规标准引用、技术指标查询、案例参考等功能。

### 知识检索的两种路径

```
路径1: 自动注入（分析节点）
analyze_dimension() → RagService.get_context() → 注入 LLM Prompt
                                              ↓
                              generate_query(LLM) → search(ChromaDB)

路径2: 工具调用（Agent Tool Calling）
Agent → knowledge_search_tool() → search_knowledge() → ChromaDB
Agent → document_overview_tool() → DocumentContextManager
Agent → chapter_content_tool() → DocumentContextManager
```

---

## 文档切片策略

### 统一切片器设计

项目使用 `UnifiedMarkdownSlicer` 统一切片器，支持基于文档类型的差异化切片策略。

**文件路径**: `backend/app/services/modules/rag/chunker.py`

```python
@dataclass
class SlicerConfig:
    split_on: List[str] = None      # 正则分割模式
    chunk_size: int = 2000           # 切片大小
    overlap: int = 400               # 重叠字符数
    min_chunk: int = 100             # 最小切片长度
    parent_child: bool = False       # 是否启用父子模式
    child_size: int = 400            # 子块大小
    parent_size: int = 2000          # 父块大小
    semantic: bool = False           # 语义切分（预留）
    max_chunk: int = 2500            # 最大切片长度
```

### 差异化切片策略

| 文档类型 | chunk_size | overlap | min_chunk | max_chunk | 分割模式 | Parent-Child |
|---------|-----------|---------|-----------|-----------|---------|-------------|
| `policy` | 2500 | 500 | 50 | 2500 | 按条款 (`第X条`) | ❌ |
| `case` | 2000 | 400 | 200 | - | Parent-Child | ✅ |
| `standard` | 1500 | 300 | 80 | 1500 | 按标准编号 (`X.X.X`) | ❌ |
| `guide` | 1800 | 350 | 150 | - | Parent-Child | ✅ |
| `report` | 2000 | 400 | 100 | - | Parent-Child | ✅ |
| `textbook` | 1800 | 350 | 150 | - | Parent-Child | ✅ |
| `laws` | 2500 | 500 | 50 | 2500 | 按条款 | ❌ |
| `plans` | 2000 | 400 | 100 | - | Parent-Child | ✅ |
| `domain` | 1800 | 350 | 150 | - | Parent-Child | ✅ |
| `default` | 2500 | 500 | 100 | 2500 | 递归字符分割 | ❌ |

**Parent-Child 启用说明**：
- ✅ 启用：内容连贯性强，需要完整上下文理解（textbook、plans、domain、case、guide、report）
- ❌ 不启用：内容天然独立，子块本身已足够（policy、standard、laws）

### 正则分割模式

```python
SPLIT_PATTERNS_RE: Dict[str, List] = {
    "policy": [re.compile(r'\n(?=第\s*[一二三四五六七八九十百千万0-9]+\s*条)')],
    "case": [re.compile(r'\n(?=[一二三四五六七八九十]+[、.])'), re.compile(r'\n(?=\d+\.[^\d])')],
    "standard": [re.compile(r'\n(?=\d+\.\d+(?:\.\d+)?)'), re.compile(r'\n(?=第\s*\d+\s*条)')],
    "guide": [re.compile(r'\n(?=#{1,3}\s)')],
    "textbook": [re.compile(r'\n(?=#{1,3}\s)'), re.compile(r'\n(?=第[一二三四五六七八九十百]+章)')],
}
```

### Parent-Child 模式（Small-to-Big）

用于 `report` 类型文档，实现高精度检索 + 完整上下文返回：

```
Small-to-Big 架构:
  ┌─────────────────────────────┐
  │  Parent Chunk (~2000 chars) │  ← 返回给 LLM 的上下文
  │  ┌───────────────────────┐  │
  │  │  Child (~400 chars)   │  │  ← 用于向量检索匹配
  │  └───────────────────────┘  │
  └─────────────────────────────┘

检索流程:
  用户查询 → 匹配 Child (高精度) → 返回 Parent (完整上下文)
```

**关键参数**：

- 子块大小：400 字符（用于精确向量匹配）
- 父块大小：2000 字符（用于返回完整上下文）
- 子块重叠：100 字符

### LLM 智能切分（v5.0 新增）

针对正则切分效果差的文档，支持使用 LLM 进行语义边界检测和切片质量评分。

**配置项**：

```python
# backend/app/core/settings.py
LLM_CHUNK_ENABLED = False  # 是否启用 LLM 切分
LLM_CHUNK_THRESHOLD = 0.7  # 语义评分阈值
LLM_CHUNK_MAX_DOC_SIZE = 10000  # 启用 LLM 切分的文档大小阈值
```

**核心类**：

```python
# backend/app/services/modules/rag/chunker.py

class LLMBoundaryDetector:
    """LLM 辅助语义边界检测"""

    async def validate_boundary_async(self, left_context: str, right_context: str) -> dict:
        """校验边界是否合理，返回 {"should_split": bool, "reason": str}"""

    async def suggest_boundary_async(self, context: str) -> int:
        """建议新的边界位置，返回字符偏移量"""


class SemanticChunkScorer:
    """切片语义完整性评分"""

    async def score_chunk_async(self, chunk: str) -> dict:
        """评估 chunk 的语义完整性，返回 {"score": float, "issues": List[str]}"""


class EnhancedMarkdownSlicer(UnifiedMarkdownSlicer):
    """增强版切分器：支持 LLM 辅助"""

    async def slice_async(self, content: str, doc_type: str, ...) -> List[Chunk]:
        """异步切分（支持 LLM 辅助）"""
        # 1. 正则初切
        # 2. LLM 边界校验
        # 3. 语义评分
        # 4. 返回高质量 chunks
```

**流程图**：

```
文档入库
    │
    ├─ 1. 正则初切
    │     按文档类型使用对应正则模式
    │
    ├─ 2. LLM 边界校验（可选）
    │     validate_boundary_async()
    │     ├─ 合理 → 保留边界
    │     └─ 不合理 → 合并相邻 chunks
    │
    ├─ 3. 语义评分（可选）
    │     score_chunk_async()
    │     ├─ score >= threshold → 保留
    │     └─ score < threshold → 过滤
    │
    └─ 4. 入库
```

**成本分析**：

| 项目 | 数据 |
|------|------|
| 模型 | qwen-flash（阿里云） |
| 单文档成本 | ~0.008元（50,000字符） |
| 50个文档批量 | ~0.4元 |

### 切片质量检测

切片器内置质量检测逻辑，过滤低质量切片：

```python
def _is_quality_chunk(self, text: str) -> bool:
    # 最小长度检测
    if len(text.strip()) < 30:
        return False
    # 中文比例检测（至少 5%）
    if sum(1 for c in text if '一' <= c <= '鿿') / len(text) < 0.05:
        return False
    return True
```

### 文档预处理

切片前自动执行以下预处理：

1. **换行符标准化**：`\r\n` → `\n`
2. **多余空行压缩**：连续空行压缩为两个
3. **OCR 标记清理**：移除 `#[Page N]`、`*[Image OCR]` 等
4. **表格行过滤**：过滤 `|` 超过 3 个的行
5. **单字中文行过滤**：过滤单字中文行

---

## 知识库组成

### 知识库分类体系

```python
# backend/app/core/settings.py
KB_CATEGORIES = ["policies", "cases", "standards", "domain", "local", "laws", "plans"]
```

### 目录映射关系

| 目录名          | category      | doc_type     | 说明                     |
| --------------- | ------------- | ------------ | ------------------------ |
| `01 专业教材` | `domain`    | `textbook` | 规划专业教材             |
| `02 法律法规` | `laws`      | -            | 法律法规文件（含子分类） |
| `03 政策文件` | `policies`  | -            | 政策文件（含子分类）     |
| `04 技术规范` | `standards` | -            | 技术规范标准             |
| `05 上位规划` | `plans`     | `report`   | 上位规划文件             |
| `06 相关案例` | `cases`     | `case`     | 规划案例                 |

### 向量存储配置

```python
# backend/app/core/settings.py
CHROMA_COLLECTION_NAME = "village_planning"
CHROMA_PERSIST_DIR = "data/knowledge_base/chroma_db"
```

### 嵌入模型配置

系统支持嵌入模型：

| 属性     |  | 阿里云模式                        |
| -------- | - | --------------------------------- |
| 配置项   |  | `EMBEDDING_PROVIDER = "aliyun"` |
| 模型     |  | `text-embedding-v4`             |
| 向量维度 |  | 1024                              |
| 语言支持 |  | 多语言                            |
| 加载方式 |  | OpenAI 兼容 API                   |

```python
# backend/app/core/settings.py
EMBEDDING_PROVIDER = "local"  # 或 "aliyun"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DASHSCOPE_API_KEY = ""  # 阿里云模式需要
```

---

## 向量存储架构

### ParentChildVectorStore 设计

**文件路径**: `backend/app/services/modules/rag/vector_store.py`

```python
class ParentChildVectorStore:
    """
    Small-to-Big 检索架构

    流程：
    1. 添加文档时：切分为父块 → 父块再切分为子块 → 子块存向量，父块存缓存
    2. 检索时：检索子块 → 获取子块的 parent_id → 返回对应的父块内容
    """

    PARENT_CACHE_FILE = "parent_chunks_cache.json"
    MAX_PARENT_CACHE_SIZE = 1000  # LRU 淘汰上限
```

### 文档添加流程（v5.0 修复）

**文件路径**: `backend/app/services/modules/rag/service.py`

```python
def add_document(self, file_path: str, ...):
    # 1. 加载文档并切分为父块
    splits = SlicingStrategyFactory.slice_document(full_content, doc_type, ...)

    # 2. 创建 ParentChildChunk 列表（父块 → 子块）
    parent_child_chunks = self._create_parent_child_chunks(split_docs, ...)

    # 3. 使用 add_chunks() 添加（而非 add_documents()）
    self._vector_store.add_chunks(parent_child_chunks)

def _create_parent_child_chunks(self, parent_docs: List[Document], ...):
    """将父块切分为子块"""
    CHILD_SIZE = 400  # 子块大小
    CHILD_OVERLAP = 100  # 子块重叠

    for parent_doc in parent_docs:
        parent_content = parent_doc.page_content
        parent_id = f"{source_name}_{parent_idx}_{hash}"

        # 切分父块为子块
        child_splits = self.text_splitter.split_text(parent_content)

        for child_idx, child_content in enumerate(child_splits):
            chunk = ParentChildChunk(
                child_content=child_content,
                child_id=f"{parent_id}_child_{child_idx}",
                parent_content=parent_content,  # 完整父块内容
                parent_id=parent_id,
                child_index=child_idx,
                total_children=len(child_splits),
                metadata={...},
            )
            all_chunks.append(chunk)

    return all_chunks
```

### 检索流程

```
用户查询
    │
    ├─ 1. 向量相似度搜索（子块）
    │     ChromaDB.similarity_search(query, k=5)
    │
    ├─ 2. 获取 parent_id
    │     从子块 metadata 中提取
    │
    ├─ 3. 查询父块缓存
    │     _parent_cache[parent_id]
    │
    └─ 4. 返回父块内容
          完整上下文（~2000 chars）
```

### Fallback 机制

当父块缓存为空或子块缺少 `parent_id` 时，自动降级返回子块结果：

```python
def retrieve(self, query: str, k: int = 5, return_parents: bool = True) -> List[Dict]:
    child_results = self.child_store.similarity_search(query, k=k)

    # Fallback 1: _parent_cache 为空时直接返回子块结果
    if not self._parent_cache:
        logger.info("[ParentChildVectorStore] _parent_cache 为空，fallback 返回子块结果")
        return [{"content": doc.page_content, "metadata": doc.metadata, "score": 0} for doc in child_results]

    # ... 尝试获取父块 ...

    # Fallback 2: 所有 child doc 都缺少 parent_id 时，直接返回子块结果
    if not parent_results:
        logger.info("[ParentChildVectorStore] parent_id 缺失，fallback 返回子块结果")
        return [{"content": doc.page_content, "metadata": doc.metadata, "score": 0} for doc in child_results]
```

### 关键参数

| 参数         | 值         | 说明               |
| ------------ | ---------- | ------------------ |
| 子块大小     | 400 字符   | 用于精确向量匹配   |
| 子块重叠     | 100 字符   | 避免边界信息丢失   |
| 父块大小     | ~2000 字符 | 用于返回完整上下文 |
| 父块缓存上限 | 1000 条    | LRU 淘汰策略       |

### 父块缓存管理

- **存储位置**: `{CHROMA_PERSIST_DIR}/parent_chunks_cache.json`
- **缓存结构**: `OrderedDict[parent_id, parent_content]`
- **淘汰策略**: LRU（最近最少使用），最大 1000 条
- **持久化**: 每次添加文档后自动保存

---

## 检索 Query 生成

### 多查询动态生成（v5.0 新架构）

**文件路径**: `backend/app/services/modules/rag/service.py`

```python
async def generate_queries(
    self,
    cfg: Any,
    state: Dict[str, Any]
) -> List[str]:
    """
    使用 LLM-Flash 基于依赖信息动态生成多条 RAG 查询

    流程：
    1. 加载依赖维度摘要（depends_on + layer_depends_on + phase_depends_on）
    2. 使用 Flash LLM 生成 5-8 条中文查询
    3. 返回多条查询用于并行检索
    """
    # 加载依赖摘要（批量加载避免 N+1）
    depends_on = getattr(cfg, 'depends_on', [])
    layer_depends_on = getattr(cfg, 'layer_depends_on', [])
    phase_depends_on = getattr(cfg, 'phase_depends_on', [])

    all_deps = depends_on + layer_depends_on + phase_depends_on

    # 批量加载各层报告
    layer_reports = await store.get_layer_reports(session_id, 1)
    layer_reports_2 = await store.get_layer_reports(session_id, 2) if phase_depends_on else {}
    layer_reports_3 = await store.get_layer_reports(session_id, 3) if depends_on else {}

    # 组装依赖摘要
    dependency_summaries = []
    for dep_key in all_deps:
        summary = layer_reports.get(dep_key) or layer_reports_2.get(dep_key) or layer_reports_3.get(dep_key)
        if summary:
            dependency_summaries.append(f"【{dep_key}】{summary}")

    # 使用 Flash LLM 生成查询
    llm = create_flash_llm(max_tokens=200, temperature=0.3)
    prompt = f"""你是一个专业的规划信息检索助手。根据以下背景信息，为规划任务生成 5-8 条中文检索查询。

## 规划任务
- 维度：{dim_name}
- 描述：{task_desc}

## 背景信息
{chr(10).join(dependency_summaries)}

## 生成要求
生成 5-8 条中文查询，覆盖不同侧面（政策法规、技术标准、地方规划、相似案例），直接输出查询（每行一条），不要编号或解释。"""

    response = await llm.ainvoke(prompt)
    queries = [q.strip() for q in response.content.split("\n") if q.strip()]
    return queries[:8]
```

### 关键特点

| 特性        | 说明                                    |
| ----------- | --------------------------------------- |
| 模型        | Flash 模型（qwen-flash，低延迟）        |
| max_tokens  | 200（多条查询词）                       |
| temperature | 0.3（稳定输出）                         |
| 依赖传递    | 同层 + 跨层依赖摘要（完整内容，不截断） |
| 查询数量    | 5-8 条中文查询                          |
| 执行方式    | 并行检索（`asyncio.gather()`）        |
| Fallback    | `"{dim_name} 规划 技术标准"`          |

### 依赖摘要加载流程

```
维度分析开始
    │
    ├─ 1. 获取依赖配置
    │     depends_on (同层依赖)
    │     layer_depends_on (Layer 1 依赖)
    │     phase_depends_on (Layer 2 依赖)
    │
    ├─ 2. 批量加载各层报告（避免 N+1）
    │     get_layer_reports(session_id, 1)
    │     get_layer_reports(session_id, 2)
    │     get_layer_reports(session_id, 3)
    │
    ├─ 3. 组装依赖摘要
    │     【{dep_key}】{完整摘要内容}
    │
    └─ 4. Flash LLM 生成查询
          5-8 条中文查询
```

### 并行检索执行

**文件路径**: `backend/app/agent/nodes/analysis.py`

```python
# 生成多条查询
queries = await RagService.get_instance().generate_queries(cfg, state)

# 并行执行所有查询
search_tasks = [RagService.get_instance().search(query, top_k=2) for query in queries]
all_results_nested = await asyncio.gather(*search_tasks)
all_results = [r for results in all_results_nested for r in results]

# 去重并排序（按 score）
seen_content = set()
unique_results = []
for r in sorted(all_results, key=lambda x: x.get("score", 0), reverse=True):
    content_key = r.get("content", "")[:100]
    if content_key not in seen_content:
        seen_content.add(content_key)
        unique_results.append(r)

# 取 top-k
results = unique_results[:5]
```

---

## 分层检索机制

### 三级开关控制

**文件路径**: `backend/app/agent/nodes/analysis.py`

```python
# 三级开关: Layer > Session > Dimension
rag_layer_config = config.get("rag_layer_config", {})
layer_rag_enabled = rag_layer_config.get(dim_layer, True)  # Layer 级
global_rag_enabled = config.get("rag_enabled", True)        # Session 级
dim_rag_query = getattr(cfg, 'rag_query', '')               # Dimension 级

# 组合决策: Layer && Session && Dimension
rag_enabled = layer_rag_enabled and global_rag_enabled

if rag_enabled and dim_rag_query:
    # 执行多查询并行检索
    queries = await RagService.get_instance().generate_queries(cfg, state)
    search_tasks = [RagService.get_instance().search(query, top_k=2) for query in queries]
    all_results_nested = await asyncio.gather(*search_tasks)
    # 去重合并
    results = _deduplicate_and_merge(all_results_nested)[:5]
```

### 三级开关流程图

```
维度分析开始
    │
    ├─ 1. Layer 级开关（最高优先级）
    │     rag_layer_config.get(dim_layer, True)
    │     ├─ True  → 继续
    │     └─ False → 跳过 RAG
    │
    ├─ 2. Session 级开关
    │     config.get("rag_enabled", True)
    │     ├─ True  → 继续
    │     └─ False → 跳过 RAG
    │
    ├─ 3. Dimension 级开关
    │     cfg.rag_query
    │     ├─ 非空 → 执行 RAG 检索
    │     └─ 空字符串 → 跳过 RAG
    │
    ├─ 4. 多查询生成
    │     generate_queries(cfg, state)
    │     └─ Flash LLM 生成 5-8 条中文查询
    │
    ├─ 5. 并行检索执行
    │     asyncio.gather(*search_tasks)
    │     └ 每条查询 top_k=2
    │
    └─ 6. 去重合并取 top-5
          组装 Prompt（传入 rag_context）
```

### 组合逻辑矩阵

| Layer 级  | Session 级 | Dimension 级 | 结果                    |
| --------- | ---------- | ------------ | ----------------------- |
| `true`  | `true`   | 非空字符串   | ✅ 执行 RAG 检索        |
| `true`  | `true`   | `""`       | ❌ 跳过（维度级关闭）   |
| `true`  | `false`  | 任意值       | ❌ 跳过（会话级关闭）   |
| `false` | 任意值     | 任意值       | ❌ 跳过（Layer 级关闭） |

### RAG 禁用维度清单

#### Layer 2（规划思路）— 全部 4 维度关闭

| 维度 Key                 | 维度名称     | rag_query | 关闭原因                                |
| ------------------------ | ------------ | --------- | --------------------------------------- |
| `resource_endowment`   | 资源禀赋分析 | `""`    | 依赖内部知识+前序报告，无需技术标准检索 |
| `planning_positioning` | 规划定位分析 | `""`    | 同上                                    |
| `development_goals`    | 发展目标分析 | `""`    | 同上                                    |
| `planning_strategies`  | 规划策略分析 | `""`    | 同上                                    |

**关闭理由**：Layer 2（规划思路层）本质是对 Layer 1 分析结果的综合提炼，输出规划理念和方向性判断。其知识来源主要是：

- Layer 1 各维度的分析报告（通过 `reports` 状态传递）
- LLM 自身的规划领域知识

外部知识检索对此类归纳性任务不仅收益有限，反而可能引入不相关的技术标准，干扰规划理念的生成。

#### Layer 3 — `project_bank` 关闭

| 维度 Key         | 维度名称   | rag_query | 关闭原因                         |
| ---------------- | ---------- | --------- | -------------------------------- |
| `project_bank` | 建设项目库 | `""`    | 建设项目目录性质，不需要知识检索 |

**关闭理由**：建设项目库本质是对 Layer 3 其他维度规划产出（产业规划、土地利用规划、道路交通规划等）的项目化汇总和投资估算，属于"目录整理"型任务，不涉及新的技术标准引用。

### 检索上下文模式

| context_mode | 说明                | Token 消耗   |
| ------------ | ------------------- | ------------ |
| `minimal`  | 仅匹配片段          | 最少         |
| `standard` | 片段 + 300 字上下文 | 中等（默认） |
| `expanded` | 片段 + 500 字上下文 | 最大         |

---

## 维度摘要生成

### 智能摘要策略

**文件路径**: `backend/app/services/report_store.py`

维度摘要用于 RAG 查询生成的上下文传递，采用智能策略：

```python
async def _generate_summary(self, content: str) -> str:
    """生成摘要 - 智能策略：短文直接返回，长文用 LLM 生成"""
    if not content:
        return ""

    # 简单清理
    cleaned = " ".join(content.split())

    # 短报告（< 1000 字）直接返回
    if len(cleaned) <= 1000:
        return cleaned

    # 长报告使用 LLM-Flash 生成摘要
    from app.core.llm import create_flash_llm

    llm = create_flash_llm(max_tokens=300, temperature=0.3)

    prompt = f"""请用300字以内概括以下规划分析报告的核心内容，包括：
1. 主要发现
2. 关键结论
3. 核心建议（如有）

报告内容：
{cleaned[:3000]}"""

    try:
        result = await llm.ainvoke(prompt)
        return result.content.strip()
    except Exception as e:
        logger.warning(f"摘要生成失败，使用截断: {e}")
        return cleaned[:500]
```

### 策略说明

| 报告长度   | 处理方式       | 说明                     |
| ---------- | -------------- | ------------------------ |
| < 1000 字  | 直接返回       | 简单清洗，保留完整内容   |
| >= 1000 字 | LLM-Flash 生成 | 300 字摘要，提取核心内容 |
| 生成失败   | 截断前 500 字  | 降级策略                 |

### 摘要使用场景

1. **RAG 查询生成**：作为依赖上下文传递给 Flash LLM
2. **消息队列**：用于前端展示维度摘要
3. **版本历史**：存储在 `DimensionReport.summary` 字段

---

## 元数据注入

### 注入字段说明

**文件路径**: `backend/app/services/modules/rag/injector.py`

| 字段               | 类型   | 说明                 | 来源                |
| ------------------ | ------ | -------------------- | ------------------- |
| `dimension_tags` | string | 维度标签（逗号分隔） | 关键词匹配/语义标注 |
| `terrain`        | string | 地形类型             | 文档内容/文件名     |
| `document_type`  | string | 文档类型             | 内容分析            |
| `regions`        | string | 地区名称（逗号分隔） | 内容提取            |
| `category`       | string | 知识库分类           | 参数传入            |
| `chunk_index`    | int    | 切片序号             | 自动生成            |
| `total_chunks`   | int    | 总切片数             | 自动生成            |
| `source`         | string | 文档来源             | 文件名              |
| `file_hash`      | string | 文件 MD5             | 自动计算            |

### 两种标注模式

#### 1. 关键词匹配（快速）

```python
# backend/app/config/document_types.py
class DimensionTagger:
    """维度标签关键词匹配"""

    DIMENSION_KEYWORDS = {
        "location": ["区位", "交通", "对外联系", "可达性"],
        "socio_economic": ["人口", "经济", "产业", "收入"],
        "land_use": ["土地利用", "用地", "耕地", "建设用地"],
        # ...
    }

    def detect_dimensions(self, content: str) -> List[str]:
        """从内容中检测相关维度"""
        detected = []
        for dim, keywords in self.DIMENSION_KEYWORDS.items():
            if any(kw in content for kw in keywords):
                detected.append(dim)
        return detected if detected else ["general"]
```

#### 2. 语义标注（精准）

```python
# backend/app/services/modules/rag/tagger.py
class SemanticDimensionTagger:
    """使用 LLM 进行语义维度标注"""

    async def tag_chunk_async(self, content: str) -> List[str]:
        """使用 Flash 模型进行语义维度标注"""
        prompt = f"""分析以下规划文档片段，判断其最相关的分析维度。

文档内容：
{content[:500]}

可选维度：区位分析、社会经济、土地利用、道路交通、公共服务、基础设施、生态绿地、建筑分析、历史文化

请返回最相关的 1-3 个维度，用逗号分隔："""

        llm = create_flash_llm(temperature=0.1, max_tokens=50)
        response = await llm.ainvoke(prompt)
        return self._parse_response(response.content)
```

### 批量注入流程

```python
# backend/app/services/modules/rag/injector.py
class MetadataInjector:
    def inject_batch(
        self,
        documents: List[Document],
        category: Optional[str] = None,
        doc_type: Optional[str] = None,
        dimension_tags: Optional[list] = None,
        terrain: Optional[str] = None,
    ) -> List[Document]:
        """批量注入元数据"""
        full_content = "\n\n".join(doc.page_content for doc in documents)
        total = len(documents)

        for idx, doc in enumerate(documents):
            params = InjectionParams(
                doc=doc,
                full_content=full_content,
                idx=idx,
                total=total,
                category=category,
                manual_doc_type=doc_type,
                manual_dimension_tags=dimension_tags,
                manual_terrain=terrain,
            )
            self.inject(params)

        return documents
```

---

## 知识检索工具集

以下工具注册到 `ToolRegistry`，供 LangChain Agent 通过 function calling 调用：

**文件路径**: `backend/app/tools/analytics/knowledge_search.py`

| 工具名                         | 函数                             | 功能                        |
| ------------------------------ | -------------------------------- | --------------------------- |
| `knowledge_search`           | `search_knowledge()`           | 向量检索，支持 context_mode |
| `list_documents`             | `list_available_documents()`   | 列出知识库所有文档          |
| `document_overview`          | `get_document_overview()`      | 文档执行摘要 + 章节列表     |
| `chapter_content`            | `get_chapter_content()`        | 章节内容（三级详情）        |
| `key_points_search`          | `search_key_points()`          | 关键要点搜索                |
| `full_document`              | `get_full_document()`          | 完整文档内容                |
| `check_technical_indicators` | `check_technical_indicators()` | 技术指标/规范标准检索       |

### 元数据过滤

```python
def _build_metadata_filter(params: MetadataFilterParams) -> Optional[Dict]:
    """构建 ChromaDB 过滤器"""
    filter_dict = {}

    if params.terrain and params.terrain != "all":
        filter_dict["terrain"] = params.terrain

    if params.doc_type:
        filter_dict["doc_type"] = params.doc_type

    if params.task_id:
        filter_dict["task_id"] = params.task_id  # 会话隔离

    return filter_dict if filter_dict else None
```

---

## 关键文件路径

| 功能                   | 文件路径                                                    |
| ---------------------- | ----------------------------------------------------------- |
| 统一切片器             | `backend/app/services/modules/rag/chunker.py`             |
| LLM 边界检测器         | `backend/app/services/modules/rag/chunker.py`             |
| 语义评分器             | `backend/app/services/modules/rag/chunker.py`             |
| 文本切片策略工厂       | `backend/app/services/modules/rag/utils/text_splitter.py` |
| 向量存储               | `backend/app/services/modules/rag/vector_store.py`        |
| RAG 服务（多查询生成） | `backend/app/services/modules/rag/service.py`             |
| 文档上下文管理器       | `backend/app/services/modules/rag/context.py`             |
| 元数据注入器           | `backend/app/services/modules/rag/injector.py`            |
| 语义维度标注器         | `backend/app/services/modules/rag/tagger.py`              |
| 知识检索工具集         | `backend/app/tools/analytics/knowledge_search.py`         |
| 分析节点（并行检索）   | `backend/app/agent/nodes/analysis.py`                     |
| 路由逻辑（依赖检查）   | `backend/app/agent/routing.py`                            |
| 报告存储（智能摘要）   | `backend/app/services/report_store.py`                    |
| 维度 RAG 配置          | `backend/app/config/phases.yaml`                          |
| 系统配置               | `backend/app/core/settings.py`                            |
| 知识库构建脚本         | `scripts/build_knowledge_base.py`                         |

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - analyze_dimension 节点设计
- [03-layer-dimension](./03-layer-dimension.md) - 维度 RAG 配置
- [06-tool-system](./06-tool-system.md) - ToolRegistry 工具注册
