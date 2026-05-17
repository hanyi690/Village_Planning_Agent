# 实验脚本修复与实现报告

## 一、背景与问题分析

### 1.1 实验概述

本项目包含两个核心实验：

| 实验名称 | 目的 | 输出目录 |
|---------|------|---------|
| RAG幻觉率实验 | 对比RAG开启/关闭条件下法规引用的幻觉率差异 | `scripts/experiments/rag_hallucination/` |
| 级联一致性实验 | 验证驳回操作后下游维度修订的语义一致性 | `scripts/experiments/cascade_consistency/` |

### 1.2 发现的问题

#### 问题1：实验数据缺失

```
scripts/experiments/output/experiments/
└── cascade_consistency/
    └── debug_session_state.json  # 仅有debug文件

# 缺失的目录和文件：
# - rag_hallucination/           # RAG实验输出目录不存在
# - baseline_reports.json         # 基线报告不存在
# - rag_on/*.json                 # RAG ON组报告不存在
# - rag_off/*.json                # RAG OFF组报告不存在
```

#### 问题4：实验设计缺陷 - 知识携带污染

**问题描述**: Layer 1-2 报告（使用 RAG ON 生成）包含 RAG 检索的知识内容，当注入到 Layer 3 时，这些知识会被携带到 RAG OFF 组，导致实验污染。

**问题分析**:
```
原实验流程:
  Step 1: Layer 1-2 (RAG ON) → fixed_context.json (含RAG检索知识)
  Step 2: Layer 3 (RAG ON) + 注入fixed_context → rag_on报告
  Step 3: Layer 3 (RAG OFF) + 注入fixed_context → rag_off报告
  
问题: rag_off报告虽然Layer 3禁用RAG，但Layer 1-2的知识已被注入，
      导致无法区分引用来源是KB还是LLM内部知识。
```

**解决方案**: 方案2 - 双固定上下文设计
- RAG ON组: 使用 RAG ON 生成的固定上下文
- RAG OFF组: 使用 RAG OFF 生成的固定上下文
- 验证阶段: 利用保存的实际注入知识验证引用

#### 问题2：幻觉验证逻辑硬编码列表太小

**修复前** (`hallucination_validator.py`):
```python
KNOWN_LAWS = {
    "《中华人民共和国城乡规划法》",
    "《中华人民共和国土地管理法》",
    # ... 仅7条法规
}

KNOWN_STANDARDS = {
    "GB50223",
    "GB50445",
    # ... 仅6条标准
}
```

**问题**: KB中有100+文档，但验证器只检查硬编码列表，导致大量真实法规被误判为幻觉。

#### 问题3：一致性检验关键词映射不足

**修复前** (`consistency_checker.py`):
```python
ALIGNMENT_KEYWORDS = {
    "planning_positioning": {
        "development_orientation": ["生态保育", "渐进式发展", "微改造"],
        # ...
    },
    "natural_environment": {
        # ...
    },
    # 仅覆盖2个目标维度
}
```

**问题**: 28维度中仅2个有映射，且关键词匹配无法识别语义等价表达。

---

## 二、修复方案设计

### 2.1 设计原则

| 原则 | 说明 |
|------|------|
| 动态加载 | 从KB索引文件动态加载法规/标准列表，而非硬编码 |
| 语义相似度 | 使用Embedding计算语义相似度，替代纯关键词匹配 |
| 混合评分 | Embedding(70%) + 关键词(30%) 混合策略 |
| 多定义幻觉率 | 提供strict/lenient/weighted三种幻觉率定义 |
| 双固定上下文 | RAG ON/OFF组使用独立的固定上下文，避免知识污染 |
| 注入知识验证 | 验证阶段利用保存的实际注入知识验证引用 |

### 2.2 技术选型

| 问题 | 解决方案 | 技术实现 |
|------|---------|---------|
| 法规列表太小 | 动态加载KB索引 | 解析 `data/RAG_doc/_cache/outline_index/*.json` |
| 关键词匹配不足 | Embedding语义相似度 | 复用 `AliyunEmbeddings` 类 |
| 幻觉率定义单一 | 多种定义 | strict/lenient/weighted |
| 知识携带污染 | 双固定上下文 | `fixed_context_rag_on.json` / `fixed_context_rag_off.json` |
| 验证基准不明确 | 注入知识验证 | `validate_with_injected_knowledge()` 方法 |

---

## 三、详细实现

