# RAG 差异化切分与检索策略探索

> **更新日期**: 2026-07-21
> **版本**: v1.0 (探索文档)
> **关联文档**: `docs/architecture/08-rag-system.md` v8.0

## 一、问题诊断

### 1.1 核心问题

当前 RAG 系统存在两个关键缺陷：

| # | 问题                           | 现状                                                                                          | 影响                                                 |
| - | ------------------------------ | --------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 1 | **文档类型无差异化切分** | 法律法规、技术规范、案例全部使用同一`HierarchySlicer`（chunk_size=2500, chunk_overlap=500） | 法律条文被截断、技术标准上下文丢失、案例叙事不完整   |
| 2 | **维度无差异化检索策略** | 23 个维度（除 Layer 2 禁用 RAG）共享同一检索管线，仅`prefer_doc_types` 做粗粒度过滤         | 法律文档从未被命中、技术标准检索精度低、案例参考不足 |

### 1.2 问题 1 详解：统一切分的代价

当前 `HierarchySlicer._slice_with_langchain()` 对所有文档使用完全相同的策略：

```python
# chunker.py:386 — 所有文档类型共用
splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "Header1"), ("##", "Header2"),
                         ("###", "Header3"), ("####", "Header4")],
    strip_headers=False,
)
```

**不同文档类型的结构特征差异**：

| 文档类型                     | 典型结构                               | 切分需求                       | 当前问题                                  |
| ---------------------------- | -------------------------------------- | ------------------------------ | ----------------------------------------- |
| **法律法规** (12 部)   | 章→节→条→款，严格编号（第X条第Y款） | 条款不可拆分，需保留完整法条   | 条款被截断，"第18条第3款"可能只保留前半段 |
| **技术规范** (GB/T 等) | 章→节→条→项，含大量表格和公式       | 表格需完整保留，公式需上下文   | 表格跨 chunk 被拆散，指标表上下文丢失     |
| **政策文件**           | 通知+正文+附件，段落式                 | 段落级切分，保留政策上下文     | 政策条款与适用范围分离                    |
| **案例**               | 叙事式，无严格编号                     | 语义完整段落，保留案例全貌     | 案例背景与措施分离                        |
| **上位规划**           | 总体规划文本，层级深                   | 需保留层级上下文（省→市→县） | 层级关系在切分中丢失                      |

**具体案例**：

```
《土地管理法》第37条：
  "非农业建设必须节约使用土地，可以利用荒地的，不得占用耕地；
   可以利用劣地的，不得占用好地。"

当前切分结果（chunk_size=2500）：
  Chunk A: "...第37条 非农业建设必须节约使用土地，可以利用荒地的，不得占用耕地；"
  Chunk B: "可以利用劣地的，不得占用好地。第38条..."

→ 法条被截断，语义不完整，检索命中 Chunk A 时缺少关键约束
```

### 1.3 问题 2 详解：统一检索的代价

当前检索管线的差异化仅体现在：

1. **`prefer_doc_types` 过滤**（ChromaDB metadata filter）— 粗粒度，仅 6 种类型
2. **L1/L3 Prompt 差异**（查询生成侧重不同）— 仅影响查询词，不影响检索策略
3. **Layer 2 禁用 RAG**（`rag_query=""`）— 全有或全无

**缺失的差异化维度**：

| 差异化维度 | 当前状态     | 应有状态                                                 |
| ---------- | ------------ | -------------------------------------------------------- |
| 检索模式   | 纯向量搜索   | 向量 + BM25 混合（法律需精确匹配）                       |
| Top-K      | 固定 3-5     | 按维度动态调整（法规 2-3，案例 5-8）                     |
| Reranking  | 无           | 按维度配置（法规需法条完整性，案例需相关性）             |
| 查询扩展   | 固定同义词   | 按维度类型扩展（法规→法条编号，案例→项目类型）         |
| 分数阈值   | 固定 1.5     | 按文档类型调整（法规精确匹配阈值低，案例语义匹配阈值高） |
| 上下文窗口 | 固定合并策略 | 按维度需求调整（法规需完整法条，案例需摘要）             |

**法律法规从未被命中的根因**（08-rag-system.md §8.3 已记录）：

```
1. generate_queries() 的 LLM Prompt 侧重技术指标
   → 生成查询如"人均建设用地指标"，而非"土地管理法 建设用地审批"
2. ChromaDB 语义搜索偏向技术内容（15K chunks 中技术规范占多数）
   → 法律条文的语义距离通常大于技术标准
3. prefer_doc_types=[policy] 仅做过滤，不改变排序
   → 即使过滤到法规类，排序仍按语义相似度
4. 法律法规的 chunk 被截断，语义不完整
   → 即使命中，返回内容也不完整
```

---

## 二、行业对标与学术参考

### 2.1 文档类型差异化切分

| 方案                                       | 来源              | 核心思路                                                     | 适用性          |
| ------------------------------------------ | ----------------- | ------------------------------------------------------------ | --------------- |
| **Legal Chunking**                   | LawGPT / ChatLaw  | 法律条文按"条"为最小单位，条内不可拆分；跨条引用时附加上下文 | ⭐⭐⭐ 法律法规 |
| **Header-Aware + Parent-Child**      | LlamaIndex RAG    | 技术文档按标题层级切分，子 chunk 携带父 chunk 摘要           | ⭐⭐⭐ 技术规范 |
| **Summary-Augmented Chunking (SAC)** | RAPTOR / GraphRAG | 每个 chunk 前置文档级/章节级摘要，增强语义完整性             | ⭐⭐⭐ 所有类型 |
| **Semantic Chunking**                | LumberChunker     | 基于语义边界检测切分点，而非固定字符数                       | ⭐⭐ 案例类     |
| **Sliding Window + Overlap**         | 通用方案          | 按固定窗口+重叠切分，适合无结构文档                          | ⭐ 政策文件     |

### 2.2 维度差异化检索

| 方案                                    | 来源                            | 核心思路                              | 适用性          |
| --------------------------------------- | ------------------------------- | ------------------------------------- | --------------- |
| **Conditional Retrieval Routing** | Self-RAG / CRAG                 | 根据查询意图分类，路由到不同检索策略  | ⭐⭐⭐ 核心方案 |
| **Hybrid Search (BM25 + Vector)** | Weaviate / Qdrant               | 关键词精确匹配 + 语义相似度，加权融合 | ⭐⭐⭐ 法律法规 |
| **Query Rewriting + Expansion**   | Query2Doc / Step-Back Prompting | 查询改写+扩展，提升召回率             | ⭐⭐ 技术标准   |
| **Cross-Encoder Reranking**       | Cohere / BGE-Reranker           | 检索后精排，提升精度                  | ⭐⭐⭐ 所有维度 |
| **Adaptive Retrieval**            | FLARE / DSPy                    | 根据生成置信度动态决定是否检索        | ⭐⭐ 规划思路层 |

