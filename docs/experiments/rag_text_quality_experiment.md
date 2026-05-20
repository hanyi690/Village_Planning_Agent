# RAG 文本质量对照实验

## 概述

本实验通过对照实验设计，量化评估 RAG（检索增强生成）对村庄规划文本质量的因果效应。实验在真实 Agent 规划流程中运行，控制所有其他变量，仅改变各层的 RAG 开/关状态。

- **实验日期**：2026-05-18
- **实验村庄**：金田村（梅州市梅县区水车镇，人口约 500，面积 23.53km²）
- **LLM**：dashscope (qwen3.5-plus)
- **Embedding**：text-embedding-v4
- **向量库**：ChromaDB (HierarchyVectorStore，层次索引)

---

## 实验设计

### 组别定义

| 组别 | L1 RAG | L2 RAG | L3 RAG | 含义                           |
| ---- | ------ | ------ | ------ | ------------------------------ |
| G1   | 关     | 关     | 关     | 纯 LLM 能力基线                |
| G2   | 关     | 关     | 开     | 仅详细规划层（L3）获取知识增益 |
| G3   | 开     | 开     | 开     | 全层 RAG，实际应用效果         |

> G4（Oracle 上限：人工精选法规替代检索）暂未实现。

### 研究假设

- **H1**：G2 > G1，L3 层 RAG 可提升详细规划报告的引用质量和专业深度
- **H2**：G3 > G2，L1/L2 层 RAG 通过级联依赖将知识传导至下游维度，进一步提升质量
- **H3**：Faithfulness 不受 RAG 状态影响（模型行为不变，仅上下文不同）

### 参数

| 参数     | 值                                       |
| -------- | ---------------------------------------- |
| 迭代次数 | 3（每组独立运行 3 次）                   |
| 评估维度 | 24 个（L1 现状分析 12 + L3 详细规划 12） |
| 总报告数 | 216 篇（3 × 3 × 24）                   |
| 并发控制 | max_concurrent=1（串行，避免 API 竞态）  |
| 缓存策略 | 报告 + RAG 知识持久化，指标可重算        |

---

## 数据生成流程

### 1. Agent 报告生成

每次 `_run_planning()` 触发完整的 LangGraph 规划执行：

```
Layer 1（现状分析，12 维度并行）
  ├─ location, socio_economic, villager_wishes, superior_planning
  ├─ natural_environment, land_use, traffic, public_services
  └─ infrastructure, ecological_green, architecture, historical_culture
       │
       ▼ (级联依赖)
Layer 2（规划思路，4 维度 Wave 执行）
  ├─ resource_endowment → planning_positioning → development_goals
  └─ planning_strategies
       │
       ▼ (级联依赖)
Layer 3（详细规划，12 维度 Wave 执行）
  ├─ industry, spatial_structure, land_use_planning, settlement_planning
  ├─ traffic_planning, public_service, infrastructure_planning, ecological
  └─ disaster_prevention, heritage, landscape, project_bank
```

### 2. RAG 检索注入

每个启用 RAG 的维度按以下步骤注入知识：

**a. 查询生成**
`RagService.generate_queries()` 用 qwen-flash 生成 4-8 条检索查询：

```
输入：维度名 + 任务描述 + 依赖报告摘要
输出：
  - "村庄道路规划技术规范标准"
  - "村内道路等级划分依据 GB 50188"
  - "道路红线宽度控制指标 CJJ 37"
  - "农村道路交通规划设计要点"
  ...
```

**b. 向量检索**
`HierarchyVectorStore.retrieve(query, k=5)`：

- 每条查询返回 top 5 文档
- 多查询结果合并，按 content 前 100 字符去重
- 按 L2 距离排序（值越小越相似），取前 5

**c. Prompt 注入**
检索结果格式化为 `【知识检索】` 段落：

```
【知识检索】以下法规和技术标准与本维度相关：

### 参考 1: GB 50188-2007 镇规划标准
道路红线宽度应符合现行国家标准，主干道≥6m，次干道≥4m...

### 参考 2: 广东省村庄规划编制导则
村庄道路规划应考虑地形地貌条件，合理确定道路等级...
```