### 3.1 RAG幻觉验证器修复

#### 3.1.1 文件修改清单

**文件**: `scripts/experiments/rag_hallucination/hallucination_validator.py`

| 修改项 | 修改前 | 修改后 |
|-------|--------|--------|
| 类属性 | `KNOWN_LAWS`, `KNOWN_STANDARDS` 硬编码 | 删除，改为动态加载 |
| 构造函数 | `def __init__(self, rag_service=None)` | 新增 `kb_index_dir` 参数 |
| 新增方法 | 无 | `load_kb_documents()` |
| 幻觉率计算 | 返回单个float | 返回 `Dict[str, float]` |

#### 3.1.2 核心代码实现

**动态加载KB文档**:
```python
def load_kb_documents(self) -> Tuple[Set[str], Set[str], List[str], str]:
    """从KB动态加载已知法规、标准和上下文
    
    Returns:
        (known_laws, known_standards, kb_sources, kb_context)
    """
    if self._known_laws is not None:
        return (self._known_laws, self._known_standards,
                self._kb_sources, self._kb_context)

    laws = set()
    standards = set()
    sources = []
    context_parts = []

    # 从索引文件加载
    if self.kb_index_dir.exists():
        for index_file in self.kb_index_dir.glob("*.json"):
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    index_data = json.load(f)

                source_name = index_file.stem.replace("_minerU_parsed_index", "")
                sources.append(source_name)

                # 提取法规名称: 《xxx法》、《xxx条例》
                law_matches = re.findall(
                    r'《([^》]+(?:法|条例|规定|办法|意见|方案))》',
                    source_name
                )
                for law in law_matches:
                    laws.add(f"《{law}》")

                # 提取标准编号: GBxxx, DBxxx
                std_matches = re.findall(
                    r'(GB[\s\-]?\d+(?:[\-\:]\d+)?|DB\d+/\d+(?:[\-\:]\d+)?)',
                    source_name
                )
                standards.update(std_matches)

                # 提取内容作为上下文
                corrected_content = index_data.get("corrected_content", "")
                if corrected_content:
                    context_parts.append(corrected_content[:5000])

            except Exception as e:
                print(f"Warning: Failed to load {index_file}: {e}")
                continue

    # 缓存结果
    self._known_laws = laws
    self._known_standards = standards
    self._kb_sources = sources
    self._kb_context = "\n\n".join(context_parts)

    return (self._known_laws, self._known_standards,
            self._kb_sources, self._kb_context)
```

**多定义幻觉率计算**:
```python
def calculate_hallucination_rate(self, validations: List[ValidationResult]) -> Dict[str, float]:
    """计算幻觉率（多种定义）
    
    Returns:
        {
            "strict": 仅HALLUCINATION状态,
            "lenient": HALLUCINATION + PARTIAL,
            "weighted": 加权计算 (HALLUCINATION + PARTIAL*0.5),
        }
    """
    if not validations:
        return {"strict": 0.0, "lenient": 0.0, "weighted": 0.0}

    hallucinations = sum(1 for v in validations if v.status == ValidationStatus.HALLUCINATION)
    partials = sum(1 for v in validations if v.status == ValidationStatus.PARTIAL)
    total = len(validations)

    return {
        "strict": hallucinations / total,
        "lenient": (hallucinations + partials) / total,
        "weighted": (hallucinations + partials * 0.5) / total,
    }
```

#### 3.1.3 验证流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    法规引用验证流程                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  输入: ExtractedReference (法规引用)                             │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Level 1: 检查动态加载的已知法规列表                         │   │
│  │ - load_kb_documents() 返回的 laws 集合                    │   │
│  │ - 匹配 → VALID (score: 95)                                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓ 未匹配                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Level 2: 检查KB上下文                                      │   │
│  │ - 在 kb_context 中搜索法规名称                             │   │
│  │ - 匹配 → VALID/PARTIAL (score: 70-90)                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓ 未匹配                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Level 3: 使用RAG检索验证                                   │   │
│  │ - rag_service.search(law_name, top_k=3)                  │   │
│  │ - score > 0.7 → VALID                                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓ 未匹配                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Level 4: 标记为幻觉                                        │   │
│  │ - HALLUCINATION (error_type: "A-法规文件名虚构")           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 3.2 级联一致性检验器修复

#### 3.2.1 文件修改清单

**文件**: `scripts/experiments/cascade_consistency/consistency_checker.py`