### 2.3 规划领域特化参考

| 参考                           | 核心发现                        | 本项目应用                            |
| ------------------------------ | ------------------------------- | ------------------------------------- |
| **SuperMap CSPON**       | 规划知识图谱 + 法规条文精确检索 | 法律法规 → 知识图谱三元组            |
| **规易AI**               | 2000+ 专业术语库 + 标准化查询   | DictionaryCenter 编码体系 → 查询扩展 |
| **GeoAgentBench**        | 117 原子工具 + Plan-and-React   | 维度 → 工具 → 检索策略映射          |
| **JackDaw (PoliRural+)** | 工具预过滤 + RAG + 值工程       | 维度级检索配置（预过滤+策略选择）     |

---

## 三、文档类型差异化切分方案

### 3.1 切分策略矩阵

| 文档类型           | 切分策略      | 最小单位     | chunk_size       | overlap | 特殊处理                            |
| ------------------ | ------------- | ------------ | ---------------- | ------- | ----------------------------------- |
| **法律法规** | 条款保留      | 条（第X条）  | 不限（按条切分） | 0       | 条内不可拆分；跨条引用附加上下文    |
| **技术规范** | 标题感知+父子 | 项（X.X.X）  | 2000             | 300     | 表格完整保留；公式附上下文          |
| **政策文件** | 递归切分      | 段落         | 1800             | 400     | 通知正文与附件分离；适用范围前置    |
| **案例**     | 语义切分      | 完整案例段落 | 3000             | 500     | 案例背景+措施+效果保持完整          |
| **上位规划** | 层级感知      | 节（X.X）    | 2500             | 400     | 层级路径（省→市→县）注入 metadata |
| **专业教材** | 标题感知      | 节（X.X）    | 2500             | 500     | 当前策略基本适用，微调即可          |

### 3.2 法律法规切分：条款保留策略

**核心原则**：法条是不可拆分的语义单元

```python
class LegalSlicer:
    """法律法规专用切分器 — 条款保留策略"""

    # 法条识别模式
    ARTICLE_PATTERNS = [
        r"第[一二三四五六七八九十百千]+条",   # 中文数字法条
        r"第\d+条",                          # 阿拉伯数字法条
    ]

    # 款级识别（条内分段）
    PARAGRAPH_PATTERN = r"（[一二三四五六七八九十]+）"  # （一）（二）等

    def slice(self, content: str, source_name: str) -> List[HierarchyChunk]:
        """
        切分策略：
        1. 按章/节/条层级切分
        2. 条是最小独立单位，不可拆分
        3. 款级作为条内结构保留
        4. 跨条引用时附加被引用条的摘要
        """
        # Step 1: 识别法条边界
        articles = self._split_by_articles(content)

        # Step 2: 为每条生成摘要（SAC — Summary-Augmented Chunking）
        for article in articles:
            article.summary = self._generate_article_summary(article.content)

        # Step 3: 检测跨条引用，附加上下文
        for article in articles:
            refs = self._detect_cross_references(article.content)
            if refs:
                article.context_refs = [
                    self._get_article_summary(ref_id) for ref_id in refs
                ]

        return articles
```

**切分效果对比**：

```
当前（统一切分）：
  Chunk 1: "第37条 非农业建设必须节约使用土地...不得占用耕地；"
  Chunk 2: "可以利用劣地的，不得占用好地。第38条..."

增强后（条款保留）：
  Chunk 1: "第37条 非农业建设必须节约使用土地，可以利用荒地的，
            不得占用耕地；可以利用劣地的，不得占用好地。"
           [摘要: 限制非农建设占用耕地，优先使用荒地劣地]
           [引用: 第36条(保护耕地基本国策)]
```

### 3.3 技术规范切分：标题感知+表格保留

**核心原则**：表格和公式不可跨 chunk

```python
class StandardSlicer:
    """技术规范专用切分器 — 标题感知+表格保留"""

    def slice(self, content: str, source_name: str) -> List[HierarchyChunk]:
        """
        切分策略：
        1. 按标题层级切分（与当前 HierarchySlicer 类似）
        2. 表格检测：整张表格归入同一 chunk
        3. 表格超长时：表格独立 chunk + 前后文摘要
        4. 公式保留：公式+说明+适用条件在同一 chunk
        5. 父子关系：子 chunk 携带父 chunk 摘要（SAC）
        """
        # Step 1: 标题切分（复用 HierarchySlicer）
        base_chunks = self._base_slice(content, source_name)

        # Step 2: 表格完整性修复
        for chunk in base_chunks:
            if self._has_broken_table(chunk.content):
                chunk.content = self._repair_table(chunk.content)

        # Step 3: SAC — 章节摘要注入
        for chunk in base_chunks:
            parent_summary = self._get_parent_summary(chunk.parent_id)
            if parent_summary:
                chunk.content = f"[章节摘要: {parent_summary}]\n{chunk.content}"

        return base_chunks
```

### 3.4 案例切分：语义完整性

**核心原则**：案例的"背景→措施→效果"叙事链不可打断

```python
class CaseSlicer:
    """案例专用切分器 — 语义完整性"""

    NARRATIVE_MARKERS = {
        "background": ["现状", "背景", "问题", "困境", "挑战"],
        "measures": ["措施", "做法", "方案", "实施", "建设"],
        "effects": ["成效", "效果", "成果", "效益", "提升"],
    }

    def slice(self, content: str, source_name: str) -> List[HierarchyChunk]:
        """
        切分策略：
        1. 检测叙事结构（背景→措施→效果）
        2. 完整叙事段落作为最小单位
        3. 超长案例：按叙事阶段切分，每段附加案例摘要
        4. 案例间边界：标题+空行+新案例名
        """
        # Step 1: 识别案例边界
        cases = self._split_by_cases(content)

        # Step 2: 每个案例内部按叙事结构切分
        for case in cases:
            if len(case.content) > 3000:
                case.sections = self._split_by_narrative(case.content)
                # 每段附加案例摘要
                for section in case.sections:
                    section.case_summary = case.summary

        return cases
```