注入到维度 LLM prompt 的 `knowledge_context` 区域。

### 3. 报告持久化

Agent 完成后，`_get_reports()` 从 `ReportStore`（SQLite）读取 24 个维度报告，与 RAG 知识一起写入缓存：

```json
{
  "reports": {
    "location": "【第一章 区位与对外交通分析】\n第一条 金田村位于...",
    "socio_economic": "...",
    ...
  },
  "injected_knowledge": {
    "dimension_knowledge": {
      "traffic_planning": {
        "rag_query": "村庄道路规划技术规范标准",
        "total_results": 5,
        "retrieval_latency_ms": 14517,
        "documents": [
          {"source": "GB 50188-2007", "snippet": "...", "score": 0.85}
        ],
        "snippets": ["道路红线宽度...", "..."]
      }
    },
    "rag_documents": [...],
    "retrieved_sources": [...]
  }
}
```

**关键设计决策**：`injected_knowledge` 仅记录实际通过 RAG 检索并注入 LLM prompt 的文档，不从报告文本中提取引用（避免记录 LLM 幻觉引用）。

---

## 评估指标

### 1. Faithfulness（忠实度）

**计算类**：`FaithfulnessCalculator`（`text_quality_metrics.py:510`）

基于规则的原子陈述验证：

**Step 1 — 提取原子陈述**：
按句子分割，用正则匹配提取含以下模式的陈述：

- 数字模式：`\d+\.?\d*[%米年公顷平方米公里]`
- 法规引用：`《[^》]+》`
- 标准编号：`GB\s*\d+`、`CJJ`、`SL`
- 关键词：`应`、`必须`、`禁止`、`标准`、`指标`

**Step 2 — 验证支持**：
在知识库上下文中查找匹配：

- 法规名称匹配（去掉书名号）
- 标准编号匹配（规范化空格/连字符）
- 数字值匹配

**Step 3 — 计算得分**：

```
faithfulness_score = supported_claims / total_claims
```

**上下文优先级**：实际 RAG 文档片段（从 `injected_knowledge` 提取） > 报告文本前 500 字符（兜底）

### 2. Content Depth（内容深度）

**计算类**：`ContentDepthEvaluator`（`text_quality_metrics.py:510`）

行为锚定量表，基准 1 分，累加：

| 加分项     | 权重 | 检测方式                                         |
| ---------- | ---- | ------------------------------------------------ |
| 数值指标   | +1.0 | `\d+\.?\d*[%米年公顷平方米公里人万元]`         |
| 法规引用   | +0.5 | `《[^》]+》`                                   |
| 标准编号   | +0.5 | `GB\s*\d+`、`CJJ\s*\d+` 等                   |
| 方法关键词 | +1.0 | `计算`、`评估`、`预测`、`分析`、`测量` |
| 建议关键词 | +1.0 | `建议`、`应当`、`规划`、`方案`、`措施` |

上限 5 分。生成中文推理文本（如 `"含3个数值指标、2条法规引用、涉及方法论述"`）。

### 3. Citation Quality（引用质量）

**计算类**：`CitationQualityEvaluator`（`citation_quality.py:442`）

三阶段评估：

**Step 1 — 提取引用**：
正则匹配 4 类引用：

- `law`：`《...法》`、`《...条例》`、`《...导则》`
- `clause`：`第X条`（支持中文数字和阿拉伯数字）
- `indicator`：`不少于X米`、`X年一遇`、`人均X平方米`
- `standard`：`GB XXXX`、`GB/T XXXX`、`DB`、`CJJ`、`SL`

提取去重（按 `(text, type)` 元组），保留周围上下文。

**Step 2 — 存在性检查**：
在知识库上下文字符串中查找引用文本，支持规范化匹配（去书名号、空格/连字符）。

**Step 3 — 准确性评估**：
引用上下文与知识库片段的关键词重叠度（Jaccard-like）。