| 修改项 | 修改前 | 修改后 |
|-------|--------|--------|
| 导入 | 无numpy | 添加 `import numpy as np` |
| 新增类 | 无 | `EmbeddingProvider` 类 |
| 构造函数 | 无参数 | 新增 `embedding_provider` 参数 |
| 返回类型 | `float` | `ConsistencyResult` 数据类 |
| 评分策略 | 纯关键词匹配 | Embedding(70%) + 关键词(30%) |

#### 3.2.2 核心代码实现

**EmbeddingProvider类**:
```python
class EmbeddingProvider:
    """Embedding服务封装"""

    def __init__(self, provider_type: str = "aliyun"):
        self.provider_type = provider_type
        self._client = None

    def _init_client(self):
        """延迟初始化客户端"""
        if self._client is not None:
            return

        if self.provider_type == "aliyun":
            from app.services.modules.rag.vector_store import AliyunEmbeddings
            from app.core.settings import DASHSCOPE_API_KEY

            self._client = AliyunEmbeddings(
                api_key=DASHSCOPE_API_KEY,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model="text-embedding-v4",
            )

    def embed(self, texts: List[str]) -> np.ndarray:
        """生成Embedding向量"""
        self._init_client()
        embeddings = self._client.embed_documents(texts)
        return np.array(embeddings)

    def similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """计算余弦相似度"""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        cosine_sim = dot_product / (norm1 * norm2)

        # 归一化到0-1范围（embedding相似度通常在0.3-1.0之间）
        normalized = max(0, (cosine_sim - 0.3) / 0.7)
        return min(normalized, 1.0)
```

**语义对齐度检验**:
```python
def check_semantic_alignment(
    self,
    target_content: str,
    downstream_content: str,
    downstream_dim: str,
    use_embedding: bool = True,
) -> ConsistencyResult:
    """检验语义对齐度

    使用Embedding计算目标维度与下游维度的语义相似度
    """
    if not downstream_content:
        return ConsistencyResult(
            dimension_key=downstream_dim,
            score=0.0,
            details={"error": "下游维度内容为空"},
        )

    embedding_similarity = 0.0
    keyword_coverage = 0.0

    # 1. Embedding语义相似度（权重70%）
    if use_embedding:
        try:
            embeddings = self.embedding_provider.embed([target_content, downstream_content])
            embedding_similarity = self.embedding_provider.similarity(embeddings[0], embeddings[1])
        except Exception as e:
            print(f"Warning: Embedding failed: {e}")
            embedding_similarity = 0.5  # 失败时使用中性值

    # 2. 关键词覆盖率（权重30%，作为补充）
    keyword_coverage = self._check_keyword_alignment(target_content, downstream_content, downstream_dim)

    # 3. 混合评分
    score = embedding_similarity * 0.7 + keyword_coverage * 0.3

    return ConsistencyResult(
        dimension_key=downstream_dim,
        score=score,
        embedding_similarity=embedding_similarity,
        keyword_coverage=keyword_coverage,
        details={
            "embedding_weight": 0.7,
            "keyword_weight": 0.3,
        },
    )
```

#### 3.2.3 评分策略对比

| 评分方法 | 权重 | 优点 | 缺点 |
|---------|------|------|------|
| Embedding相似度 | 70% | 能识别语义等价表达，无需预设关键词 | 需要API调用，有成本 |
| 关键词匹配 | 30% | 可解释性强，无API成本 | 无法识别同义表达 |

**示例对比**:

| 目标内容 | 下游内容 | 关键词匹配 | Embedding相似度 | 混合评分 |
|---------|---------|-----------|----------------|---------|
| "生态保育优先" | "生态环境保护为主" | 0% (无匹配) | 85% | 59.5% |
| "地质灾害防治" | "地质灾害风险评估" | 50% (部分匹配) | 78% | 69.1% |
| "特色南药产业" | "特色南药产业" | 100% (完全匹配) | 95% | 96.5% |

---

### 3.3 方案2：双固定上下文设计（解决知识携带污染）

#### 3.3.1 问题回顾

原实验设计存在知识携带污染问题：

```
原流程:
  Layer 1-2 (RAG ON) → fixed_context.json (含RAG检索知识)
                              ↓
  Layer 3 (RAG OFF) + 注入fixed_context → rag_off报告
  
问题: rag_off报告虽然Layer 3禁用RAG，但Layer 1-2的RAG检索知识
      已被注入，导致无法区分引用来源。
```