### 3.5 Summary-Augmented Chunking (SAC) — 通用增强

SAC 是所有文档类型的通用增强层，在每个 chunk 前置摘要：

```
原始 chunk:
  "3.2 用地指标控制\n村庄人均建设用地指标不超过120㎡，
   宅基地面积不超过120㎡/户..."

SAC 增强后:
  "[章节摘要: 第3章 用地标准与指标控制 — 规定村庄建设用地
   总量控制、人均指标、宅基地面积上限等核心约束]
   3.2 用地指标控制\n村庄人均建设用地指标不超过120㎡，
   宅基地面积不超过120㎡/户..."
```

**摘要生成策略**：

| 层级   | 摘要来源 | 生成方式                           |
| ------ | -------- | ---------------------------------- |
| 文档级 | 全文摘要 | LLM Flash 一次性生成（入库时）     |
| 章节级 | 章节摘要 | LLM Flash 按章节生成（入库时）     |
| 条款级 | 法条摘要 | LLM Flash 按条生成（法律法规专用） |

**成本估算**：78 文档 × 平均 5 章 × Flash LLM ≈ 390 次 Flash 调用，约 ¥2-5

---

## 四、维度差异化检索策略

### 4.1 检索路由架构

```
                    ┌─────────────────┐
                    │  查询意图分类    │
                    │  IntentRouter   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ↓              ↓              ↓
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │ 法规检索   │  │ 标准检索   │  │ 案例检索   │
     │ LegalRoute │  │ TechRoute  │  │ CaseRoute  │
     └──────┬─────┘  └──────┬─────┘  └──────┬─────┘
            │               │               │
     ┌──────┴─────┐  ┌──────┴─────┐  ┌──────┴─────┐
     │BM25精确匹配│  │向量语义搜索│  │向量+案例摘要│
     │+向量补充   │  │+SAC上下文  │  │+项目类型过滤│
     │+法条完整性 │  │+表格保留   │  │+叙事完整性  │
     └────────────┘  └────────────┘  └────────────┘
```

### 4.2 维度→检索策略映射

| 维度                          | 检索路由                | 检索模式                | Top-K | 特殊配置                         |
| ----------------------------- | ----------------------- | ----------------------- | ----- | -------------------------------- |
| **superior_planning**   | LegalRoute              | BM25(0.6) + Vector(0.4) | 3     | 法条完整性检查；精确匹配法律名称 |
| **land_use**            | TechRoute + LegalRoute  | Vector(0.7) + BM25(0.3) | 4     | 用地分类标准精确匹配；法规补充   |
| **historical_culture**  | LegalRoute + TechRoute  | BM25(0.5) + Vector(0.5) | 3     | 保护法规精确匹配；技术标准补充   |
| **ecological_green**    | TechRoute + LegalRoute  | Vector(0.7) + BM25(0.3) | 4     | 生态红线标准；法规约束补充       |
| **infrastructure**      | TechRoute               | Vector(1.0) + SAC       | 5     | 表格完整性；设施配置标准         |
| **traffic**             | TechRoute               | Vector(1.0) + SAC       | 4     | 道路等级标准；可达性方法         |
| **public_services**     | TechRoute               | Vector(1.0) + SAC       | 4     | 设施配置标准表格                 |
| **industry**            | CaseRoute + TechRoute   | Vector(0.8) + Case(0.2) | 6     | 产业案例参考；技术标准           |
| **spatial_structure**   | CaseRoute + TechRoute   | Vector(0.6) + Case(0.4) | 5     | 空间布局案例；结构模式           |
| **settlement_planning** | CaseRoute + TechRoute   | Vector(0.6) + Case(0.4) | 5     | 居民点整治案例                   |
| **landscape**           | CaseRoute + TechRoute   | Vector(0.6) + Case(0.4) | 5     | 景观风貌案例                     |
| **villager_wishes**     | TechRoute               | Vector(1.0)             | 3     | 调查方法标准                     |
| **socio_economic**      | TechRoute               | Vector(1.0)             | 3     | 人口预测方法                     |
| **architecture**        | TechRoute + PolicyRoute | Vector(0.8) + BM25(0.2) | 4     | 建筑标准+风貌法规                |
| **natural_environment** | TechRoute               | Vector(1.0)             | 3     | 生态评价方法                     |
| **location**            | TechRoute               | Vector(1.0)             | 3     | 区位分析方法                     |

### 4.3 检索路由实现方案

```python
class IntentRouter:
    """查询意图分类器 — 决定检索路由"""

    ROUTE_RULES = {
        "legal": {
            "triggers": ["法规", "法律", "条例", "规定", "审批", "合规",
                         "土地管理法", "城乡规划法", "环境保护法"],
            "route": "LegalRoute",
        },
        "technical": {
            "triggers": ["标准", "规范", "指标", "方法", "计算", "配置",
                         "GB/T", "CJJ", "技术要求"],
            "route": "TechRoute",
        },
        "case": {
            "triggers": ["案例", "实践", "经验", "参考", "借鉴",
                         "示范", "典型"],
            "route": "CaseRoute",
        },
    }

    def classify(self, query: str, dim_key: str) -> str:
        """分类查询意图，返回路由名称"""
        # 1. 维度级硬路由（优先级最高）
        dim_route = self._get_dimension_route(dim_key)
        if dim_route:
            return dim_route

        # 2. 查询关键词匹配
        for route_name, rule in self.ROUTE_RULES.items():
            if any(trigger in query for trigger in rule["triggers"]):
                return rule["route"]

        # 3. 默认路由
        return "TechRoute"
```

### 4.4 BM25 + 向量混合检索

法律法规需要精确匹配（法条编号、法律名称），纯向量搜索效果差：

```python
class HybridRetriever:
    """混合检索器 — BM25 + 向量搜索加权融合"""

    def retrieve(self, query: str, k: int = 5,
                 bm25_weight: float = 0.4,
                 vector_weight: float = 0.6,
                 doc_types: List[str] = None) -> List[Dict]:
        """
        混合检索流程：
        1. BM25 关键词检索（精确匹配法条编号、法律名称）
        2. 向量语义检索（语义相似度）
        3. 加权融合（Reciprocal Rank Fusion）
        4. 去重 + 截断
        """
        # BM25 检索
        bm25_results = self._bm25_search(query, k=k*2, doc_types=doc_types)

        # 向量检索
        vector_results = self._vector_search(query, k=k*2, doc_types=doc_types)

        # Reciprocal Rank Fusion
        fused = self._rrf_merge(
            bm25_results, vector_results,
            bm25_weight, vector_weight
        )

        return fused[:k]

    def _rrf_merge(self, *result_lists, k=60):
        """Reciprocal Rank Fusion — 多路检索结果融合"""
        scores = {}
        for weight, results in zip(self.weights, result_lists):
            for rank, item in enumerate(results):
                doc_id = item["chunk_id"]
                scores[doc_id] = scores.get(doc_id, 0) + weight / (k + rank + 1)
        return sorted(scores.items(), key=lambda x: -x[1])
```