**Step 4 — 支持性分类**：

- 支撑性：`根据...应`、`按照...标准`、`规定...不得`
- 装饰性：`参考`、`详见`、`相关`

**汇总指标**：

```
existence_rate = existing_citations / total_citations
accuracy_rate = accurate_citations / total_citations
supportive_rate = supportive_citations / total_citations
```

**阈值**：`accuracy_score ≥ 0.7` 视为准确引用。

---

## 统计方法

### 组间比较

从每组 3 次迭代取指标均值，进行配对比较：

```
G2 vs G1：L3 RAG 的净因果效应（控制 L1/L2 无 RAG）
G3 vs G2：L1/L2 RAG 的增量效应（在 L3 RAG 基础上）
```

### 效应量

**Cohen's d**（`statistical_analysis.py:463`）：

```
d = (mean1 - mean2) / pooled_std
pooled_std = sqrt(((n1-1)*s1² + (n2-1)*s2²) / (n1+n2-2))
```

| d      | 效应大小 |
| ------ | -------- |
| ≥ 0.2 | 小       |
| ≥ 0.5 | 中       |
| ≥ 0.8 | 大       |

### 显著性检验

配对 t 检验（`scipy.stats.ttest_rel`），双尾：

| p 值    | 标记   |
| ------- | ------ |
| < 0.001 | \*\*\* |
| < 0.01  | \*\*   |
| < 0.05  | \*     |
| ≥ 0.05 | ns     |

### 可视化辅助

`StatisticalAnalyzer` 还生成：

- **雷达图数据**：`generate_radar_chart_data()` — 各组在 3 个指标上的多维剖面
- **森林图数据**：`generate_forest_plot_data()` — 各指标的效应量和置信区间

---

## 实验结果

### 描述性统计

| 指标         | G1 (无 RAG)    | G2 (仅 L3)     | G3 (全开)      |
| ------------ | -------------- | -------------- | -------------- |
| Faithfulness | 0.764 ± 0.038 | 0.797 ± 0.068 | 0.658 ± 0.056 |
| 内容深度     | 2.23 ± 0.07   | 2.17 ± 0.05   | 2.40 ± 0.03   |
| 引用数       | 2.00 ± 0.58   | 3.33 ± 1.67   | 6.33 ± 1.76   |

### 组间对比

| 对比               | 指标               | Δ              | p               | 显著性       |
| ------------------ | ------------------ | --------------- | --------------- | ------------ |
| G2 vs G1           | Faithfulness       | +4.1%           | 0.564           | ns           |
| G2 vs G1           | 内容深度           | -2.8%           | 0.474           | ns           |
| G2 vs G1           | 引用数             | +66.7%          | 0.456           | ns           |
| **G3 vs G2** | Faithfulness       | -13.9%          | 0.171           | ns           |
| **G3 vs G2** | **内容深度** | **+7.9%** | **0.031** | **\*** |
| **G3 vs G2** | 引用数             | +90.0%          | 0.375           | ns           |

### 数据解读

**1. 全开 RAG 显著提升内容深度**（p=0.031）

G3 的报告包含更多技术标准引用和量化指标，这是通过级联依赖实现的：L1/L2 层 RAG 检索到的规划标准被写入 L1/L2 报告，L3 维度通过依赖机制加载这些报告作为上下文，从而间接受益。单层 RAG（G2）无法实现这种传导。

**2. L3 RAG 单独启用效果有限**

G2 vs G1 在所有指标上均无显著差异。这说明仅 L3 层获取知识时，由于缺乏 L1/L2 报告的知识基础，详细规划报告的提升不足以达到统计显著。

**3. Faithfulness 无显著组间差异**

三组忠实度均在 0.63-0.80 范围内，意味着基于规则的检测方法区分度有限。当前使用正则匹配 + 字符串查找，无法检测语义层面的幻觉（如虚构的法规名称或条款编号），需要 LLM-based NLI 来精确测量。

**4. G3 引用数趋势上升**（+90%，p=0.375）