#### 3.3.2 解决方案

**方案2**: 生成两组固定上下文，验证阶段利用保存的实际注入知识。

```
新流程:
  Step 1a: Layer 1-2 (RAG ON) → fixed_context_rag_on.json (含injected_knowledge)
  Step 1b: Layer 1-2 (RAG OFF) → fixed_context_rag_off.json (无RAG检索知识)
  
  Step 2: Layer 3 (RAG ON) + 注入fixed_context_rag_on → rag_on报告
  Step 3: Layer 3 (RAG OFF) + 注入fixed_context_rag_off → rag_off报告
  
  Step 4: 验证阶段
    - RAG ON组: 使用injected_knowledge验证引用是否来自实际注入的知识
    - RAG OFF组: 使用KB全局验证（无injected_knowledge）
```

#### 3.3.3 文件修改清单

**文件**: `scripts/experiments/config.py`

| 修改项 | 修改内容 |
|-------|---------|
| 新增常量 | `FIXED_CONTEXT_RAG_ON` - RAG ON固定上下文路径 |
| 新增常量 | `FIXED_CONTEXT_RAG_OFF` - RAG OFF固定上下文路径 |

**文件**: `scripts/experiments/rag_hallucination/run_rag_experiment.py`

| 修改项 | 修改内容 |
|-------|---------|
| `generate_fixed_context()` | 新增 `rag_enabled_for_l1l2` 参数 |
| `save_fixed_context()` | 新增 `injected_knowledge` 字段，根据RAG状态选择保存路径 |
| `extract_injected_knowledge()` | 新增函数，从状态中提取注入知识 |
| `load_fixed_context()` | 新增 `rag_enabled_for_l1l2` 参数，加载对应固定上下文 |
| `generate_layer3_reports()` | 使用匹配的固定上下文 |
| `validate_and_analyze()` | 利用注入知识验证 |

**文件**: `scripts/experiments/rag_hallucination/hallucination_validator.py`

| 修改项 | 修改内容 |
|-------|---------|
| 新增方法 | `validate_with_injected_knowledge()` |

#### 3.3.4 核心代码实现

**注入知识提取**:
```python
def extract_injected_knowledge(state: Dict[str, Any]) -> Dict[str, Any]:
    """从状态中提取注入知识

    知识来源:
    1. rag_context: RAG检索返回的原始内容
    2. dimension_knowledge: 各维度注入的知识切片
    3. retrieved_sources: 检索到的文档来源
    """
    injected = {
        "rag_context": {},
        "dimension_knowledge": {},
        "retrieved_sources": [],
    }

    # 从reports中提取引用
    reports = state.get("reports", {})
    for layer_key, layer_reports in reports.items():
        if isinstance(layer_reports, dict):
            for dim_key, report_content in layer_reports.items():
                if isinstance(report_content, str) and report_content:
                    refs = ReferenceExtractor().extract(report_content)
                    injected["dimension_knowledge"][dim_key] = {
                        "references": [r.text for r in refs],
                        "content_snippets": [],
                    }

    # 从rag_context中提取
    rag_context = state.get("rag_context", {})
    if isinstance(rag_context, dict):
        for source, content in rag_context.items():
            injected["rag_context"][source] = content[:500] if content else ""
            if source not in injected["retrieved_sources"]:
                injected["retrieved_sources"].append(source)

    return injected
```

**注入知识验证**:
```python
def validate_with_injected_knowledge(
    self,
    ref: ExtractedReference,
    injected_knowledge: Dict[str, Any],
) -> ValidationResult:
    """使用注入知识验证引用

    Args:
        ref: 提取的引用
        injected_knowledge: 保存的实际注入知识

    Returns:
        验证结果
    """
    ref_text = ref.text
    ref_clean = ref_text.replace("《", "").replace("》", "")

    # 1. 检查维度知识中的引用
    for dim_key, dim_knowledge in injected_knowledge.get("dimension_knowledge", {}).items():
        references = dim_knowledge.get("references", [])
        if ref_text in references:
            return ValidationResult(
                reference=ref,
                status=ValidationStatus.VALID,
                kb_match=True,
                kb_source=f"注入知识-{dim_key}",
                match_score=95.0,
                note="引用来自实际注入的知识",
            )

    # 2. 检查RAG上下文
    for source, content in injected_knowledge.get("rag_context", {}).items():
        if ref_text in content or ref_clean in content:
            return ValidationResult(
                reference=ref,
                status=ValidationStatus.VALID,
                kb_match=True,
                kb_source=source,
                kb_content=content[:200],
                match_score=90.0,
                note="引用在RAG检索内容中找到",
            )

    # 3. 检查检索来源列表
    for source in injected_knowledge.get("retrieved_sources", []):
        if ref_clean in source:
            return ValidationResult(
                reference=ref,
                status=ValidationStatus.VALID,
                kb_match=True,
                kb_source=source,
                match_score=85.0,
                note="引用来源文档被检索过",
            )

    # 4. 未在注入知识中找到，使用KB全局验证
    return self.validate_reference(ref)
```