### 4.5 维度级检索配置扩展

在 `phases.yaml` 中为每个维度增加检索策略配置：

```yaml
# 当前配置（仅 prefer_doc_types）
- key: superior_planning
  rag_query: "上位规划衔接要求 村庄规划政策依据 土地利用总体规划"
  prefer_doc_types: [policy, planning]

# 增强配置（增加检索策略）
- key: superior_planning
  rag_query: "上位规划衔接要求 村庄规划政策依据 土地利用总体规划"
  prefer_doc_types: [policy, planning]
  retrieval_config:
    route: legal              # 检索路由
    hybrid_weights:           # 混合检索权重
      bm25: 0.6
      vector: 0.4
    top_k: 3                  # 检索数量
    score_threshold: 1.2      # 分数阈值（法规精确匹配，阈值低）
    chunk_integrity: true     # 法条完整性检查
    reranker: true            # 启用 Reranker
```

对应的 `DimensionConfig` 扩展：

```python
class RetrievalConfig(BaseModel):
    """维度级检索配置"""
    route: str = "tech"                    # legal | tech | case | hybrid
    hybrid_weights: Dict[str, float] = {    # 混合检索权重
        "bm25": 0.3,
        "vector": 0.7,
    }
    top_k: int = 5                         # 检索数量
    score_threshold: float = 1.5           # 分数阈值
    chunk_integrity: bool = False          # 法条完整性检查
    reranker: bool = False                 # 启用 Reranker
    sac_enabled: bool = True               # 启用摘要增强

class DimensionConfig(BaseModel):
    # ... 现有字段 ...
    retrieval_config: RetrievalConfig = Field(default_factory=RetrievalConfig)
```

---

## 五、法律法规检索专项优化

### 5.1 问题根因分析

08-rag-system.md §8.3 已记录：12 部法律法规从未被 RAG 检索命中。根因链：

```
generate_queries() 侧重技术指标
  → 生成查询如"人均建设用地指标"
    → ChromaDB 语义搜索偏向技术内容
      → 法律条文语义距离 > 技术标准
        → 法规 chunk 排名靠后
          → prefer_doc_types=[policy] 仅过滤不改变排序
            → 法规仍被技术标准挤出 Top-K
```

### 5.2 优化方案：法规知识图谱 + 精确检索

**方案 A：法规知识图谱（长期）**

将法律条文结构化为知识图谱三元组，支持精确查询：

```
(土地管理法, 第37条, "非农业建设必须节约使用土地")
(土地管理法, 第37条_适用, "非农业建设")
(土地管理法, 第37条_约束, "不得占用耕地")
(土地管理法, 第37条_例外, "可以利用荒地的")
```

查询时：`"建设用地审批"` → 图谱查询 → 命中第37条 → 返回完整法条

**方案 B：法规专用索引 + BM25（短期，推荐先实施）**

为法律法规建立独立的 BM25 索引，支持法条编号精确匹配：

```python
class LegalIndex:
    """法规专用索引 — BM25 + 法条编号精确匹配"""

    def search(self, query: str, k: int = 3) -> List[Dict]:
        # 1. 法条编号精确匹配（最高优先级）
        article_match = self._match_article_number(query)
        if article_match:
            return [article_match]

        # 2. 法律名称精确匹配
        law_match = self._match_law_name(query)
        if law_match:
            return law_match[:k]

        # 3. BM25 关键词检索
        bm25_results = self._bm25_search(query, k=k*2)

        # 4. 向量语义检索（补充）
        vector_results = self._vector_search(query, k=k)

        # 5. RRF 融合
        return self._rrf_merge(bm25_results, vector_results, k=k)
```

**方案 C：查询改写（中期）**

在 `generate_queries()` 中增加法规查询改写规则：

```python
# 当前：generate_queries() 侧重技术指标
# 生成: "人均建设用地指标"

# 增强：法规查询改写
# 生成: "土地管理法 建设用地审批" + "城乡规划法 建设用地标准"
```

实现方式：在 `_build_query_prompt()` 中为法规相关维度增加法规查询生成指令：

```python
if dim_key in LEGAL_RELEVANT_DIMS:
    prompt += """
    ## 法规查询补充
    除技术标准外，还需检索相关法律法规：
    1. 包含法律名称的精确查询（如"土地管理法 建设用地"）
    2. 包含法条编号的查询（如"第37条 耕地保护"）
    3. 包含法规关键词的查询（如"基本农田保护条例"）
    """
```

### 5.3 法规相关维度映射

| 维度               | 相关法规                                 | 查询改写示例                                   |
| ------------------ | ---------------------------------------- | ---------------------------------------------- |
| superior_planning  | 土地管理法、城乡规划法                   | "土地管理法 村庄规划" + "城乡规划法 乡村建设"  |
| land_use           | 土地管理法、基本农田保护条例             | "土地管理法 建设用地审批" + "基本农田保护条例" |
| historical_culture | 文物保护法、历史文化名城名镇名村保护条例 | "文物保护法 传统村落" + "历史文化名村保护条例" |
| ecological_green   | 环境保护法、森林法                       | "环境保护法 生态红线" + "森林法 生态保护"      |
| land_use_planning  | 土地管理法、城乡规划法                   | "土地管理法 用地规划" + "城乡规划法 用地布局"  |
| architecture       | 城乡规划法、建筑法                       | "城乡规划法 建筑管理" + "建筑法 农房建设"      |

---

## 六、Cross-Encoder Reranking 方案

### 6.1 为什么需要 Reranking

当前检索仅使用 Bi-Encoder（向量相似度），精度有限：

```
查询: "历史文化保护规划"
Bi-Encoder 结果:
  1. [0.82] "历史文化街区保护规划技术规范" — 相关但非法规
  2. [0.79] "传统村落保护发展规划" — 案例类
  3. [0.76] "文物保护法第13条" — 法规，但排名靠后

Cross-Encoder Reranking 后:
  1. [0.95] "文物保护法第13条" — 法规，精确匹配
  2. [0.91] "历史文化街区保护规划技术规范" — 技术标准
  3. [0.85] "传统村落保护发展规划" — 案例
```

