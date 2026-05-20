# 级联修复（Cascade Revision）实验详细说明文档

> **版本**: v1.0  
> **日期**: 2026-05-18  
> **适用项目**: 村庄规划智能体 (Village Planning Agent)

---

## 目录

1. [实验概述](#1-实验概述)
2. [系统架构](#2-系统架构)
3. [实验场景定义](#3-实验场景定义)
4. [数据模型](#4-数据模型)
5. [实验流程详解](#5-实验流程详解)
6. [评分体系](#6-评分体系)
7. [数据说明](#7-数据说明)
8. [当前实验结果](#8-当前实验结果)
9. [运行说明](#9-运行说明)
10. [附录](#10-附录)

---

## 1. 实验概述

### 1.1 实验目的

级联修复实验是村庄规划智能体项目的核心验证实验之一。实验旨在验证以下核心命题：

> **当一个规划维度报告被"驳回"（reject）后，所有受该变更影响的下游维度，是否能在语义上与修订后的上游维度保持一致性。**

### 1.2 核心命题

实验围绕三个关键问题展开：

| 问题 | 描述 | 验证方法 |
|------|------|---------|
| **反馈响应度** | 被驳回的维度是否充分响应了反馈意见？ | 正向关键词覆盖率 + 负向关键词清除率 + 内容变化度 |
| **语义对齐度** | 下游维度是否与修订后的上游维度在语义上一致？ | Embedding余弦相似度 + 关键词对齐覆盖 |
| **级联传播完整性** | 修订是否沿依赖DAG传播至所有受影响的下游维度？ | 影响树完整性检查 + 波次完成度验证 |

### 1.3 在项目中的位置

```
Village_Planning_Agent/
├── backend/                          # 生产后端 — 级联修订引擎
│   ├── app/agent/
│   │   ├── state.py                  # AgentState 修订字段定义
│   │   ├── routing.py                # 波次调度与级联路由
│   │   └── nodes/
│   │       ├── analysis.py           # 维度分析（含修订感知）
│   │       └── completion.py         # 修订完成检测
│   ├── app/config/
│   │   ├── phases.yaml               # 28维度定义与依赖关系
│   │   └── dependency.py             # 影响树计算、波次生成
│   └── app/services/
│       ├── runtime.py                # 执行引擎、检查点跟踪
│       ├── review.py                 # 审批/驳回操作
│       └── checkpoint.py             # 检查点持久化
│
└── scripts/experiments/              # 实验层
    ├── config.py                     # 场景定义、输出路径
    └── cascade_consistency/
        ├── run_baseline.py           # 基线报告生成器
        ├── run_experiment.py         # 实验编排器
        └── consistency_checker.py    # 一致性评分引擎
```

---

## 2. 系统架构

### 2.1 三层规划维度体系

项目定义了 28 个规划维度，分为三个层级：

**Layer 1 — 现状分析（12维度，并行执行）**

| 维度键 | 中文名称 | 维度键 | 中文名称 |
|--------|---------|--------|---------|
| `location` | 区位分析 | `land_use` | 土地利用现状 |
| `socio_economic` | 社会经济 | `traffic` | 交通现状 |
| `villager_wishes` | 村民意愿 | `public_services` | 公共服务现状 |
| `superior_planning` | 上位规划 | `infrastructure` | 基础设施现状 |
| `natural_environment` | 自然环境 | `ecological_green` | 生态绿地现状 |
| `architecture` | 建筑分析 | `historical_culture` | 历史文化 |

**Layer 2 — 规划思路（4维度，按波次执行）**

| 维度键 | 中文名称 |
|--------|---------|
| `resource_endowment` | 资源禀赋分析 |
| `planning_positioning` | 规划定位分析 |
| `development_goals` | 发展目标分析 |
| `planning_strategies` | 规划策略分析 |

**Layer 3 — 详细规划（12维度，按波次执行）**

| 维度键 | 中文名称 | 维度键 | 中文名称 |
|--------|---------|--------|---------|
| `industry` | 产业规划 | `infrastructure_planning` | 基础设施规划 |
| `spatial_structure` | 空间结构规划 | `ecological` | 生态绿地规划 |
| `land_use_planning` | 土地利用规划 | `disaster_prevention` | 防震减灾规划 |
| `settlement_planning` | 居民点规划 | `heritage` | 历史文保规划 |
| `traffic_planning` | 道路交通规划 | `landscape` | 村庄风貌指引 |
| `public_service` | 公共服务设施规划 | `project_bank` | 建设项目库 |

### 2.2 依赖关系与影响树

维度之间通过三种依赖关系连接：

- **`depends_on`**：层内依赖（Layer 2/3内部的维度间依赖）
- **`layer_depends_on`**：跨层引用 Layer 1
- **`phase_depends_on`**：跨层引用 Layer 2

影响树通过 BFS（广度优先搜索）计算，确定当某个维度被驳回时，哪些下游维度会受到影响，并按"波次"组织执行顺序。

#### 场景1影响树（驳回 `planning_positioning`）

```
Wave 0 (目标层):
  └─ planning_positioning

Wave 1 (直接下游，Layer 2→3):
  ├─ industry
  ├─ spatial_structure
  ├─ land_use_planning
  ├─ development_goals
  └─ planning_strategies

Wave 2 (间接受影响，Layer 3):
  ├─ settlement_planning      ├─ ecological
  ├─ traffic_planning          ├─ disaster_prevention
  ├─ public_service            ├─ heritage
  ├─ infrastructure_planning   ├─ landscape
  └─ project_bank
```

> **影响范围**: 3个波次，共14个维度（含目标维度），覆盖率50%（14/28）。

#### 场景2影响树（驳回 `natural_environment`）

```
Wave 0 (目标层):
  └─ natural_environment

Wave 1 (直接下游):
  ├─ resource_endowment       ├─ infrastructure_planning
  ├─ spatial_structure        ├─ ecological
  ├─ land_use_planning        └─ disaster_prevention

Wave 2 (次级下游):
  ├─ industry                 ├─ development_goals
  ├─ planning_positioning     ├─ planning_strategies
  └─ project_bank

Wave 3 (远端下游):
  ├─ settlement_planning      ├─ public_service
  ├─ traffic_planning         ├─ heritage
  └─ landscape
```

> **影响范围**: 4个波次，共20个维度（含目标维度），覆盖率71%（20/28）。

### 2.3 波次调度机制

级联修订采用严格波次调度（Wave-Ordered Dispatch），在 `backend/app/agent/routing.py` 中实现：

1. **`after_conversation` 路由**：检测 `need_revision=True` → 计算影响树 → 重置已完成维度 → 分发 Wave 0
2. **`after_analysis` 路由**：检测 `is_revision=True` → 使用 `get_next_revision_wave()` 获取下一波次 → 按波次分发 → 所有波次完成后返回 `END`
3. **完成检测**：`revision_completed_dims` 追踪每个波次的完成状态 → 全部完成时置 `is_revision=False`

关键原则：**每个波次只能在上一波次全部完成后才能开始**，确保下游维度能读取到最新的上游修订结果。

---

## 3. 实验场景定义

实验定义了两个驳回场景，配置位于 `scripts/experiments/config.py` 第68-102行。

### 3.1 场景1：驳回规划定位（Layer 2）

| 配置项 | 值 |
|--------|-----|
| 场景ID | `scenario1` |
| 名称 | 驳回规划定位（Layer 2） |
| 目标维度 | `planning_positioning` |
| 目标层级 | Layer 2 |
| 最小一致性阈值 | 0.6 |

**驳回反馈文本：**

> 金田村常住人口仅500人，不具备承接大规模旅游的基础设施条件。千年古檀树、古茶亭遗址等核心历史资源应划定为绝对保护对象，剥离重度商业开发权。规划定位应转向生态保育优先、客家文化微改造的渐进式发展路径。

**关键词检测集：**

| 类型 | 关键词列表 |
|------|-----------|
| 正向 | `生态保育`, `渐进式发展`, `客家文化微改造`, `绝对保护`, `保护优先`, `微改造` |
| 负向 | `大规模旅游`, `商业开发`, `景区化`, `旅游开发` |

### 3.2 场景2：驳回自然环境分析（Layer 1）

| 配置项 | 值 |
|--------|-----|
| 场景ID | `scenario2` |
| 名称 | 驳回自然环境分析（Layer 1） |
| 目标维度 | `natural_environment` |
| 目标层级 | Layer 1 |
| 最小一致性阈值 | 0.6 |

**驳回反馈文本：**

> 现状报告中明确记载金田村存在5处崩塌隐患点和35处滑坡隐患点，但当前分析未对隐患点的空间分布与影响范围进行充分评估，需强化地质灾害风险的分析深度。

**关键词检测集：**

| 类型 | 关键词列表 |
|------|-----------|
| 正向 | `崩塌隐患`, `滑坡隐患`, `地质灾害风险`, `隐患点分布`, `风险管控`, `风险评估` |
| 负向 | （无） |

---

## 4. 数据模型

### 4.1 核心数据结构

#### ExperimentResult（实验结果）

```python
@dataclass
class ExperimentResult:
    scenario_name: str                          # 场景标识
    session_id: str                             # 会话ID
    target_dimension: str                       # 被驳回的目标维度键
    impact_tree: Dict[int, List[str]]           # {波次索引: [维度键列表]}
    revision_diffs: List[RevisionDiff]          # 修订差异列表
    consistency_scores: Dict[str, ConsistencyResult]  # {维度键: 一致性分数}
    overall_consistency: float                  # 总体一致性评分 (0-1)
    from_cache: bool = False                    # 是否来自缓存
    generated_at: str                           # 生成时间 (ISO格式)
```

#### RevisionDiff（修订差异）

```python
@dataclass
class RevisionDiff:
    dimension_key: str        # 维度键
    dimension_name: str       # 维度中文名
    layer: int                # 层级 (1/2/3)
    wave: int                 # 影响树中的波次索引
    is_target: bool           # 是否为被驳回的目标维度
    old_content: str          # 基线内容（截断500字符）
    new_content: str          # 修订后内容（截断500字符）
    content_length_diff: int  # len(new) - len(old)
    keywords_added: List[str] # 新增正向关键词
    keywords_removed: List[str] # 移除的负向关键词
```

#### ConsistencyResult（一致性检验结果）

```python
@dataclass
class ConsistencyResult:
    dimension_key: str              # 维度键
    score: float                    # 混合一致性评分 (0-1)
    embedding_similarity: float     # Embedding余弦相似度（归一化后）
    keyword_coverage: float         # 关键词覆盖率
    content_change: float           # 内容变化度（仅目标维度有值）
    details: Dict[str, Any]         # 调试元数据（权重、错误信息等）
```

#### StatisticalReport（统计检验报告）

```python
@dataclass
class StatisticalReport:
    mean_score: float         # 均值
    std_score: float          # 标准差
    ci_95: tuple              # 95%置信区间 (lower, upper)
    cohens_d: float           # Cohen's d 效应量
    p_value: float            # 配对t检验p值
    interpretation: str       # 人类可读的统计解释
```

### 4.2 关键词对齐映射

`ConsistencyChecker.ALIGNMENT_KEYWORDS` 维护了一个三层关键词映射表，覆盖约12个目标维度与25个下游维度的语义关联：

```
Layer 1 → Layer 2 映射示例:
  natural_environment → resource_endowment: ["自然资源", "地形地貌", "气候条件"]
  natural_environment → disaster_prevention: ["地质灾害", "隐患点", "风险评估", "地质条件"]
  historical_culture → heritage: ["历史文化", "文保单位", "古树", "古茶亭"]
  infrastructure → infrastructure_planning: ["基础设施", "市政设施"]

Layer 2 → Layer 3 映射示例:
  planning_positioning → industry: ["发展定位", "产业方向"]
  planning_positioning → spatial_structure: ["规划定位", "空间策略"]
  planning_positioning → planning_strategies: ["规划策略", "发展路径"]
  land_use_planning → settlement_planning: ["用地规划", "建设用地"]
  development_goals → project_bank: ["目标导向", "项目策划"]
```

当维度间无预设映射时，将回退到通用对齐：提取目标内容中高频出现的2-4字中文短语，统计在下游内容中的覆盖率。

---

## 5. 实验流程详解

实验通过 `CascadeExperimentRunner` 类编排，共7步。

### 5.1 完整流程

```
Step 0: 基线生成
  run_baseline.py → 运行28维度完整规划 → baseline_reports.json
                              ↓
Step 1: 影响树计算
  get_impact_tree_compat(target_dim) → {wave: [dims]}
                              ↓
Step 2: 基线报告加载
  读取 baseline_reports.json → 28维度报告字典
                              ↓
Step 3: 分叉与修订注入
  从基线checkpoint fork → 注入need_revision等状态
  → 注入合成AIMessage触发after_conversation路由
  → SSE监听等待 revision checkpoint_saved
                              ↓
Step 4: 修订后报告收集
  ReportStore.get_layer_reports() x 3层 → 修订后报告字典
                              ↓
Step 5: 差异计算
  逐维度对比 old vs new → RevisionDiff列表
                              ↓
Step 6: 一致性检验
  目标维度: check_feedback_response()
  下游维度: check_semantic_alignment()
                              ↓
Step 7: 结果持久化
  → experiment_result_runN.json
  → consistency_scores_runN.json
```

### 5.2 Step 0：基线生成

**执行脚本**: `run_baseline.py`

运行完整的28维度规划 Graph，使用金田村现状数据。

- 使用 `InProcessEventListener` 监听 SSE 事件（`layer_completed`, `checkpoint_saved`, `error`）
- 等待所有3层完成后，通过 `ReportStore` 收集所有报告
- 保存到 `baseline_reports.json`

**输出数据结构**:
```json
{
  "session_id": "baseline_bf16cd6b",
  "checkpoint_id": "1f1525df-846d-6135-800f-ae11f42dfcb1",
  "generated_at": "2026-05-18T10:04:57",
  "dimension_count": 28,
  "reports": {
    "planning_positioning": "...",
    "industry": "...",
    ...
  }
}
```

### 5.3 Step 1：影响树计算

从 `backend/app/config/dependency.py` 调用 `get_impact_tree_compat(target_dim)`。

该函数通过 BFS 遍历依赖DAG，构建 `{wave_index: [dimension_keys]}` 映射：

- Wave 0 = 目标维度本身
- Wave 1+ = 下游维度（逐层发现）
- 跨全部三层追索（`depends_on` + `layer_depends_on` + `phase_depends_on`）

### 5.4 Step 2：基线报告加载

从 `baseline_reports.json` 读取 `reports` 字段，返回 `Dict[str, str]`（28个键值对）。

### 5.5 Step 3：分叉与修订注入（核心步骤）

这是实验最关键的技术步骤，实现了**从基线检查点分叉（fork）并注入修订触发器**的机制。

```
1. 获取基线 session_id 和 checkpoint_id
2. 通过 graph.aget_state() 获取基线检查点状态
3. 从基线 config 创建 fork_cfg（含 checkpoint_ns=""）

4. 第一轮 aupdate_state（as_node="conversation"）:
   注入修订触发器:
   - need_revision: True
   - revision_target_dimensions: [target_dim]
   - human_feedback: <场景反馈文本>
   - revision_feedback: <场景反馈文本>
   - is_revision: True

5. 第二轮 aupdate_state（as_node="conversation"）:
   注入合成 AIMessage:
   - tool_calls: [{name: "AdvancePlanningIntent", ...}]
   → 触发 after_conversation 路由

6. 启动 SSE 监听器（复用基线 session_id）

7. 通过 graph.astream(fork_cfg, stream_mode=['values','checkpoints'])
   消费执行流:
   - 每个 checkpoint 事件 → 创建 checkpoint_saved SSE 事件
   - 监听器等待 is_revision=True 的 checkpoint_saved
```

**后端路由响应链**:
- `after_conversation` 检测 `need_revision` → 构建影响树 → 重置 `completed_dimensions` → 分发 Wave 0
- 维度分析节点检测 `is_revision` → 使用修订提示词 → 完成后更新 `revision_completed_dims`
- `after_analysis` 检测修订模式 → 获取下一波次 → 按波次分发 → 全部完成后置 `last_revised_dimensions`
- `_trigger_planning_execution` 检测 `last_revised_dimensions` → 发送 `checkpoint_saved` 事件（带 `is_revision=True`）

### 5.6 Step 4：修订后报告收集

修订完成后，从 `ReportStore` 逐层获取更新后的报告：

```python
for layer in [1, 2, 3]:
    layer_reports = await store.get_layer_reports(session_id, layer)
    reports.update(layer_reports)
```

### 5.7 Step 5：差异计算

对影响树中每个维度进行比较分析：

| 比较项 | 计算方法 |
|--------|---------|
| `content_length_diff` | `len(new_content) - len(old_content)` |
| `keywords_added` | 正向关键词 ∩ (new - old) |
| `keywords_removed` | 负向关键词 ∩ (old - new) |
| 内容截断 | old/new 各截断至500字符用于展示 |

### 5.8 Step 6：一致性检验

详见第6章「评分体系」。

### 5.9 Step 7：结果持久化

每个实验运行生成两个JSON文件：

| 文件 | 内容 |
|------|------|
| `experiment_result_runN.json` | 完整的 `ExperimentResult`（含影响树、修订差异、一致性评分） |
| `consistency_scores_runN.json` | 精简版（仅维度分数映射，便于快速查看） |

### 5.10 缓存机制

修订后的报告缓存在 `cached_reports/` 目录中：

```
cached_reports/
  scenario1_run1_revision_reports.json
  scenario1_run2_revision_reports.json
  scenario1_run3_revision_reports.json
  scenario2_run1_revision_reports.json
  ...
```

缓存文件结构：
```json
{
  "scenario": "scenario1",
  "run": 1,
  "target_dimension": "planning_positioning",
  "impact_tree": {...},
  "reports": {"planning_positioning": "...", ...},
  "cached_at": "2026-05-18T..."
}
```

使用 `--no-cache` 参数可跳过缓存，强制重新生成修订。

---

## 6. 评分体系

### 6.1 目标维度：反馈响应度

**函数**: `ConsistencyChecker.check_feedback_response()`

用于评估被驳回的目标维度是否充分响应了反馈意见。

#### 评分公式

```
score = positive_coverage x 0.5 + negative_removal x 0.3 + content_change x 0.2
```

#### 三因子详解

**因子1：正向关键词覆盖率（权重50%）**

```
positive_coverage = found_positive / total_positive
```
- 检测修订后内容中出现了多少个期望的正向关键词
- 若无正向关键词配置，默认为0.5

**因子2：负向关键词清除率（权重30%）**

```
negative_in_old = count(negative_kw in old_content)
negative_in_new = count(negative_kw in new_content)
negative_removal = 1 - negative_in_new/negative_in_old  (if negative_in_old > 0)
                 = 1.0  (if old中无负向词 且 new中无)
                 = 0.5  (if old中无负向词 但 new中有)
```

**因子3：内容变化度（权重20%）**

```
change = 1 - SequenceMatcher(old, new).ratio()
clamped = 0.3  (if change < 0.1, 视为无实质修改)
        = 1.0  (if change > 0.8, 视为重写)
        = change (otherwise)
```

### 6.2 下游维度：语义对齐度

**函数**: `ConsistencyChecker.check_semantic_alignment()`

用于评估下游维度是否在语义上与修订后的目标维度保持一致。

#### 评分公式

```
score = embedding_similarity x 0.7 + keyword_coverage x 0.3
```

#### Embedding相似度（权重70%）

```
1. 调用 AliyunEmbeddings (text-embedding-v4) 生成目标内容和下游内容的向量
2. 计算余弦相似度: cosine_sim = dot(A,B) / (||A|| x ||B||)
3. 归一化到 [0,1]:
   normalized = max(0, (cosine_sim - offset) / scale)
   默认: offset=0.3, scale=0.7
```

**归一化校准**：通过5个预设中文样本对自动校准 `offset` 和 `scale` 参数：
```
样本对:
  ("生态保育优先，渐进式发展", "以保护为主，逐步推进")
  ("地质灾害风险评估", "滑坡隐患点分布分析")
  ("客家文化微改造", "历史资源保护修缮")
  ("特色南药产业", "林下经济发展")
  ("村庄总体规划", "土地利用详细规划")
```

偏移量取这些样本对的中位数余弦值，缩放因子 = 1 - 偏移量。

#### 关键词覆盖率（权重30%）

```
1. 从 ALIGNMENT_KEYWORDS 映射中查找预期关键词
2. keyword_coverage = found_keywords / expected_keywords
3. 若无映射，回退到通用对齐：提取目标内容高频2-4字短语，检查下游覆盖
```

#### 回退机制

当 Embedding API 不可用时（网络错误、密钥缺失等）：

- 纯关键词评分：`score = keyword_coverage`
- `details.fallback_to_keyword = True`

### 6.3 总体一致性

所有维度 `ConsistencyResult.score` 的算术平均值：

```
overall_consistency = sum(scores) / len(scores)
```

### 6.4 统计检验

`run_statistical_tests()` 函数提供多轮实验的统计分析：

| 指标 | 计算方法 |
|------|---------|
| **均值** | `np.mean(values)` |
| **标准差** | `np.std(values, ddof=1)` |
| **95%CI** | `scipy.stats.t.interval(0.95, n-1, mean, se)` |
| **Cohen's d** | `(mean_exp - mean_baseline) / pooled_std` |
| **p值** | `scipy.stats.ttest_rel()` 配对t检验 |
| **效应量解读** | d>=0.8: 大 / d>=0.5: 中 / d>=0.2: 小 / d<0.2: 可忽略 |
| **显著性** | p<0.01: 极显著 / p<0.05: 显著 / 否则: 不显著 |

---

## 7. 数据说明

### 7.1 输入数据

| 数据 | 路径 | 说明 |
|------|------|------|
| 金田村现状报告 | `docs/泗水镇金田村现状报告.docx` | Word文档，村庄背景数据 |
| 基线报告 | `output/experiments/cascade_consistency/baseline/baseline_reports.json` | 28维度完整基线 |
| 维度配置 | `backend/app/config/phases.yaml` | 维度定义与依赖关系 |
| 实验配置 | `scripts/experiments/config.py` | 场景定义、关键词、输出路径 |

### 7.2 输出目录结构

```
output/experiments/cascade_consistency/
├── baseline/
│   └── baseline_reports.json           # 基线报告（28维度）
├── cached_reports/
│   ├── scenario1_run1_revision_reports.json
│   ├── scenario1_run2_revision_reports.json
│   ├── scenario1_run3_revision_reports.json
│   ├── scenario2_run1_revision_reports.json
│   ├── scenario2_run2_revision_reports.json
│   └── scenario2_run3_revision_reports.json
├── scenario1_planning_positioning/
│   ├── experiment_result_run1.json     # 完整实验结果
│   ├── experiment_result_run2.json
│   ├── experiment_result_run3.json
│   ├── consistency_scores_run1.json    # 精简分数
│   ├── consistency_scores_run2.json
│   └── consistency_scores_run3.json
├── scenario2_natural_environment/
│   ├── experiment_result_run1.json
│   ├── experiment_result_run2.json
│   ├── experiment_result_run3.json
│   ├── consistency_scores_run1.json
│   ├── consistency_scores_run2.json
│   └── consistency_scores_run3.json
└── analysis/                           # 分析报告（待生成）
```

### 7.3 输出文件格式

#### experiment_result_runN.json

顶层字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `scenario_name` | string | 场景标识 |
| `session_id` | string | 会话ID |
| `target_dimension` | string | 被驳回的目标维度 |
| `impact_tree` | object | `{波次号: [维度键数组]}` |
| `revision_diffs` | array | `RevisionDiff` 对象数组 |
| `consistency_scores` | object | `{维度键: ConsistencyResult}` |
| `overall_consistency` | float | 总体一致性评分 |
| `from_cache` | bool | 是否使用缓存 |
| `generated_at` | string | ISO 8601 时间戳 |

#### consistency_scores_runN.json

精简格式，仅为 `{维度键: ConsistencyResult}` 的扁平化字典。

### 7.4 Embedding缓存

`EmbeddingProvider` 使用 MD5哈希作为键的内存缓存（`_cache` 字典），避免相同文本的重复API调用。缓存生命周期为单次实验运行。

---

## 8. 当前实验结果

### 8.1 场景1运行数据（run1）

**配置**: 驳回 `planning_positioning`，目标为"生态保育优先"

#### 修订差异摘要

| 指标 | 值 |
|------|-----|
| 影响维度数 | 14 |
| 有内容变化的维度 | 0 |
| 平均 `content_length_diff` | 0 |
| 新增正向关键词（总计） | 0 |
| 移除负向关键词（总计） | 0 |

> **发现**: 所有14个维度的 `old_content` 与 `new_content` 完全相同，修订未产生任何内容变化。

#### 一致性评分

| 维度 | 评分 | Embedding相似度 | 关键词覆盖 |
|------|------|:---:|:---:|
| `planning_positioning` (目标) | 44.3% | N/A | 0.0% |
| `heritage` | 35.5% | 18.6% | 75.0% |
| `industry` | 30.0% | 28.6% | 33.3% |
| `spatial_structure` | 27.7% | 39.6% | 0.0% |
| `ecological` | 26.2% | 23.1% | 33.3% |
| `land_use_planning` | 25.0% | 14.3% | 50.0% |
| `disaster_prevention` | 22.5% | 0.0% | 75.0% |
| `settlement_planning` | 16.9% | 2.7% | 50.0% |
| `planning_strategies` | 15.0% | 21.4% | 0.0% |
| `development_goals` | 14.7% | 21.0% | 0.0% |
| `project_bank` | 7.2% | 10.3% | 0.0% |
| `traffic_planning` | 6.4% | 9.1% | 0.0% |
| `landscape` | 6.2% | 8.8% | 0.0% |
| `public_service` | 0.0% | 0.0% | 0.0% |

| 汇总指标 | 值 |
|----------|-----|
| **总体一致性** | **19.5%** |
| 阈值 (0.6) | 未通过 |
| 最高分维度 | `heritage` (35.5%) |
| 最低分维度 | `public_service` (0.0%) |

### 8.2 场景2运行数据（run1）

**配置**: 驳回 `natural_environment`，目标为"强化地质灾害风险分析"

#### 修订差异摘要

| 指标 | 值 |
|------|-----|
| 影响维度数 | 20 |
| 有内容变化的维度 | 0 |
| 平均 `content_length_diff` | 0 |

#### 一致性评分汇总

| 汇总指标 | 值 |
|----------|-----|
| **总体一致性** | **12.9%** |
| 阈值 (0.6) | 未通过 |
| 目标维度 (`natural_environment`) | 52.7% |
| 下游最高分 | 约 30% |
| 下游最低分 | 0.0% |

### 8.3 已知问题与局限性

#### 问题1：修订未产生内容变化

当前实验中，所有维度的 `content_length_diff` 均为0，`keywords_added`/`keywords_removed` 均为空。这表明**分叉+修订注入机制未能成功触发LLM生成修订后的内容**。

**可能原因**：

1. 基于检查点的分叉未能正确连接到修订状态——`need_revision` 标志可能未被 `analyze_dimension` 节点正确读取
2. LLM调用可能在无初始上下文的情况下运行，导致内容保持不变
3. 修订路径中的提示工程可能缺少明确的"重写"指令

**影响**：一致性分数反映的是基线文本与自身比较的结果，而非真正的修订对齐。Embedding相似度来自于相同/高度相似文本的比较，关键词覆盖率来自于`ALIGNMENT_KEYWORDS`映射的偶然匹配。

#### 问题2：部分Embedding调用失败

多个维度显示 `embedding_similarity: 0.0`（如 `public_service`, `infrastructure_planning`, `disaster_prevention`），可能由于API调用错误或超时。当Embedding失败时，评分回退到纯关键词匹配。

#### 问题3：关键词映射覆盖率有限

`ALIGNMENT_KEYWORDS` 映射覆盖约12个目标维度和25个下游维度，28维度中仍有部分维度无预设映射，回退到通用中文短语匹配，精度较低。

---

## 9. 运行说明

### 9.1 环境准备

```bash
# 确保在项目根目录
cd Village_Planning_Agent

# 确保依赖安装
pip install -r backend/requirements.txt

# 确保数据库和RAG知识库已初始化
# 确保 Aliyun DASHSCOPE_API_KEY 已配置
```

### 9.2 命令行用法

```bash
# 第一步：生成基线报告（仅需运行一次）
python scripts/experiments/cascade_consistency/run_baseline.py

# 第二步：运行场景1实验
python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario1

# 运行场景2实验
python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario2

# 多轮运行（3轮，支持统计分析）
python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario1 --runs 3
python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario2 --runs 3

# 禁用缓存，强制重新生成修订
python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario1 --no-cache
```

### 9.3 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--scenario` | 场景选择（scenario1 / scenario2） | 必选 |
| `--runs` | 运行轮数 | 1 |
| `--no-cache` | 禁用缓存，重新生成修订报告 | False（启用缓存） |

### 9.4 超时设置

| 阶段 | 超时时间 |
|------|---------|
| 基线生成（每层） | 900秒 (15分钟) |
| 修订等待 | 900秒 (15分钟) |
| Embedding API | 依赖HTTP客户端默认超时 |

---

## 10. 附录

### 10.1 关键文件路径索引

#### 实验脚本

| 文件 | 用途 |
|------|------|
| `scripts/experiments/cascade_consistency/run_baseline.py` | 基线报告生成器 |
| `scripts/experiments/cascade_consistency/run_experiment.py` | 实验编排器（分叉、修订、评分） |
| `scripts/experiments/cascade_consistency/consistency_checker.py` | 一致性检验引擎（Embedding、关键词、统计） |
| `scripts/experiments/config.py` | 场景定义、输出路径、村庄数据 |
| `scripts/experiments/sse_listener.py` | SSE事件监听器 |

#### 后端集成

| 文件 | 用途 |
|------|------|
| `backend/app/agent/state.py` | AgentState 修订级联字段定义 |
| `backend/app/agent/routing.py` | `after_conversation` / `after_analysis` 波次路由 |
| `backend/app/agent/nodes/analysis.py` | 维度分析（含修订感知） |
| `backend/app/agent/nodes/completion.py` | 层完成与修订完成检测 |
| `backend/app/config/phases.yaml` | 28维度定义与依赖关系 |
| `backend/app/config/dependency.py` | `get_impact_tree_compat()`、`get_next_revision_wave()` |
| `backend/app/services/runtime.py` | 执行引擎、检查点跟踪 |
| `backend/app/services/review.py` | 审批/驳回操作 |
| `backend/app/services/checkpoint.py` | 检查点持久化 |
| `backend/app/services/sse.py` | SSE事件管理与发布 |

#### 数据文件

| 文件 | 用途 |
|------|------|
| `docs/泗水镇金田村现状报告.docx` | 金田村背景数据（输入） |
| `output/experiments/cascade_consistency/baseline/baseline_reports.json` | 28维度基线报告 |
| `output/experiments/cascade_consistency/scenario1_planning_positioning/` | 场景1结果目录 |
| `output/experiments/cascade_consistency/scenario2_natural_environment/` | 场景2结果目录 |
| `output/experiments/cascade_consistency/cached_reports/` | 修订报告缓存目录 |

### 10.2 术语表

| 术语 | 英文 | 说明 |
|------|------|------|
| 维度 | Dimension | 规划分析的最小单元，共28个 |
| 波次 | Wave | 影响树中的执行层级 |
| 影响树 | Impact Tree | 从目标维度沿依赖DAG追索的下游维度集合 |
| 级联修订 | Cascade Revision | 驳回后沿影响树逐波次自动修订的机制 |
| 分叉 | Fork | 从基线检查点创建新的执行分支 |
| 反馈响应度 | Feedback Response | 目标维度对驳回反馈的响应程度评分 |
| 语义对齐度 | Semantic Alignment | 下游维度与修订后上游维度的语义一致性评分 |
| 检查点 | Checkpoint | LangGraph 状态快照，支持分叉和恢复 |
| 基线 | Baseline | 未受驳回影响的原始28维度报告 |
| SSE | Server-Sent Events | 服务端推送事件，用于实验监听执行状态 |

### 10.3 相关文档

- [实验实现报告](./experiment_implementation_report.md) — 实验脚本修复与技术方案
- [RAG文本质量实验](./rag_text_quality_experiment.md) — 相关RAG实验文档

---

*文档基于代码提交 `9899cbb4` 和 `91896f44` 的实际实现与运行数据编写。*