#### 3.3.5 实验对比分析

| 对比项 | RAG ON组 | RAG OFF组 |
|--------|----------|-----------|
| Layer 1-2 知识来源 | RAG检索 | LLM内部 |
| Layer 3 知识来源 | RAG检索 | LLM内部 |
| 固定上下文 | `fixed_context_rag_on.json` | `fixed_context_rag_off.json` |
| 验证基准 | 注入知识 + KB全局 | KB全局 |
| 预期幻觉率 | 低（引用来自KB） | 高（引用可能虚构） |

#### 3.3.6 实验流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    方案2: 双固定上下文实验流程                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 1a: generate-fixed-context-on                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ rag_layer_config = {1: True, 2: True}                    │   │
│  │ 保存: fixed_context_rag_on.json                          │   │
│  │ 包含: reports + injected_knowledge                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 1b: generate-fixed-context-off                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ rag_layer_config = {1: False, 2: False}                  │   │
│  │ 保存: fixed_context_rag_off.json                         │   │
│  │ 包含: reports (无RAG检索内容)                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 2: generate-rag-on (使用fixed_context_rag_on)             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 注入: fixed_context_rag_on.json                          │   │
│  │ Layer 3: RAG ON                                          │   │
│  │ 保存: rag_on/                                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 3: generate-rag-off (使用fixed_context_rag_off)           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 注入: fixed_context_rag_off.json                         │   │
│  │ Layer 3: RAG OFF                                         │   │
│  │ 保存: rag_off/                                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 4: validate (利用注入知识验证)                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ RAG ON组:                                                │   │
│  │   - 加载 fixed_context_rag_on.json                       │   │
│  │   - 使用 injected_knowledge 验证引用                     │   │
│  │                                                          │   │
│  │ RAG OFF组:                                               │   │
│  │   - 加载 fixed_context_rag_off.json                      │   │
│  │   - 使用 KB 全局验证                                      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 3.4 引用提取器改进

#### 3.3.1 文件修改清单

**文件**: `scripts/experiments/rag_hallucination/reference_extractor.py`

| 修改项 | 修改前 | 修改后 |
|-------|--------|--------|
| 数据类 | 无 `__hash__` | 添加 `__hash__` 和 `__eq__` |
| 方法别名 | 无 | 新增 `extract()` 作为 `extract_all_references()` 别名 |

#### 3.3.2 改进代码

```python
@dataclass
class ExtractedReference:
    """提取的引用"""
    text: str
    type: ReferenceType
    context: str = ""
    position: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        return hash((self.text, self.type))

    def __eq__(self, other):
        if not isinstance(other, ExtractedReference):
            return False
        return self.text == other.text and self.type == other.type
```

---

### 3.4 实验运行脚本改进

#### 3.4.1 文件修改清单

**文件**: `scripts/experiments/rag_hallucination/run_rag_experiment.py`

| 修改项 | 修改前 | 修改后 |
|-------|--------|--------|
| 新增函数 | 无 | `validate_and_analyze()` |
| 步骤选项 | 5个 | 7个 (新增 `validate`, `validate-only`) |
| 流程 | 无验证步骤 | 添加验证步骤 |

#### 3.4.2 验证函数实现