### 6.2 Reranker 选型

| 模型                         | 大小 | 延迟         | 中文支持 | 适用场景           |
| ---------------------------- | ---- | ------------ | -------- | ------------------ |
| **bge-reranker-v2-m3** | 560M | ~50ms/query  | ⭐⭐⭐   | 通用中文 Reranking |
| **bge-reranker-large** | 330M | ~30ms/query  | ⭐⭐⭐   | 低延迟场景         |
| **Cohere Rerank**      | API  | ~100ms/query | ⭐⭐     | 无需本地部署       |
| **Qwen-Reranker**      | 7B   | ~200ms/query | ⭐⭐⭐⭐ | 最高精度           |

**推荐**：`bge-reranker-v2-m3`（本地部署，中文优化，延迟可接受）

### 6.3 Reranking 管线

```python
class RerankingPipeline:
    """检索后精排管线"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        from FlagEmbedding import FlagReranker
        self.reranker = FlagReranker(model_name, use_fp16=True)

    def rerank(self, query: str, candidates: List[Dict],
               top_k: int = 5, min_score: float = 0.3) -> List[Dict]:
        """
        精排流程：
        1. 构造 query-document pairs
        2. Cross-Encoder 打分
        3. 过滤低分结果
        4. 返回 Top-K
        """
        pairs = [[query, c["content"][:512]] for c in candidates]
        scores = self.reranker.compute_score(pairs)

        for candidate, score in zip(candidates, scores):
            candidate["rerank_score"] = score

        ranked = sorted(candidates, key=lambda x: -x["rerank_score"])
        return [r for r in ranked if r["rerank_score"] >= min_score][:top_k]
```

---

## 七、实现路线图

### Phase 1 — 法律法规专项优化（2-3 天，最高优先级）

- [ ] 实现 `LegalSlicer`：条款保留切分策略
  - 法条边界识别（正则 + LLM 辅助）
  - 条内不可拆分
  - 跨条引用上下文附加
- [ ] 建立法规 BM25 索引（`rank_bm25` 库）
  - 12 部法律独立索引
  - 法条编号精确匹配
  - 法律名称精确匹配
- [ ] 修改 `generate_queries()` 增加法规查询改写
  - 法规相关维度增加法规查询生成指令
  - 6 个法规相关维度映射表
- [ ] 重新入库法律法规文档（使用 LegalSlicer）
- [ ] 验证：`superior_planning` 维度能否命中法律条文

### Phase 2 — 维度级检索配置（2-3 天）

- [ ] 扩展 `DimensionConfig` 增加 `retrieval_config`
- [ ] 扩展 `phases.yaml` 增加检索策略配置
- [ ] 实现 `IntentRouter` 查询意图分类
- [ ] 实现 `HybridRetriever` BM25 + 向量混合检索
- [ ] 修改 `RagService.search()` 支持路由分发
- [ ] 验证：各维度检索结果类型分布是否符合预期

### Phase 3 — Summary-Augmented Chunking（1-2 天）

- [ ] 实现 SAC 摘要生成（LLM Flash 批量处理）
  - 文档级摘要
  - 章节级摘要
  - 法条级摘要（法律法规专用）
- [ ] 修改入库流程：切分后自动生成摘要
- [ ] 修改检索流程：返回结果前置摘要
- [ ] 验证：检索结果上下文完整性提升

### Phase 4 — Reranking（1-2 天）

- [ ] 集成 `bge-reranker-v2-m3`
- [ ] 实现 `RerankingPipeline`
- [ ] 按维度配置 Reranker 开关
- [ ] 验证：检索精度提升（人工评估 Top-3 命中率）

### Phase 5 — 技术规范/案例切分优化（2-3 天）

- [ ] 实现 `StandardSlicer`：表格保留 + 公式上下文
- [ ] 实现 `CaseSlicer`：叙事完整性
- [ ] 重新入库技术规范和案例文档
- [ ] 验证：表格/案例检索完整性

---

## 八、关键复用与兼容性

### 8.1 复用清单

| 已有模块             | 路径                                        | 复用方式                                   |
| -------------------- | ------------------------------------------- | ------------------------------------------ |
| HierarchySlicer      | `modules/rag/chunker.py`                  | 技术规范/教材仍使用，法律法规/案例替换     |
| HierarchyVectorStore | `modules/rag/vector_store.py`             | 扩展支持混合检索，不替换                   |
| MetadataExtractor    | `modules/rag/utils/metadata_extractor.py` | 增加`doc_type` → 切分策略映射           |
| RagService           | `modules/rag/service.py`                  | 扩展`search()` 支持路由分发              |
| DimensionConfig      | `config/loader.py`                        | 扩展`retrieval_config` 字段              |
| DictionaryCenter     | `modules/gis/schema/dicts/`               | 查询扩展：用地分类名称 → 编码 → 法规关联 |

### 8.2 向后兼容

| 变更                 | 兼容策略                                                  |
| -------------------- | --------------------------------------------------------- |
| 新增 LegalSlicer     | 不影响现有 HierarchySlicer；按`doc_type` 路由选择切分器 |
| 新增 BM25 索引       | 独立索引，不影响 ChromaDB；混合检索是新增能力             |
| 扩展 DimensionConfig | `retrieval_config` 有默认值，旧配置自动兼容             |
| 新增 IntentRouter    | 默认路由为 TechRoute，与当前行为一致                      |
| 新增 Reranker        | 可选功能，`reranker: false` 时跳过                      |
| SAC 摘要             | 入库时生成，旧数据可增量补充                              |

### 8.3 数据迁移

```
Phase 1 迁移（法律法规）：
  1. 使用 LegalSlicer 重新切分 12 部法律
  2. 删除 ChromaDB 中旧的法律 chunks
  3. 重新入库新 chunks（含法条摘要）
  4. 建立 BM25 索引

Phase 5 迁移（技术规范+案例）：
  1. 使用 StandardSlicer/CaseSlicer 重新切分
  2. 增量更新 ChromaDB
  3. 生成 SAC 摘要
```

---

## 九、验证方案

### 9.1 法律法规检索验证