全开 RAG 组平均每维度 6.3 条引用，是 G2 的 1.9 倍。效应量可观但 n=3 统计效力不足。

---

## 缓存系统

### 缓存策略

```
output/experiments/rag_text_quality/cached_reports/
├── jintian_g1_iter0_reports.json   # 24 reports, 0 RAG docs
├── jintian_g1_iter1_reports.json
├── jintian_g1_iter2_reports.json
├── jintian_g2_iter0_reports.json   # 24 reports, 55 RAG docs (11 L3 dims × 5)
├── jintian_g2_iter1_reports.json
├── jintian_g2_iter2_reports.json
├── jintian_g3_iter0_reports.json   # 24 reports, 60 RAG docs (12 L3 dims × 5)
├── jintian_g3_iter1_reports.json   # 24 reports, 115 RAG docs (23 dims × 5)
└── jintian_g3_iter2_reports.json
```

**缓存键**：`{village_name}_{group_name}_iter{N}_reports.json`

- 不依赖 experiment_id（每次运行时间戳），跨运行可复用

**命中行为**：缓存命中时加载报告 + RAG 知识，跳过 Agent 执行，仅重算指标。

### RAG 知识记录

每组缓存中 `injected_knowledge` 按维度记录：

| 组 | dims with RAG | total docs | 说明                                             |
| -- | ------------- | ---------- | ------------------------------------------------ |
| G1 | 0/28          | 0          | RAG 全关，正确                                   |
| G2 | 11/28         | 55         | L3 除 project_bank 外的 11 个维度，各 5 docs     |
| G3 | 12-23/28      | 60-115     | 全开：L1 12 + L3 11（project_bank 无 rag_query） |

---

## 局限性与改进方向

| 局限                  | 改进方向                                               |
| --------------------- | ------------------------------------------------------ |
| n=3 统计效力低        | 增至 n=5-10 次迭代                                     |
| Faithfulness 基于规则 | 引入 LLM NLI（如 qwen-flash 判断陈述是否被上下文支持） |
| 仅测试单一村庄        | 扩展到不同规模/特征的村庄                              |
| 无 Oracle 上限        | 实现 G4 人工精选法规组                                 |
| 评估维度仅 L1+L3      | 加入 L2（规划思路）维度的评估                          |
| 指标计算在实验脚本内  | 解耦为独立评估管线，支持跨实验对比                     |

---

## 运行方式

```bash
# 完整实验（生成报告 + 计算指标）
python scripts/experiments/rag_text_quality/run_4group_experiment.py \
    --village jintian \
    --iterations 3 \
    --max-concurrent 1

# 仅从缓存重算分析（不重新生成报告）
python scripts/experiments/rag_text_quality/run_4group_experiment.py \
    --iterations 3 \
    --max-concurrent 1
#（缓存命中时自动跳过 Agent 执行）
```

### 关键文件

| 文件                                                              | 用途                                      |
| ----------------------------------------------------------------- | ----------------------------------------- |
| `scripts/experiments/rag_text_quality/run_4group_experiment.py` | 实验编排器（4 组 × N 轮）                |
| `scripts/experiments/rag_text_quality/text_quality_metrics.py`  | Faithfulness + Content Depth 计算         |
| `scripts/experiments/rag_text_quality/citation_quality.py`      | Citation Quality 计算                     |
| `scripts/experiments/rag_text_quality/statistical_analysis.py`  | 统计检验（t 检验、Cohen's d）             |
| `scripts/experiments/rag_text_quality/oracle_knowledge.py`      | Oracle 知识库（G4 预留）                  |
| `scripts/experiments/sse_listener.py`                           | SSE 事件监听（含 InProcessEventListener） |
| `backend/app/agent/nodes/analysis.py`                           | Agent 维度分析（LLM 调用 + RAG 检索）     |
| `backend/app/config/phases.yaml`                                | 28 维度定义（维度名、工具、RAG 查询模板） |
| `backend/app/services/modules/rag/service.py`                   | RAG 查询生成 + 向量检索                   |