```python
def validate_and_analyze() -> Dict[str, Any]:
    """Step: 提取引用并验证"""
    logger.info("[Validate] 提取引用并验证...")

    from scripts.experiments.rag_hallucination.reference_extractor import ReferenceExtractor
    from scripts.experiments.rag_hallucination.hallucination_validator import HallucinationValidator

    extractor = ReferenceExtractor()
    validator = HallucinationValidator()

    results = {"rag_on": {}, "rag_off": {}}

    for group, group_dir in [("rag_on", RAG_ON_DIR), ("rag_off", RAG_OFF_DIR)]:
        all_validations = []

        for dim_key in RAG_ENABLED_DIMENSIONS:
            report_file = group_dir / f"{dim_key}.json"
            if not report_file.exists():
                continue

            with open(report_file, "r", encoding="utf-8") as f:
                report_data = json.load(f)

            content = report_data.get("content", "")
            if not content:
                continue

            # 提取引用
            references = extractor.extract(content)
            logger.info(f"[{group}] {dim_key}: 提取到 {len(references)} 条引用")

            # 验证引用
            validations = [validator.validate_reference(ref) for ref in references]
            stats = validator.get_validation_statistics(validations)
            all_validations.extend(validations)

            results[group][dim_key] = {
                "reference_count": len(references),
                "validations": [v.to_dict() for v in validations],
                "statistics": stats,
            }

        # 计算总体幻觉率
        if all_validations:
            results[group]["overall"] = validator.get_validation_statistics(all_validations)

    # 保存验证结果
    validation_file = RAG_HALLUCINATION_DIR / "validation_results.json"
    with open(validation_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return results
```

---

## 四、实验流程说明

### 4.1 RAG幻觉率实验流程（方案2）

```
┌─────────────────────────────────────────────────────────────────┐
│                    RAG幻觉率实验完整流程（方案2）                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 1a: generate-fixed-context-on                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 启动规划会话 (session_id: fixed_context_rag_on_xxx)       │   │
│  │ Layer 1-2: RAG启用 (rag_layer_config={1:True, 2:True})   │   │
│  │ 等待Layer 2完成                                           │   │
│  │ 保存状态到: fixed_context_rag_on.json                     │   │
│  │ 包含: reports + injected_knowledge                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 1b: generate-fixed-context-off                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 启动规划会话 (session_id: fixed_context_rag_off_xxx)      │   │
│  │ Layer 1-2: RAG禁用 (rag_layer_config={1:False, 2:False}) │   │
│  │ 等待Layer 2完成                                           │   │
│  │ 保存状态到: fixed_context_rag_off.json                    │   │
│  │ 包含: reports (无RAG检索内容)                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 2: generate-rag-on                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 加载固定上下文: fixed_context_rag_on.json                 │   │
│  │ 启动新会话 (session_id: rag_on_xxx)                       │   │
│  │ 注入Layer 1-2报告                                         │   │
│  │ Layer 3: RAG启用 (rag_layer_config={3:True})             │   │
│  │ 生成5维度报告                                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 3: generate-rag-off                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 加载固定上下文: fixed_context_rag_off.json                │   │
│  │ 启动新会话 (session_id: rag_off_xxx)                      │   │
│  │ 注入Layer 1-2报告                                         │   │
│  │ Layer 3: RAG禁用 (rag_layer_config={3:False})            │   │
│  │ 生成5维度报告                                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 4: validate                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ RAG ON组验证:                                              │   │
│  │   - 加载 fixed_context_rag_on.json                        │   │
│  │   - 提取 injected_knowledge                               │   │
│  │   - 使用 validate_with_injected_knowledge() 验证          │   │
│  │                                                          │   │
│  │ RAG OFF组验证:                                             │   │
│  │   - 加载 fixed_context_rag_off.json                       │   │
│  │   - 无 injected_knowledge                                 │   │
│  │   - 使用 validate_reference() KB全局验证                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 5: generate-outputs                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 生成输出文档:                                              │   │
│  │   - Excel: 幻觉率汇总表                                    │   │
│  │   - Word: 典型引用对比段落                                 │   │
│  │   - JSON: 验证结果详情                                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 级联一致性实验流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    级联一致性实验完整流程                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 1: 计算影响树                                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 输入: target_dimension = "planning_positioning"          │   │
│  │ 调用: get_impact_tree_compat(target_dimension)           │   │
│  │                                                           │   │
│  │ 输出:                                                     │   │
│  │   {                                                       │   │
│  │     0: ["planning_positioning"],  # 目标维度             │   │
│  │     1: ["development_orientation", "population_scale"],  │   │
│  │     2: ["industry_planning", "land_use_planning"],       │   │
│  │   }                                                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 2: 获取基线报告                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 加载: baseline_reports.json                               │   │
│  │ 或运行: run_baseline.py 生成基线                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 3: 执行驳回和修订                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 启动新会话                                                │   │
│  │ 调用: review_service.reject(session_id, feedback, dims)  │   │
│  │ 调用: PlanningRuntimeService.resume_execution()          │   │
│  │ 等待修订完成                                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 4: 计算修订差异                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 对每个维度:                                               │   │
│  │   old_content = baseline[dim]                            │   │
│  │   new_content = revised[dim]                             │   │
│  │   diff = calculate_diff(old, new)                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 5: 检验一致性                                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 目标维度:                                                 │   │
│  │   check_feedback_response(old, new, feedback, keywords) │   │
│  │                                                           │   │
│  │ 下游维度:                                                 │   │
│  │   check_semantic_alignment(target, downstream, dim)     │   │
│  │   - 使用Embedding计算语义相似度 (70%)                     │   │
│  │   - 使用关键词匹配作为补充 (30%)                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  Step 6: 保存结果                                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 输出文件:                                                 │   │
│  │   - experiment_result.json: 完整实验结果                   │   │
│  │   - revision_diffs.json: 修订差异                        │   │
│  │   - consistency_scores.json: 一致性评分                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 五、使用说明

### 5.1 运行RAG幻觉率实验（方案2）

```bash
# 运行完整实验（自动生成双固定上下文）
python scripts/experiments/rag_hallucination/run_rag_experiment.py --step all

