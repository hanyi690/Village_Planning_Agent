# RAG 系统架构文档

## 概述

Village Planning Agent 的 RAG（Retrieval-Augmented Generation）系统为规划代理提供专业知识检索能力，支持法规标准引用、技术指标查询、案例参考等功能。

## 核心架构

### Small-to-Big 检索架构

系统采用 **Small-to-Big** 架构进行检索：

```
查询 → 检索子块（400字符）→ 获取 parent_id → 返回父块完整内容（2000字符）
```

**优势**：
- 子块用于精确匹配，提高检索精度
- 父块用于返回上下文，提供完整信息

### 文档处理流程

```
文档上传 → 解析（MarkItDown/Docling）→ 切片 → 元数据注入 → 向量化 → 存储
```

---

## Parent-Child 模式决策

### 各文档类型的切分策略

| 文档类型 | Parent-Child | 切分策略 | 原因 |
|----------|-------------|----------|------|
| `policy` | 关闭 | 按条文切分（第X条） | 法律条文有明确边界，无需 Parent-Child |
| `laws` | 关闭 | 按条文切分（第X条） | 同 policy |
| `standard` | 关闭 | 按章节号切分（X.X.X） | 技术标准有层级结构 |
| `case` | 启用 | Parent-Child | 规划案例内容连续，需要上下文 |
| `guide` | 启用 | Parent-Child | 指南内容需要完整上下文理解 |
| `report` | 启用 | Parent-Child | 报告内容需要完整上下文 |
| `textbook` | 启用 | Parent-Child | 教材内容需要完整上下文理解 |
| `plans` | 启用 | Parent-Child | 规划方案需要完整上下文 |
| `domain` | 启用 | Parent-Child | 领域知识需要完整上下文 |

### 切分参数配置

| 参数 | Policy/Standard | Case/Guide/Report |
|------|-----------------|-------------------|
| `chunk_size` | 1500-2500 | 1800-2000 |
| `overlap` | 300-500 | 350-400 |
| `min_chunk` | 100 | 100-200 |
| `parent_size` | - | 1800-2000 |
| `child_size` | - | 400 |

---

## 解析器选择策略

| 场景 | 推荐解析器 | 原因 |
|------|-----------|------|
| PDF 含表格 | Docling | 保留表格结构 |
| PDF 无表格 | MarkItDown | 速度快 |
| 扫描件 | Docling + RapidOCR | OCR 支持 |
| 大文档（>100页）| MarkItDown | 避免内存问题 |

---

## 工具注册机制

系统统一使用 `ToolRegistry.register()` 注册工具：

```python
@ToolRegistry.register("knowledge_search")
def knowledge_search_registry_wrapper(context: Dict[str, Any]) -> str:
    """检索知识库"""
    return search_knowledge(...)
```

**已注册工具**：
- `list_documents` - 列出知识库文档
- `document_overview` - 获取文档概览
- `chapter_content` - 获取章节内容
- `knowledge_search` - 检索知识库
- `key_points_search` - 搜索关键要点
- `full_document` - 获取完整文档
- `check_technical_indicators` - 检索技术指标

---

## 增量更新机制

系统支持基于文件哈希的增量更新：

```python
def _should_update_document(self, source_name: str, new_hash: str) -> bool:
    """检查文档是否需要更新"""
    # 新文档 → 需要添加
    # 无哈希记录 → 需要更新
    # 哈希变化 → 需要更新
    # 哈希相同 → 跳过
```

**更新流程**：
1. 计算文件 MD5 哈希
2. 与存储的哈希对比
3. 若相同则跳过，若不同则删除旧版本并重新索引

---

## 查询缓存机制

为减少 LLM 调用成本，系统实现查询缓存：

```python
# 缓存键：维度 + 依赖列表哈希
cache_key = hashlib.md5(f"{dim_key}:{deps_str}".encode()).hexdigest()

# 缓存 TTL：1 小时
_query_cache_ttl: int = 3600
```

---

## RAG 在规划流程中的应用

### Layer 1（现状分析）

全部 12 维度启用 RAG：
- `location` - 区位与对外交通分析
- `socio_economic` - 社会经济分析
- `villager_wishes` - 村民意愿与诉求分析
- `superior_planning` - 上位规划与政策导向分析
- `natural_environment` - 自然环境分析
- `land_use` - 土地利用分析
- `traffic` - 道路交通分析
- `public_services` - 公共服务设施分析
- `infrastructure` - 基础设施分析
- `ecological_green` - 生态绿地分析
- `architecture` - 建筑分析
- `historical_culture` - 历史文化与乡愁保护分析

### Layer 2（规划思路）

全部 4 维度关闭 RAG：
- `resource_endowment` - 资源禀赋分析
- `planning_positioning` - 规划定位分析
- `development_goals` - 发展目标分析
- `planning_strategies` - 规划策略分析

**关闭原因**：依赖内部知识 + 前序报告，无需外部检索

### Layer 3（详细规划）

11 维度启用，1 维度关闭：
- `industry` - 产业规划
- `spatial_structure` - 空间结构规划
- `land_use_planning` - 土地利用规划
- `settlement_planning` - 居民点规划
- `traffic_planning` - 道路交通规划
- `public_service` - 公共服务设施规划
- `infrastructure_planning` - 基础设施规划
- `ecological` - 生态绿地规划
- `disaster_prevention` - 防震减灾规划
- `heritage` - 历史文保规划
- `landscape` - 村庄风貌指引
- `project_bank` - 建设项目库（关闭）

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| RAG 服务 | `backend/app/services/modules/rag/service.py` |
| 向量存储 | `backend/app/services/modules/rag/vector_store.py` |
| 切片器 | `backend/app/services/modules/rag/chunker.py` |
| 元数据注入 | `backend/app/services/modules/rag/injector.py` |
| 知识检索工具 | `backend/app/tools/analytics/knowledge_search.py` |
| 文档加载器 | `backend/app/utils/document_loader.py` |
| 维度配置 | `backend/app/config/phases.yaml` |