```
测试 1: superior_planning 维度
  输入: "上位规划与政策导向分析"
  当前: 0 条法规命中
  期望: ≥2 条法规命中（土地管理法、城乡规划法相关条文）

测试 2: 法条编号精确匹配
  输入: "土地管理法第37条"
  当前: 无法命中
  期望: 精确返回第37条完整内容

测试 3: 法条完整性
  输入: "非农业建设占用耕地"
  当前: 返回截断的法条片段
  期望: 返回完整法条（第37条全文）
```

### 9.2 维度检索差异化验证

```
测试 4: industry 维度
  输入: "村庄产业发展规划"
  当前: 仅返回技术标准
  期望: 技术标准 + 产业案例（≥1 条案例）

测试 5: infrastructure 维度
  输入: "村庄基础设施配置标准"
  当前: 可能返回截断的表格
  期望: 返回完整的设施配置标准表格

测试 6: historical_culture 维度
  输入: "历史文化保护规划"
  当前: 技术标准排名 > 法规
  期望: 法规排名 ≥ 技术标准（Reranking 后）
```

### 9.3 回归测试

- 现有维度报告生成功能不受影响（新配置有默认值）
- ChromaDB 数据兼容（增量更新，不破坏现有索引）
- RAG 查询缓存兼容（缓存键增加 retrieval_config 维度）

---

## 十、与 08-rag-system.md 的对齐



  一、优化方案对比研究分析
  让我基于搜索结果展示不同优化方案的效果：

  案例1: Anthropic的Contextual Retrieval (2024)

  优化措施： 为每个chunk生成50-100 token的文档上下文

  效果：

  ┌──────────────────────────────┬────────────┬──────────┐
  │             技术             │ 检索失败率 │ 改善幅度 │
  ├──────────────────────────────┼────────────┼──────────┤
  │ 基础RAG                      │ 5.7%       │ 基线     │
  ├──────────────────────────────┼────────────┼──────────┤
  │ +Contextual Embeddings       │ 3.7%       │ -35%     │
  ├──────────────────────────────┼────────────┼──────────┤
  │ +Contextual BM25             │ 2.9%       │ -49%     │
  ├──────────────────────────────┼────────────┼──────────┤
  │ +Contextual BM25 + Reranking │ 1.9%       │ -67%     │
  └──────────────────────────────┴────────────┴──────────┘

  成本分析：

- $1.02/百万token（prompt caching）
- 适用于800 token chunks + 50 token context instructions

  案例2: Chroma Research基准测试

  原文配置： 800 tokens, 400 tokens overlap → 1.4%精度

  优化配置： 200 tokens, 0% overlap → 5.18%精度（3.7倍提升）

  关键发现：

- 10% overlap是最佳比例（不是50%！）
- 句子级chunking性价比最高
- 语境悬崖：超过2500 tokens精度下降
- 语义chunking对自然文档提升有限

  案例3: eBay E-commerce RAG系统

  数据配置：

- Chunk size: 384 tokens（recursive split）
- Overlap: 50 tokens
- 2,645个问题-答案对测试

  结果：

- Recursive chunking表现最佳
- 元数据增强（标题+关键词）提升0.034 mAP
- Query refinement将mAP从0.45提升到0.48

  案例4: 自适应Chunking框架 (Ekimetrics, 2026)

  5个指标评估：

1. References Completeness (RC)
2. Intrachunk Cohesion (ICC)
3. Document Contextual Coherence (DCC)
4. Block Integrity (BI)
5. Size Compliance (SC)

  效果：

- 问题正确率从62-64%提升到72%
- 成功回答问题+30%（65 vs 49）

---

  二、当前代码的具体问题

  问题1：切片配置单一（chunker.py第715-720行）

# 当前代码

  splitter = RecursiveCharacterTextSplitter(
      chunk_size=max_chars,           # 固定2500
      chunk_overlap=200,              # 固定，不是10%关系！
      separators=["\n\n", "\n", "。", "；", "，", " ", ""],
  )

  问题：

- 使用200 overlap固定值（应使用10% chunk size比例）
- 所有文档类型相同配置
- 缺少结构感知的分割策略

  问题2：查询生成无维度差异化（service.py第320行）

# 当前代码

  llm = create_flash_llm(max_tokens=200, temperature=0.3)
  queries = [q.strip() for q in response.content.split("\n") if q.strip()]
  return queries[:8]  # 固定8个query

  问题：

- 所有维度使用相同的max_tokens=200
- 无温度调优（相同temperature=0.3）
- 固定top_k=8，无维度优先级差异

  问题3：缺少边界保护机制

  缺失：

- 空标题节点修复不完整
- 法律文档章节边界未保留
- 表格chunking策略简单（仅提取前后文本）

---

  三、具体可操作的优化实施

  优化方案A：文档类型感知的切片 + 边界保护

  步骤1：修改settings.py（文档配置部分）

# 在 backend/app/core/settings.py 第99-101行之后添加

# ==========================================

# RAG Doc-Type Aware Chunking Configuration

# ==========================================

  CHUNK_CONFIG = {
      # 专业教材：保留章节结构，可稍大chunk
      "textbook": {
          "max_chars": 3500,
          "overlap_percent": 10,
          "separators": ["\n\n##", "\n\n###", "\n\n", "\n", "。", "；", "，", " ", ""],
          "respect_boundaries": True,  # 保留章节边界
      },

    # 法律法规：保留条款边界，使用较小chunk + semantic cutoff
      "policy": {
          "max_chars": 2000,
          "overlap_percent": 10,
          "separators": ["\n\n第", "\n\n([一二三四五六七八九十]+)",
                         "\n\n[A-Z]\\. ", "\n\n", "。", "；"],
          "use_semantic_cutoff": True,  # 使用语义断点而非固定大小
          "respect_boundaries": True,  # 保留"第一条/第二款"边界
      },

    # 技术标准：平衡配置，精确chunk
      "standard": {
          "max_chars": 2500,
          "overlap_percent": 10,
          "separators": ["\n\n##", "\n\n###", "\n\n§", "\n\n", "。", "；", "，", " ", ""],
          "use_semantic_similarity": True,  # 使用语义相似度检测主题变化
      },

    # 案例：可大chunk，逐案存储
      "case": {
          "max_chars": 4000,
          "overlap_percent": 15,
          "separators": ["\n\n\n", "\n\n", "\n", "。", "；", "，", " ", ""],
          "respect_case_boundary": True,  # 保留案例标题边界
      },

    # 默认配置
      "default": {
          "max_chars": 3000,
          "overlap_percent": 10,
          "separators": ["\n\n", "\n", "。", "；", "，", " ", ""],
      }
  }