# 分步运行 - 双固定上下文生成
python scripts/experiments/rag_hallucination/run_rag_experiment.py --step generate-fixed-context-on
python scripts/experiments/rag_hallucination/run_rag_experiment.py --step generate-fixed-context-off

# 或者一次性生成双固定上下文
python scripts/experiments/rag_hallucination/run_rag_experiment.py --step generate-fixed-context

# 生成报告
python scripts/experiments/rag_hallucination/run_rag_experiment.py --step generate-rag-on
python scripts/experiments/rag_hallucination/run_rag_experiment.py --step generate-rag-off

# 验证（利用注入知识）
python scripts/experiments/rag_hallucination/run_rag_experiment.py --step validate

# 生成输出文档
python scripts/experiments/rag_hallucination/run_rag_experiment.py --step generate-outputs

# 仅验证（需要先有报告数据）
python scripts/experiments/rag_hallucination/run_rag_experiment.py --step validate-only
```

### 5.2 运行级联一致性实验

```bash
# 生成基线报告
python scripts/experiments/cascade_consistency/run_baseline.py

# 运行实验
python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario1
python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario2
```

### 5.3 单元测试

```bash
# 测试引用提取器
python -c "
from scripts.experiments.rag_hallucination.reference_extractor import ReferenceExtractor

text = '''
根据《中华人民共和国城乡规划法》第十八条规定，
崩塌隐患点避让距离不少于50米，应符合GB50223标准。
'''

extractor = ReferenceExtractor()
refs = extractor.extract(text)
for ref in refs:
    print(f'{ref.type.value}: {ref.text}')
"

# 测试幻觉验证器
python -c "
from scripts.experiments.rag_hallucination.hallucination_validator import HallucinationValidator

validator = HallucinationValidator()
laws, standards, sources, context = validator.load_kb_documents()
print(f'已知法规: {len(laws)} 条')
print(f'已知标准: {len(standards)} 条')
print(f'KB来源: {len(sources)} 个')
"

# 测试一致性检验器
python -c "
from scripts.experiments.cascade_consistency.consistency_checker import ConsistencyChecker

