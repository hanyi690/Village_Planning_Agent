# RAG 知识库架构

本文档详细说明 RAG 知识检索系统的架构设计及在维度执行中的使用方式。

> **更新日期**: 2026-05-10
> **版本**: v3.1

## 目录

- [知识检索的两种路径](#知识检索的两种路径)
- [维度执行中的检索流程](#维度执行中的检索流程)
- [RAG 开关机制](#rag-开关机制)
- [RAG 禁用维度清单](#rag-禁用维度清单)
- [RagService 核心 API](#ragservice-核心-api)
- [向量存储](#向量存储)
- [知识库管理](#知识库管理)
- [知识检索工具集](#知识检索工具集)
- [关键文件路径](#关键文件路径)

---

## 知识检索的两种路径

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

## 维度执行中的检索流程

### 自动注入路径（RagService.get_context）

每个维度分析都会自动触发知识检索，无需 Agent 显式调用工具。检索受**两级开关**控制：

```python
# backend/app/agent/nodes/analysis.py → analyze_dimension()
# 步骤 3: RAG 查询（两级开关：会话级 rag_enabled + 维度级 rag_query）
rag_context = ""
rag_enabled = state.get("config", {}).get("rag_enabled", True)
dim_rag_query = getattr(cfg, 'rag_query', '')
if rag_enabled and dim_rag_query:
    rag_context = await RagService.get_instance().get_context(dim_key, state, cfg)
else:
    reason = "会话级 RAG 已关闭" if not rag_enabled else f"维度 rag_query 为空"
    logger.info(f"[analyze_dimension] {dim_key}: 跳过 RAG（{reason}）")
```

### 检索三步流程

```
步骤 1: LLM 生成查询词
输入: 维度名称 + 分析阶段 + prompt_hint + 前序摘要
输出: ≤20 词的英文搜索查询

步骤 2: 向量相似度搜索
引擎: ChromaDB
模型: BAAI/bge-small-zh-v1.5 (384维)
策略: ParentChildVectorStore (Small-to-Big)
参数: top_k=3

步骤 3: 格式化注入
每个结果截断为 500 字符
格式: 【参考N - 文档类型】\n来源: xxx\n内容:\nxxx
最终注入 LLM Prompt 的知识参考部分
```

### 两级开关流程图

```
维度分析开始
    │
    ├─ 1. 获取会话级 rag_enabled 配置
    │     （来自 API 请求参数，默认 True）
    │
    ├─ 2. 获取维度级 rag_query 配置
    │     （来自 phases.yaml，不同维度独立配置）
    │
    ├─ 3. 组合决策
    │     rag_enabled && rag_query ?
    │     ├─ True  → 执行 RAG 检索（generate_query → search → format）
    │     └─ False → 跳过 RAG，rag_context = ""
    │
    └─ 4. 组装 Prompt（无论是否检索，均传入 rag_context）
```

### 组合逻辑矩阵

| 会话级 `rag_enabled` | 维度级 `rag_query` | 结果 |
|---------------------|-------------------|------|
| `true` | 非空字符串 | ✅ 执行 RAG 检索 |
| `true` | `""` | ❌ 跳过（维度级关闭） |
| `false` | 任意值 | ❌ 跳过（会话级关闭） |

这种设计支持：
- **实验对比**：通过 API 参数整体开关 RAG，对比有无知识注入的效果差异
- **精细控制**：对特定维度（如规划思路类维度）在 YAML 中设置 `rag_query: ""` 单独关闭

### LLM 查询生成

```python
# backend/app/services/modules/rag/service.py → generate_query()
query_prompt = f"""Based on the dimension analysis requirements,
generate a concise search query (max 20 words) to find relevant
regulations and technical standards.

Dimension: {dim_name}
Phase: {phase}
Analysis Focus: {prompt_hint}
Previous Context:
{前序维度摘要或"None (first dimension in layer)"}

Generate only the search query, no explanation:"""

llm = create_llm(model="flash", temperature=0.3, max_tokens=50)
query = await llm.ainvoke(query_prompt)
```

关键特点：
- 使用轻量 `flash` 模型（低延迟）
- 固定 `max_tokens=50`（仅需查询词）
- 传入前序维度摘要，使查询具备上下文连贯性
- 失败时 fallback 为 `"{dim_name} 规划 技术标准"`

---

## RAG 开关机制

### 会话级开关

RAG 开关作为 API 请求参数传入，默认开启。

**API 参数定义**（`session_routes.py:121`）：
```python
rag_enabled: bool = Form(True, description="启用 RAG 知识检索（实验对比用）"),
```

**数据流**：
```
API 请求 → session_routes.create_session()
       → runtime.PlanningRuntimeService.start_session(rag_enabled=...)
       → state["config"]["rag_enabled"]  (存入会话状态)
       → analyze_dimension() 从 state 中读取使用
```

### 维度级开关

每个维度通过 `phases.yaml` 中的 `rag_query` 字段独立控制检索行为：

```yaml
# phases.yaml 示例
- key: location
  rag_query: "区位 交通"    # 非空 → 启用 RAG（LLM 生成查询词后检索）

- key: land_use_planning
  rag_query: "土地利用规划"   # 非空 → 启用 RAG

- key: planning_strategies
  rag_query: ""              # 空字符串 → 跳过 RAG
```

### 组合判定逻辑

```python
# analysis.py:108-120
rag_enabled = state.get("config", {}).get("rag_enabled", True)
dim_rag_query = getattr(cfg, 'rag_query', '')
if rag_enabled and dim_rag_query:
    rag_context = await RagService.get_instance().get_context(dim_key, state, cfg)
```

两个条件**必须同时满足**才执行 RAG 检索，任一为假则跳过。

---

## RAG 禁用维度清单

以下维度配置了 `rag_query: ""`，在 RAG ON 模式下也会跳过检索：

### Layer 2（规划思路）— 全部 4 维度关闭

| 维度 Key | 维度名称 | rag_query | 关闭原因 |
|----------|---------|-----------|---------|
| `resource_endowment` | 资源禀赋分析 | `""` | 依赖内部知识+前序报告，无需技术标准检索 |
| `planning_positioning` | 规划定位分析 | `""` | 同上 |
| `development_goals` | 发展目标分析 | `""` | 同上 |
| `planning_strategies` | 规划策略分析 | `""` | 同上 |

**关闭理由**：Layer 2（规划思路层）本质是对 Layer 1 分析结果的综合提炼，输出规划理念和方向性判断。其知识来源主要是：
- Layer 1 各维度的分析报告（通过 `reports` 状态传递）
- LLM 自身的规划领域知识

外部知识检索对此类归纳性任务不仅收益有限，反而可能引入不相关的技术标准，干扰规划理念的生成。

### Layer 3 — `project_bank` 关闭

| 维度 Key | 维度名称 | rag_query | 关闭原因 |
|----------|---------|-----------|---------|
| `project_bank` | 建设项目库 | `""` | 建设项目目录性质，不需要知识检索 |

**关闭理由**：建设项目库本质是对 Layer 3 其他维度规划产出（产业规划、土地利用规划、道路交通规划等）的项目化汇总和投资估算，属于"目录整理"型任务，不涉及新的技术标准引用。

### 实验依据

上述开关配置源于 `docs/manual_analysis_report.md` 的实验结论：
- RAG 知识注入对**上位规划引用**有明显提升（RAG ON 正确引用上位规划名称，RAG OFF 仅泛泛提及）
- 但对规划思路类维度，知识注入在成本（Token 消耗、延迟）和收益（引用准确性）上性价比低
- 建设项目库作为汇总维度，无需独立知识检索

---

## RagService 核心 API

```python
# backend/app/services/modules/rag/service.py
class RagService:
    """动态 RAG 检索与知识库管理服务（单例）"""

    # ── 检索 API ──

    async def generate_query(cfg, state) -> str:
        """LLM 生成优化后的搜索查询词"""

    async def search(query: str, top_k: int = 3) -> List[Dict]:
        """向量相似度搜索，返回 {content, metadata, score}"""

    async def get_context(dim_key, state, cfg=None) -> str:
        """完整检索流程: generate_query → search → format"""

    @staticmethod
    def format_for_prompt(results) -> str:
        """格式化搜索结果用于 Prompt 注入"""

    # ── 知识库管理 API ──

    def add_document(file_path, category, doc_type, ...) -> Dict:
        """增量添加文档: 加载→切片→元数据注入→向量化"""

    def delete_document(source_name: str) -> Dict:
        """删除文档及关联向量"""

    def list_documents() -> List[Dict]:
        """列出知识库中所有文档"""

    def get_stats() -> Dict:
        """知识库统计信息"""

    @property
    def vectorstore:
        """获取向量存储实例（供 knowledge_search 工具使用）"""
```

---

## 向量存储

### ChromaDB 配置

```python
# backend/app/core/settings.py
CHROMA_COLLECTION_NAME = "village_planning"
CHROMA_PERSIST_DIR = "data/chroma_db"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
```

### ParentChildVectorStore (Small-to-Big)

```
Small-to-Big 架构:
  ┌─────────────────────────────┐
  │  Parent Chunk (~500 chars)  │  ← 返回给 LLM 的上下文
  │  ┌───────────────────────┐  │
  │  │  Child (~100 chars)   │  │  ← 用于向量检索匹配
  │  └───────────────────────┘  │
  └─────────────────────────────┘

检索流程:
  用户查询 → 匹配 Child (高精度) → 返回 Parent (完整上下文)
```

### DocumentContextManager

```python
# backend/app/services/modules/rag/context.py
class DocumentContextManager:
    """文档全文上下文管理器"""

    def get_context_around_chunk(source, start_index, context_chars=500):
        """获取切片前后的完整上下文字段"""

    def get_full_document(source) -> dict:
        """获取完整文档内容（含元数据、切片数）"""

    def get_chapter_by_header(source, header_pattern) -> dict:
        """按标题关键词匹配章节内容"""

    def get_executive_summary(source) -> dict:
        """获取文档执行摘要（200 字）"""

    def list_chapter_summaries(source) -> dict:
        """列出所有章节标题与摘要"""

    def search_key_points(query, sources=None) -> dict:
        """在预先提取的关键要点中搜索"""
```

### 嵌入模型

| 属性 | 值 |
|------|-----|
| 模型名称 | `BAAI/bge-small-zh-v1.5` |
| 向量维度 | 384 |
| 语言支持 | 中文 |
| 加载方式 | sentence-transformers (离线缓存) |

---

## 知识库管理

### 文档添加流程

```
add_document(file_path)
  │
  ├─ 1. FileTypeDetector.detect() → 识别文件类型 (.pdf/.docx/.txt 等)
  ├─ 2. _create_loader() → 加载文档内容
  ├─ 3. _infer_doc_type() → 推断文档类型
  │     textbook / guide / policy / standard / case / report
  ├─ 4. SlicingStrategyFactory.slice_document() → 按类型策略切片
  ├─ 5. MetadataInjector.inject_batch() → 注入维度标签/地形标签
  ├─ 6. vectorstore.add_documents() → 向量化存储
  └─ 7. _update_document_index() → 更新 document_index.json
```

### 文档类型推断规则

| 文档类型 | 关键词匹配 |
|----------|-----------|
| `textbook` | 教材、原理、教程、导论、基础 + 章节检测 (第X章) |
| `guide` | 指南、手册、指导、操作、规程 |
| `policy` | 条例、规定、办法、通知、意见、决定、批复 |
| `standard` | 标准、规范、GB、CJJ、CJ、HG、JC、JG、JT |
| `case` | 规划、设计、方案、案例、实例、工程 |
| `report` | 默认 fallback |

---

## 知识检索工具集

以下工具注册到 `ToolRegistry`，供 LangChain Agent 通过 function calling 调用：

| 工具名 | 函数 | 功能 |
|--------|------|------|
| `knowledge_search` | `search_knowledge()` | 向量检索，支持 context_mode (minimal/standard/expanded) |
| `list_documents` | `list_available_documents()` | 列出知识库所有文档及基本信息 |
| `document_overview` | `get_document_overview()` | 文档执行摘要 + 章节列表 |
| `chapter_content` | `get_chapter_content()` | 章节内容 (summary/medium/full 三级) |
| `key_points_search` | `search_key_points()` | 在预提取关键要点中搜索 |
| `full_document` | `get_full_document()` | 获取完整文档内容 |
| `check_technical_indicators` | `check_technical_indicators()` | 技术指标/规范标准检索 |

### 检索上下文模式

| contex_mode | 说明 | Token 消耗 |
|-------------|------|-----------|
| `minimal` | 仅匹配片段 | 最少 |
| `standard` | 片段 + 300 字上下文 | 中等（默认） |
| `expanded` | 片段 + 500 字上下文 | 最大 |

### 元数据过滤

支持按 `terrain`（地形）、`doc_type`（文档类型）、`task_id`（会话隔离）过滤，
使用 ChromaDB `where` 子句实现。

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| RAG 服务（检索+管理） | `backend/app/services/modules/rag/service.py` |
| 文档上下文管理器 | `backend/app/services/modules/rag/context.py` |
| 向量存储（ParentChild） | `backend/app/services/modules/rag/vector_store.py` |
| 元数据注入器 | `backend/app/services/modules/rag/injector.py` |
| 维度标签器 | `backend/app/services/modules/rag/tagger.py` |
| 知识检索工具集 | `backend/app/tools/analytics/knowledge_search.py` |
| 分析节点（调用检索） | `backend/app/agent/nodes/analysis.py` |
| RAG 配置（维度级开关） | `backend/app/config/phases.yaml` |

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - analyze_dimension 节点设计
- [03-layer-dimension](./03-layer-dimension.md) - 维度 RAG 配置
- [06-tool-system](./06-tool-system.md) - ToolRegistry 工具注册