# Embedding限制（阿里云text-embedding-v4支持8192 token）

  ROBUST_CHUNK_SIZE = 4000  # 安全上限
  DEFAULT_CHUNK_SIZE = 3000  # 默认值
  MAX_OVERLAP_PERCENT = 20   # 最大overlap百分比

  步骤2：在chunker.py中添加结构感知切片器

# 在 backend/app/modules/rag/chunker.py 顶部导入部分添加

  from typing import Literal, Optional, Dict, List, Any

# 在类定义外部添加工具函数

  def _calculate_overlap_size(chunk_size: int, overlap_percent: int) -> int:
      """计算overlap大小（百分比）"""
      return max(50, chunk_size * overlap_percent // 100)  # 至少50字符

  def _detect_boundaries(content: str) -> Dict[str, List[str]]:
      """检测文档边界标记

    返回：{"paragraphs": [...], "legal_items": [...], "table_separators": [...]}
      """
      import re
      boundaries = {"paragraphs": [], "legal_items": [], "section_titles": []}

    # 法律条款
      legal_pattern = r'\n\n(第[一二三四五六七八九十百千]+条|第一款|第二款|[A-Z]\.\s+\w+)'
      legal_matches = re.findall(legal_pattern, content)
      boundaries["legal_items"] = legal_matches

    # PDF章节标题
      section_pattern = r'\n\n(第[一二三四五六七八九十]+章|Chapter\s+\d+|[IVX]+\.?\s+\w+)'
      section_matches = re.findall(section_pattern, content)
      boundaries["section_titles"] = section_matches

    # 段落边界（双换行）
      boundaries["paragraphs"] = [m.start() for m in re.finditer(r'\n\n', content)]

    return boundaries

  def _create_structure_preserving_splitter(chunk_size: int, overlap: int,
                                           separators: List[str],
                                           respect_boundaries: bool = False,
                                           doc_type: str = "default") -> Any:
      """创建保留文档结构的splitter

    Args:
          chunk_size: 每块字符数
          overlap: 重叠字符数
          separators: 分隔符列表（按优先级)
          respect_boundaries: 是否尊重文档边界
          doc_type: 文档类型（影响策略选择）
      """
      from langchain_text_splitters import RecursiveCharacterTextSplitter

    # 法律文档检测
      if respect_boundaries or doc_type == "policy":
          # 优先使用条款边界
          enhanced_separators = [
              r'\n\n第[一二三四五六七八九十百千]+条',
              r'\n\n[A-Z]\.\s+\w+',
              r'\n\n([一二三四五六七八九十百千]+款)',
              *separators
          ]
      else:
          enhanced_separators = separators

    return RecursiveCharacterTextSplitter(
          chunk_size=chunk_size,
          chunk_overlap=overlap,
          separators=enhanced_separators,
          # 增强分块算法，优先按边界切分
          length_function=len,
          is_separator_regex=True  # 移除此行（相当于is_separator_regex=False）
      )

# 修改 HierarchySlicer.slice_content() 方法

  async def _slice_content(
      self,
      content: str,
      source_name: str,
      doc_type: str = "default"
  ) -> List[HierarchyChunk]:
      """带结构感知的切片处理

    Args:
          content: Markdown内容
          source_name: 文档名称
          doc_type: 文档类型
      """
      from app.core.settings import CHUNK_CONFIG, ROBUST_CHUNK_SIZE, DEFAULT_CHUNK_SIZE

    # 1. 选择chunk配置
      chunk_cfg = CHUNK_CONFIG.get(doc_type, CHUNK_CONFIG["default"])
      max_chars = min(chunk_cfg["max_chars"], ROBUST_CHUNK_SIZE)
      overlap_size = _calculate_overlap_size(max_chars, chunk_cfg["overlap_percent"])
      separators = chunk_cfg["separators"]

    # 2. 检测文档边界（仅对政策/标准文档）
      use_robust_splitter = chunk_cfg.get("respect_boundaries", False) or
    doc_type == "policy" or doc_type in ["standard", "textbook"]

    # 3. 使用结构感知的splitter
      try:
          splitter = _create_structure_preserving_splitter(
              max_chars, overlap_size, separators,
              respect_boundaries=use_robust_splitter,
              doc_type=doc_type
          )
          documents = splitter.split_text(content)
      except Exception as e:
          logger.warning(f"[Chunker] Robust splitter failed: {e}, using fallback")
          # 回退到简单分块
          documents = self._fallback_simple(content, source_name)

    # 4. 处理超长切片
      results = []
      for doc in documents:
          if len(doc.page_content) > max_chars * 3:  # 单块 > 3倍chunk_size
              # 按1000字符分块
              sub_chunks = self._split_by_char_limit(doc.page_content, 1000, source_name)
              results.extend(sub_chunks)
          else:
              results.append(self._create_hierarchy_chunk(doc, source_name))

    return results

  def _split_by_char_limit(self, content: str, limit: int, source_name: str) -> List[HierarchyChunk]:
    """按字符限制分块（防止超长切片）"""
      import math
      chunks_count = math.ceil(len(content) / limit)
      results = []

    for i in range(chunks_count):
          start = i * limit
          end = min((i + 1) * limit, len(content))
          chunk_text = content[start:end]

    chunk = HierarchyChunk(
              content=chunk_text,
              chunk_id=f"{source_name}_{i}",
              depth=0,
              parent_id=None,
              ancestors=[],
              section_title=f"Section {i+1}",
              metadata={"source": source_name, "is_split": True}
          )
          results.append(chunk)

    return results

  步骤3：增强表格chunking（parse_tools.py现有代码优化）

# 在 backend/app/tools/gis/parse_tools.py 的 extract_structured_text 函数中

  async def extract_structured_text(
      section_content: str,
      table_type: str = "general",
      deduplicate_rows: bool = True  # 新增参数
  ) -> Dict[str, Any]:
      """提取结构化表格数据（增强版）

    新增功能：
      - 表格行去重
      - 头部判断改进
      - 自适应行分块
      """
      try:
          from app.core.settings import CHUNK_SIZE
          from langchain_core.messages import AIMessage

    # Stage 1: json_schema（优先）
          try:
              structured_llm = llm.with_structured_output(
                  TableExtractionResult, method="json_schema"
              )
              result = await structured_llm.ainvoke([
                  SystemMessage(content=f"{prompt}\n\nReturn JSON output."),
                  HumanMessage(content=section_content),
              ])
              if result is not None:
                  # 表格行去重（按全部列值）
                  if deduplicate_rows:
                      seen_rows = set()
                      unique_rows = []
                      for row in result.rows:
                          row_key = tuple(row.values()) if isinstance(row, dict) else row
                          if row_key not in seen_rows:
                              seen_rows.add(row_key)
                              unique_rows.append(row)
                      result.rows = unique_rows
                      result.column_names = list(seen_rows.pop()[0].keys()) if seen_rows else
  result.column_names

    return make_result(
                      success=True,
                      data={
                          "rows": result.rows,
                          "column_names": result.column_names,
                          "confidence": result.confidence,
                          "row_count": len(result.rows),
                      },
                  )
          except Exception as parse_err:
              logger.debug("[extract_structured_text] Stage 1 failed: %s", parse_err)

    # Stage 2: Raw invoke + manual JSON parse（已有逻辑保持不变）
          raw = None
          try:
              raw_response = await llm.ainvoke([
                  SystemMessage(content=f"{prompt}\n\nReturn JSON output."),
                  HumanMessage(content=section_content),
              ])
              raw = raw_response.content if hasattr(raw_response, 'content') else str(raw_response)

    # 手动JSON解析（已有逻辑保持不变）
              json_str = re.sub(r'^``(?:json)?\s*', '', raw, flags=re.MULTILINE)               json_str = re.sub(r'\s*``$', '', json_str, flags=re.MULTILINE)

    obj_s = json_str.find('{')
              arr_s = json_str.find('[')
              if arr_s != -1 and (obj_s == -1 or arr_s < obj_s):
                  # 回退逻辑保持不变
                  ...
              else:
                  ...

    return make_result(
                  success=True,
                  data={
                      "rows": result.rows,
                      "column_names": result.column_names,
                      "confidence": result.confidence,
                      "row_count": len(result.rows),
                  },
              )
          except Exception as e2:
              logger.debug("[extract_structured_text] Stage 2 failed: %s", e2)

    # Stage 3: Flash repair（已有逻辑保持不变）
          ...

    return make_result(success=False, error="All 3 stages failed")
      except Exception as e:
          logger.warning("[extract_structured_text] Failed: %s", e)
          return make_result(success=False, error=str(e))

---

  优化方案B：维度级Query调优 + 上下文增强

  步骤1：修改settings.py（Query调优配置）

# 在 backend/app/core/settings.py 第320行附近添加

# ==========================================

# RAG Query Tuning Configuration

# ==========================================

  QUERY_TUNE_CONFIG = {
      # 技术标准类：短query，冷启动慢
      "technical": {
          "max_tokens": 150,          # 减少到150
          "temperature": 0.1,         # 更冷的温度（更精确）
          "top_k":

本探索文档完全对齐 `08-rag-system.md v8.0` 的架构，是增量增强而非重构：

| 08-rag-system.md 组件         | 当前状态              | 本文档增强                    |
| ----------------------------- | --------------------- | ----------------------------- |
| HierarchySlicer               | 统一切分              | 按文档类型路由到专用切分器    |
| HierarchyVectorStore          | 纯向量检索            | 扩展支持 BM25 + 向量混合      |
| RagService.generate_queries() | L1/L3 Prompt 差异     | 增加法规查询改写 + 意图路由   |
| RagService.search()           | prefer_doc_types 过滤 | 增加检索路由 + Reranking      |
| DimensionConfig               | prefer_doc_types      | 增加 retrieval_config         |
| MetadataExtractor             | doc_type 推断         | 增加 doc_type → 切分策略映射 |
| Small-to-Big                  | 占位切片合并          | 增加 SAC 摘要增强             |
| §8.3 法律法规未命中          | 已知问题              | 本文档 Phase 1 专项解决       |

---

## 附录 A：78 文档类型分布

| 类别                | 文档数 | doc_type | 切分策略                                      |
| ------------------- | ------ | -------- | --------------------------------------------- |
| 专业教材            | ~5     | textbook | 标题感知（当前策略）                          |
| 法律法规/法律       | ~12    | policy   | **条款保留**（LegalSlicer）             |
| 法律法规/地方性法规 | ~3     | policy   | **条款保留**（LegalSlicer）             |
| 政策文件/国家层面   | ~8     | policy   | 递归切分（PolicySlicer）                      |
| 政策文件/地方层面   | ~5     | policy   | 递归切分（PolicySlicer）                      |
| 技术规范/国家层面   | ~20    | standard | **标题感知+表格保留**（StandardSlicer） |
| 上位规划/广东省     | ~5     | planning | 层级感知（PlanningSlicer）                    |
| 相关案例            | ~20    | case     | **语义完整性**（CaseSlicer）            |

## 附录 B：BM25 实现参考

```python
# 使用 rank_bm25 库
from rank_bm25 import BM25Okapi
import jieba

class LegalBM25Index:
    """法规 BM25 索引"""

    def __init__(self):
        self.bm25 = None
        self.corpus = []  # chunk_id 列表
        self.tokenized_corpus = []

    def build(self, chunks: List[Dict]):
        """构建索引"""
        self.corpus = [c["chunk_id"] for c in chunks]
        self.tokenized_corpus = [
            list(jieba.cut(c["content"])) for c in chunks
        ]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def search(self, query: str, k: int = 5) -> List[Dict]:
        """BM25 检索"""
        tokenized_query = list(jieba.cut(query))
        scores = self.bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)),
                           key=lambda i: -scores[i])[:k]
        return [{"chunk_id": self.corpus[i],
                 "bm25_score": float(scores[i])}
                for i in top_indices if scores[i] > 0]
```

## 附录 C：Reciprocal Rank Fusion (RRF)

```python
def reciprocal_rank_fusion(
    result_lists: List[List[Dict]],
    weights: List[float],
    k: int = 60,
) -> List[Dict]:
    """
    RRF 融合多路检索结果

    公式: score(d) = Σ weight_i / (k + rank_i(d))

    Args:
        result_lists: 多路检索结果（每路已按分数排序）
        weights: 各路权重
        k: RRF 常数（默认 60，抑制高排名结果的过度优势）

    Returns:
        融合后的排序结果
    """
    scores = {}
    for weight, results in zip(weights, result_lists):
        for rank, item in enumerate(results):
            doc_id = item["chunk_id"]
            if doc_id not in scores:
                scores[doc_id] = {"score": 0, "item": item}
            scores[doc_id]["score"] += weight / (k + rank + 1)

    ranked = sorted(scores.values(), key=lambda x: -x["score"])
    return [r["item"] for r in ranked]
```