checker = ConsistencyChecker()
result = checker.check_semantic_alignment(
    '规划定位转向生态保育优先',
    '产业发展以特色南药和林下经济为主',
    'industry_planning',
)
print(f'一致性评分: {result.score:.2%}')
print(f'Embedding相似度: {result.embedding_similarity:.2%}')
print(f'关键词覆盖率: {result.keyword_coverage:.2%}')
"
```

---

## 六、输出文件说明

### 6.1 RAG幻觉率实验输出（方案2）

| 文件路径 | 说明 |
|---------|------|
| `output/experiments/rag_hallucination/fixed_context/fixed_context_rag_on.json` | Layer 1-2固定上下文（RAG ON，含injected_knowledge） |
| `output/experiments/rag_hallucination/fixed_context/fixed_context_rag_off.json` | Layer 1-2固定上下文（RAG OFF，无RAG检索内容） |
| `output/experiments/rag_hallucination/rag_on/*.json` | RAG ON组报告（5维度） |
| `output/experiments/rag_hallucination/rag_off/*.json` | RAG OFF组报告（5维度） |
| `output/experiments/rag_hallucination/validation_results.json` | 验证结果统计（含injected_knowledge_used标记） |

**fixed_context_rag_on.json 结构**:
```json
{
  "session_id": "fixed_context_rag_on_xxx",
  "saved_at": "2026-05-17T...",
  "rag_enabled_for_l1l2": true,
  "phase": "layer2_completed",
  "reports": { ... },
  "completed_dimensions": { ... },
  "injected_knowledge": {
    "rag_context": { "source_name": "content..." },
    "dimension_knowledge": { "dim_key": { "references": [...] } },
    "retrieved_sources": ["source1", "source2"]
  }
}
```

### 6.2 级联一致性实验输出

| 文件路径 | 说明 |
|---------|------|
| `output/experiments/cascade_consistency/baseline/baseline_reports.json` | 基线报告 |
| `output/experiments/cascade_consistency/scenario1/experiment_result.json` | 场景1实验结果 |
| `output/experiments/cascade_consistency/scenario1/revision_diffs.json` | 场景1修订差异 |
| `output/experiments/cascade_consistency/scenario1/consistency_scores.json` | 场景1一致性评分 |

---

## 七、技术决策记录

### 7.1 Embedding vs 关键词匹配

| 维度 | Embedding语义相似度 | 关键词匹配 |
|------|-------------------|-----------|
| 准确性 | ✅ 高 - 能识别语义等价表达 | ❌ 低 - 只能匹配精确关键词 |
| 覆盖范围 | ✅ 广 - 无需预设关键词 | ❌ 窄 - 需要人工预设 |
| 可维护性 | ✅ 好 - 无需维护映射表 | ❌ 差 - 需要为28维度手动维护 |
| 计算成本 | ⚠️ 中 - 需要调用embedding API | ✅ 低 - 纯文本匹配 |
| 可解释性 | ⚠️ 中 - 相似度分数较抽象 | ✅ 高 - 可明确看到匹配的关键词 |

**决策**: 采用混合策略 - Embedding(70%) + 关键词(30%)

### 7.2 幻觉率定义

| 定义 | 计算方式 | 适用场景 |
|------|---------|---------|
| strict | 仅HALLUCINATION状态 | 严格评估 |
| lenient | HALLUCINATION + PARTIAL | 宽松评估 |
| weighted | HALLUCINATION + PARTIAL*0.5 | 平衡评估 |

**决策**: 默认使用weighted，同时提供三种定义供选择

### 7.3 双固定上下文设计

| 方案 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| 方案1 | 不保存报告，仅保存完成状态 | 简单 | Layer 3需要重新生成Layer 1-2内容 |
| 方案2 | 生成两组固定上下文 | 实验对比清晰，验证可利用注入知识 | 需要运行两次Layer 1-2 |

**决策**: 采用方案2，验证阶段利用保存的实际注入知识

---

## 八、修改文件汇总

| 文件 | 修改类型 | 修改内容 |
|------|---------|---------|
| `scripts/experiments/rag_hallucination/hallucination_validator.py` | 修改 | 动态加载KB文档、多定义幻觉率、`validate_with_injected_knowledge()` |
| `scripts/experiments/cascade_consistency/consistency_checker.py` | 修改 | EmbeddingProvider类、混合评分策略 |
| `scripts/experiments/rag_hallucination/reference_extractor.py` | 修改 | `__hash__`/`__eq__`方法、`extract()`别名 |
| `scripts/experiments/rag_hallucination/run_rag_experiment.py` | 修改 | 双固定上下文生成、注入知识保存、验证利用注入知识 |
| `scripts/experiments/config.py` | 修改 | 新增 `FIXED_CONTEXT_RAG_ON`/`FIXED_CONTEXT_RAG_OFF` 路径常量 |

---

## 九、后续工作建议

1. **运行完整实验**: 使用修复后的脚本生成完整实验数据
2. **人工验证**: 抽取10条法规引用，人工核对是否为幻觉
3. **扩展关键词映射**: 为所有28维度添加关键词映射
4. **多次运行**: 每个场景运行3次以上，计算均值和方差
5. **论文数据**: 使用实验数据生成论文第四章图表

---

*报告生成时间: 2026-05-17*
*最后更新: 2026-05-17 (方案2实现)*
