# 实验框架设计文档

> **版本**: v2.0 (统一框架)
> **更新日期**: 2026-05-20
> **适用项目**: Village Planning Agent — 金田村村庄规划智能体

---

## 一、概述

### 1.1 背景

Village Planning Agent 包含两类核心实验：

| 实验                       | 目标                                                       | 旧入口                                                          |
| -------------------------- | ---------------------------------------------------------- | --------------------------------------------------------------- |
| **级联一致性实验**   | 验证驳回反馈后，下游维度修订是否保持语义一致性             | `cascade_consistency/run_baseline.py` + `run_experiment.py` |
| **RAG 文本质量实验** | 对比不同 RAG 配置下的文本 Faithfulness、内容深度、引用质量 | `rag_text_quality/run_4group_experiment.py`                   |

两套实验独立运行时存在大量重复代码（ReportStore 调用、规划图执行、SSE 监听、JSON 缓存、配置加载），且无法共享数据库已有数据。v2.0 统一框架消除了这些重复，提供：

- **共享基类** `ExperimentRunner`：封装规划图执行、规划文本生成、基线保存
- **数据抽象层** `ExperimentDataAccessor`：统一 ReportStore + 文件缓存接口
- **并行调度器** `ParallelExperimentScheduler`：支持多 session 并行运行
- **统一 CLI** `run.py`：单入口替代多个独立脚本

### 1.2 设计原则

1. **继承优于复制**：`CascadeRunner` 和 `RAGQualityRunner` 继承 `ExperimentRunner`，只实现实验特有逻辑
2. **缓存优先**：所有报告读取先查文件缓存，再查数据库，避免重复生成
3. **懒加载**：`MetricsSuite` 延迟导入重型模块（Embedding 模型、LLM 客户端）
4. **并行安全**：不同 session_id 的实验可并行运行，依赖 SQLite WAL + SSE 分桶 + thread_id 隔离

---

## 二、目录结构

```
scripts/experiments/
├── framework/                         # 统一框架
│   ├── __init__.py                   # 公共 API 导出
│   ├── config.py                     # 统一配置 (VillageConfig, ExperimentConfig, CascadeScenario)
│   ├── cache.py                      # 文件缓存 (ExperimentCache)
│   ├── data_accessor.py              # 数据抽象层 (ReportStore + 缓存)
│   ├── runner.py                     # 运行器基类 (ExperimentRunner)
│   ├── exporter.py                   # 统一导出 (ResultExporter)
│   ├── metrics.py                    # 指标封装 (MetricsSuite)
│   └── parallel.py                   # 并行调度器 (ParallelExperimentScheduler)
│
├── cascade/                           # 级联实验（新）
│   ├── __init__.py
│   └── runner.py                     # CascadeRunner 继承 ExperimentRunner
│
├── rag_quality/                       # RAG 质量实验（新）
│   ├── __init__.py
│   └── runner.py                     # RAGQualityRunner 继承 ExperimentRunner
│
├── cascade_consistency/               # 级联实验（旧，保留）
│   ├── consistency_checker.py        # 一致性检验器（被 framework/metrics.py 引用）
│   ├── run_baseline.py               # 旧基线脚本
│   └── run_experiment.py             # 旧实验脚本
│
├── rag_text_quality/                  # RAG 质量实验（旧，保留）
│   ├── text_quality_metrics.py       # 文本质量指标（被 framework/metrics.py 引用）
│   ├── citation_quality.py           # 引用质量评估（被 framework/metrics.py 引用）
│   ├── statistical_analysis.py       # 统计分析
│   └── oracle_knowledge.py           # Oracle 知识
│
├── sse_listener.py                    # SSE 事件监听器（共享）
└── run.py                             # 统一 CLI 入口
```

---

## 三、框架模块详细设计

### 3.1 `framework/config.py` — 统一配置

合并旧 `config.py` + `dependencies.py`，用 dataclass 替代散落常量。

#### 数据类

```python
@dataclass
class VillageConfig:
    village_name: str           # 村庄名称
    status_report: str          # 现状报告全文
    task_description: str       # 任务描述
    constraints: str            # 约束条件

@dataclass
class CascadeScenario:
    name: str                   # 场景名称
    target_dimension: str       # 驳回目标维度
    target_layer: int           # 目标层级 (1/2/3)
    feedback: str               # 反馈意见
    keywords: Dict[str, List[str]]  # 关键词检测 {dim_key: [keywords]}
    min_consistency_threshold: float = 0.6

@dataclass
class ExperimentConfig:
    experiment_id: str
    village: VillageConfig
    output_dir: Path
    cache_dir: Path
    use_cache: bool = True
    max_concurrent: int = 3
    cascade_scenarios: Dict[str, CascadeScenario]  # 级联场景
    rag_groups: Dict[str, Dict[int, bool]]         # RAG 组配置
```

#### 预定义场景

| 场景      | 目标维度                  | 层级 | 反馈摘要                           |
| --------- | ------------------------- | ---- | ---------------------------------- |
| scenario1 | `development_goals`     | L1   | 调整为南药+客家文化+生态康养       |
| scenario2 | `population_prediction` | L1   | 使用户籍人口（3200人，0.8%增长率） |
| scenario3 | `industry_planning`     | L2   | 增加南药深加工产业链               |

#### RAG 组配置

| 组 | L1  | L2  | L3  | 含义                 |
| -- | --- | --- | --- | -------------------- |
| g1 | off | off | off | 纯 LLM 基线          |
| g2 | off | off | on  | L3 RAG 净增益        |
| g3 | on  | off | on  | 全开（实际应用配置） |

#### 路径注入

`config.py` 在模块加载时自动将 `_PROJECT_ROOT` 和 `_BACKEND_ROOT` 注入 `sys.path`，确保所有 `from app.xxx` 导入正常工作。

---

### 3.2 `framework/cache.py` — 统一缓存

#### 类接口

```python
class ExperimentCache:
    def __init__(self, cache_dir: Path)

    @staticmethod
    def key_for(exp_type: str, identifier: str, run: int = 0) -> str
    # 返回: "{exp_type}_{identifier}_run{run}"

    def load(self, key: str) -> Optional[Dict[str, Any]]
    def save(self, key: str, data: Dict[str, Any], metadata: Dict = None) -> Path

    def load_reports(self, exp_type, identifier, run=0) -> Optional[Dict[str, str]]
    def save_reports(self, exp_type, identifier, reports, run=0, **extra) -> Path

    def invalidate(self, key: str) -> None
    def clear_all(self) -> int
```

#### 缓存文件格式

```json
{
  "_meta": {
    "cache_key": "reports_session_abc123_run0",
    "cached_at": "2026-05-20T14:30:00.000000"
  },
  "session_id": "abc123",
  "reports": { "dimension_key": "content..." }
}
```

#### 缓存策略

- **文件路径**: `{cache_dir}/{cache_key}.json`
- **元数据包装**: 每次 `save()` 自动附加 `_meta` 字段（cache_key, cached_at）
- **失效**: `invalidate()` 删除单个文件；`clear_all()` 清空整个目录

---

### 3.3 `framework/data_accessor.py` — 数据抽象层

#### 类接口

```python
class ExperimentDataAccessor:
    def __init__(self, cache: ExperimentCache)

    async def get_reports(
        self, session_id: str,
        layers: List[int] = None,          # 默认 [1,2,3]
        dimension_filter: List[str] = None, # 可选维度过滤
    ) -> Dict[str, str]

    async def get_reports_with_sources(
        self, session_id: str, layer: int
    ) -> Dict[str, Any]

    def load_baseline_from_file(self, path: Path) -> Dict[str, str]
    def load_layer_reports_from_file(self, path: Path) -> Dict[str, str]

    @staticmethod
    def infer_layer(dim_key: str) -> int
```

#### 数据读取流程

```
get_reports(session_id, layers)
  │
  ├─ 1. 查文件缓存 (cache_key = "reports_{session_id}_run0")
  │     ├─ 命中 → 返回缓存中的 reports
  │     └─ 未命中 ↓
  │
  ├─ 2. 查数据库 (ReportStore.get_instance())
  │     for layer in layers:
  │         reports.update(await store.get_layer_reports(session_id, layer))
  │
  └─ 3. 写入文件缓存
        cache.save(cache_key, {"session_id": ..., "reports": ...})
```

#### 数据库已有数据

| 表                    | 行数 | 说明                                                |
| --------------------- | ---- | --------------------------------------------------- |
| `dimension_reports` | 56   | session_id + 28 维度报告（L1×12 + L2×4 + L3×12） |
| `checkpoints`       | 32   | LangGraph 检查点                                    |
| `writes`            | 362  | 检查点写入记录                                      |

`get_reports()` 可直接复用这些数据，无需重新运行规划图。

---

### 3.4 `framework/runner.py` — 运行器基类

#### 类接口

```python
class ExperimentRunner(ABC):
    def __init__(self, config: ExperimentConfig)
    # 属性: self.config, self.cache, self.data_accessor

    async def run_planning_graph(
        self, session_id: str, project_name: str,
        rag_config: Dict[int, bool] = None,
        village_data: str = None,
    ) -> Dict[str, str]

    async def generate_planning_text(
        self, session_id: str, output_dir: Path,
        project_name: str, **kwargs
    ) -> Any

    async def save_baseline(
        self, session_id: str, reports: Dict[str, str],
        output_dir: Path, project_name: str,
        checkpoint_id: str = ""
    ) -> Path

    async def get_checkpoint_id(self, session_id: str) -> str

    @abstractmethod
    async def run(self) -> Any

    @staticmethod
    def new_session_id(tag: str = "") -> str
```

#### `run_planning_graph()` 执行流程

```
run_planning_graph(session_id, project_name, rag_config, village_data)
  │
  ├─ 1. PlanningRuntimeService.ensure_initialized()
  │     初始化 LangGraph StateGraph + Checkpointer
  │
  ├─ 2. PlanningRuntimeService.build_initial_state(...)
  │     构建 LangGraph 初始状态，注入 village_data, task_description,
  │     constraints, rag_layer_config 等
  │
  ├─ 3. SSE 初始化
  │     sse_manager.init_session(session_id, {...})
  │     sse_manager.set_execution_active(session_id, True)
  │
  ├─ 4. InProcessEventListener 连接
  │     listener = InProcessEventListener(session_id)
  │     await listener.connect()
  │
  ├─ 5. 启动规划执行
  │     task = asyncio.create_task(
  │         PlanningRuntimeService._trigger_planning_execution(session_id, initial_state)
  │     )
  │
  ├─ 6. 逐层等待完成
  │     for layer in [1, 2, 3]:
  │         await listener.wait_for_any_event(
  │             event_types=[EVENT_LAYER_COMPLETED, EVENT_ERROR],
  │             timeout=900,
  │             filter_func=lambda e: e.layer == layer or e.type == "error"
  │         )
  │
  ├─ 7. 清理
  │     await task
  │     await listener.disconnect()
  │
  └─ 8. 从数据库获取报告
        reports = await self.data_accessor.get_reports(session_id)
        return reports  # {dim_key: content}
```

#### `save_baseline()` 保存内容

| 文件                      | 内容                                                              |
| ------------------------- | ----------------------------------------------------------------- |
| `baseline_reports.json` | session_id, checkpoint_id, generated_at, dimension_count, reports |
| 规划文本 (MD + JSON)      | 由 `PlanningTextGenerator` 生成                                 |

---

### 3.5 `framework/exporter.py` — 统一导出

#### 类接口

```python
class ResultExporter:
    def __init__(self, cache: ExperimentCache)

    async def export_session(
        self, session_id: str, output_dir: Path,
        project_name: str = "village_planning",
        layers: List[int] = None,
        include_rag: bool = True,
        include_planning_text: bool = True,
    ) -> Path

    def export_experiment_result(
        self, result: Any, output_dir: Path,
        filename: str = "experiment_result.json"
    ) -> Path
```

#### `export_session()` 输出文件

| 文件                      | 内容                                          |
| ------------------------- | --------------------------------------------- |
| `layer{N}_reports.json` | 第 N 层维度报告                               |
| `rag_knowledge.json`    | 各层 RAG 知识来源（含 retrieved_chunks）      |
| 规划文本 (MD + JSON)      | 由 `PlanningTextGenerator` 生成             |
| `export_summary.json`   | 导出元信息（session_id, exported_at, layers） |

---

### 3.6 `framework/metrics.py` — 指标封装

#### 类接口

```python
class MetricsSuite:
    async def evaluate_text_quality(self, text, context, dim_key) -> Dict
    def evaluate_citation_quality(self, text, dim_key) -> Dict
    def check_consistency(self, old_text, new_text, feedback, keywords) -> float
    def check_consistency_detailed(self, old_text, new_text, feedback, keywords) -> Dict
```

#### 懒加载映射

| 方法                                                   | 首次调用时导入               | 来源模块                                       |
| ------------------------------------------------------ | ---------------------------- | ---------------------------------------------- |
| `evaluate_text_quality`                              | `TextQualityMetrics`       | `rag_text_quality/text_quality_metrics.py`   |
| `evaluate_citation_quality`                          | `CitationQualityEvaluator` | `rag_text_quality/citation_quality.py`       |
| `check_consistency` / `check_consistency_detailed` | `ConsistencyChecker`       | `cascade_consistency/consistency_checker.py` |

---

### 3.7 `framework/parallel.py` — 并行调度器

#### 类接口

```python
class ParallelExperimentScheduler:
    def __init__(self, config: ExperimentConfig, max_parallel: int = 2)

    async def run_experiments_parallel(self, runners: List) -> List
    async def run_sequential(self, runners: List) -> List
```

#### 并行安全保证

| 隔离维度             | 机制               | 说明                                               |
| -------------------- | ------------------ | -------------------------------------------------- |
| SQLite 并发读        | WAL 模式           | 已在 `database/operations.py` 启用               |
| SQLite 并发写        | WAL 模式           | 不同 session_id 写入不同行，无锁冲突               |
| SSE 事件             | 按 session_id 分桶 | `sse_manager.subscribe(session_id)` 返回独立队列 |
| LangGraph checkpoint | 按 thread_id 隔离  | `thread_id = session_id`，不同 session 天然隔离  |
| LLM API              | 全局 Semaphore(3)  | `LLM_SEMAPHORE` 限制总并发 ≤ 3                  |

#### 并行执行流程

```
run_experiments_parallel([runner1, runner2, runner3])
  │
  ├─ semaphore = asyncio.Semaphore(max_parallel)
  │
  ├─ tasks = [
  │     _run_with_semaphore(runner1),  # 获取信号量 → runner1.run()
  │     _run_with_semaphore(runner2),  # 获取信号量 → runner2.run()
  │     _run_with_semaphore(runner3),  # 等待信号量 → ...
  │   ]
  │
  └─ results = await asyncio.gather(*tasks, return_exceptions=True)
      # 任一 runner 异常不影响其他 runner
```

---

## 四、实验运行器设计

### 4.1 级联一致性实验 — `CascadeRunner`

#### 实验原理

当用户对某个维度报告提出驳回反馈时，规划智能体需要：

1. 修订目标维度报告以响应反馈
2. 自动级联修订受影响的下游维度
3. 保持上下游维度间的语义一致性

#### 类定义

```python
class CascadeRunner(ExperimentRunner):
    def __init__(self, config: ExperimentConfig, scenario: CascadeScenario, run_index: int = 0)
    async def run(self) -> Dict[str, Any]
    async def _ensure_baseline(self) -> Dict[str, str]
    async def _run_cascade_revision(self, session_id, baseline_reports, scenario) -> Dict[str, str]
    def _check_all_consistency(self, baseline, revised, scenario) -> Dict[str, Any]
```

#### 执行流程

```
CascadeRunner.run()
  │
  ├─ 1. _ensure_baseline()
  │     ├─ 查 baseline_reports.json 文件 → 命中则返回
  │     ├─ 查 ExperimentCache("baseline", "jintian") → 命中则返回
  │     └─ 调用 run_planning_graph() 生成新基线
  │         → save_baseline() 保存
  │         → cache.save_reports() 缓存
  │
  ├─ 2. _run_cascade_revision(session_id, baseline_reports, scenario)
  │     ├─ PlanningRuntimeService.build_initial_state(...)
  │     ├─ 注入反馈到 initial_state:
  │     │     initial_state["feedback_history"].append({
  │     │         "dimension": scenario.target_dimension,
  │     │         "layer": scenario.target_layer,
  │     │         "feedback": scenario.feedback,
  │     │     })
  │     │     initial_state["revision_mode"] = True
  │     │     initial_state["revision_target"] = {...}
  │     ├─ SSE 初始化 + InProcessEventListener
  │     ├─ 启动规划执行（从 target_layer 开始）
  │     ├─ 等待 L{target_layer} → L3 完成
  │     └─ data_accessor.get_reports(session_id) 获取修订后报告
  │
  ├─ 3. _check_all_consistency(baseline, revised, scenario)
  │     for dim_key, keywords in scenario.keywords.items():
  │         metrics.check_consistency_detailed(
  │             baseline[dim_key], revised[dim_key],
  │             scenario.feedback, {dim_key: keywords}
  │         )
  │
  └─ 4. 保存结果
        → cascade_result.json
        → revised_reports.json
```

#### 一致性检验方法

`ConsistencyChecker` 提供三种检验：

| 方法                           | 权重     | 说明                                                            |
| ------------------------------ | -------- | --------------------------------------------------------------- |
| `check_feedback_response()`  | 目标维度 | 正向关键词覆盖率(50%) + 负向关键词清除率(30%) + 内容变化度(20%) |
| `check_semantic_alignment()` | 下游维度 | Embedding 语义相似度(70%) + 关键词对齐度(30%)                   |
| `check_keyword_coverage()`   | 补充     | 期望关键词覆盖率 × (1 - 禁止关键词残留率)                      |

Embedding 使用阿里云 `text-embedding-v4` 模型，通过校准参数将原始余弦相似度归一化到 [0, 1]：

```
normalized = max(0, (cosine_sim - offset) / scale)
# 默认: offset=0.3, scale=0.7
# 自动校准: 基于预设样本对的中位数
```

---

### 4.2 RAG 文本质量实验 — `RAGQualityRunner`

#### 实验原理

2×2 干净对照设计，通过控制 RAG 检索的层级开关，隔离 RAG 对文本质量的净贡献：

| 组 | L1 RAG | L2 RAG | L3 RAG | 对比意义                |
| -- | ------ | ------ | ------ | ----------------------- |
| g1 | off    | off    | off    | 纯 LLM 能力基线         |
| g2 | off    | off    | on     | L3 RAG 净增益 = g2 - g1 |
| g3 | on     | on     | on     | 实际应用效果            |

#### 类定义

```python
class RAGQualityRunner(ExperimentRunner):
    def __init__(self, config: ExperimentConfig, group_name: str, iteration: int = 0)
    async def run(self) -> Dict[str, Any]
    async def _get_reports(self, session_id) -> tuple[Dict[str, str], bool]
    async def _evaluate_metrics(self, reports) -> Dict[str, Any]
    def _get_kb_context(self, dim_key, content) -> str
```

#### 执行流程

```
RAGQualityRunner.run()
  │
  ├─ 1. _get_reports(session_id)
  │     ├─ 查 ExperimentCache("rag", "{group}_iter{N}") → 命中则返回
  │     └─ 调用 run_planning_graph(session_id, rag_config=self._rag_config)
  │         → cache.save() 缓存报告 + RAG 知识
  │
  ├─ 2. _evaluate_metrics(reports)
  │     for dim_key in L1_dims + L3_dims:
  │         ├─ Faithfulness: metrics.evaluate_text_quality(content, kb_context, dim_key)
  │         │   kb_context = 实际 RAG 注入的知识片段 (优先)
  │         │             或 content[:500] (回退)
  │         └─ Citation: metrics.evaluate_citation_quality(content, dim_key)
  │
  └─ 3. 保存结果
        → rag_result.json (含 metrics.dimensions + metrics.summary)
        → reports.json
        → 规划文本 (MD + JSON)
```

#### 评估指标

| 指标                   | 计算方法                                                                                    | 范围   |
| ---------------------- | ------------------------------------------------------------------------------------------- | ------ |
| **Faithfulness** | 可被检索上下文支持的原子陈述比例                                                            | [0, 1] |
| **内容深度**     | 规则评分：数值指标(1分) + 法规引用(0.5分) + 标准编号(0.5分) + 技术方法(1分) + 具体建议(1分) | [1, 5] |
| **引用存在率**   | KB 中存在的引用数 / 总引用数                                                                | [0, 1] |
| **引用准确率**   | 准确性评分 ≥ 70 的引用数 / 总引用数                                                        | [0, 1] |
| **支持性引用率** | 支撑关键论点的引用数 / 总引用数                                                             | [0, 1] |

#### Faithfulness 计算细节

1. **原子陈述提取**：按句号/换行分割，筛选包含数字指标、法规引用、规范性关键词（应/须/必须/不得/禁止/规定/要求/标准）的句子
2. **支持性检查**：逐句检查陈述中的数字、法规名、标准编号是否出现在检索上下文中
3. **评分**：`supported_claims / total_claims`

---

## 五、SSE 事件监听机制

### 5.1 双模式监听器

| 模式     | 类                         | 连接方式                                | 适用场景         |
| -------- | -------------------------- | --------------------------------------- | ---------------- |
| 进程内   | `InProcessEventListener` | 直接读取 `sse_manager` 内部队列       | 实验脚本（推荐） |
| HTTP SSE | `SSEEventListener`       | HTTP 连接 `/api/sessions/{id}/stream` | 外部客户端       |

### 5.2 事件类型

| 事件                   | 说明             | 实验用途           |
| ---------------------- | ---------------- | ------------------ |
| `layer_completed`    | 某层所有维度完成 | 等待 L1/L2/L3 完成 |
| `dimension_complete` | 单维度完成       | 细粒度进度监控     |
| `rag_result`         | RAG 检索结果     | 提取实际注入的知识 |
| `checkpoint_saved`   | 检查点保存       | 级联修订完成信号   |
| `error`              | 执行错误         | 错误检测与中断     |
| `completed`          | 整体完成         | 全流程结束信号     |

### 5.3 事件等待机制

```python
# 等待单层完成
await listener.wait_for_any_event(
    event_types=[EVENT_LAYER_COMPLETED, EVENT_ERROR],
    timeout=900,
    filter_func=lambda e: e.get("type") == "error" or e.get("data", {}).get("layer") == target_layer
)

# 等待所有层完成
for layer in [1, 2, 3]:
    await listener.wait_for_layer_completion(layer, timeout=900)
```

### 5.4 事件收集器

`SSEEventCollector` 注册通配符处理器 `"*"`，收集所有事件，支持按类型和层级过滤：

```python
collector = SSEEventCollector(listener)
# ... 运行实验 ...
rag_events = collector.get_events_by_type("rag_result")
layer_events = collector.get_layer_events()  # {1: [...], 2: [...], 3: [...]}
```

---

## 六、统一 CLI 设计

### 6.1 命令结构

```
python scripts/experiments/run.py <command> [options]
```

| 命令         | 说明              | 关键参数                                                       |
| ------------ | ----------------- | -------------------------------------------------------------- |
| `baseline` | 生成基线报告      | `--output-dir`                                               |
| `cascade`  | 级联修订实验      | `--scenario`, `--runs`, `--no-cache`                     |
| `rag`      | RAG 质量实验      | `--groups`, `--iterations`, `--parallel`, `--no-cache` |
| `export`   | 导出 session 数据 | `--session-id`, `--output-dir`, `--project-name`         |

### 6.2 典型用法

```bash
# 1. 生成基线（首次运行必须）
python scripts/experiments/run.py baseline

# 2. 级联实验：场景1，3轮
python scripts/experiments/run.py cascade --scenario scenario1 --runs 3

# 3. RAG 实验：3组，2轮迭代，2路并行
python scripts/experiments/run.py rag --groups g1,g2,g3 --iterations 2 --parallel 2

# 4. RAG 实验：仅运行 g2，禁用缓存
python scripts/experiments/run.py rag --groups g2 --no-cache

# 5. 导出指定 session 的完整数据
python scripts/experiments/run.py export --session-id abc123 --output-dir output/export/abc123
```

### 6.3 命令实现

| 命令         | 实现函数           | 核心逻辑                                                                                           |
| ------------ | ------------------ | -------------------------------------------------------------------------------------------------- |
| `baseline` | `cmd_baseline()` | 创建 `CascadeRunner` + dummy scenario → `_ensure_baseline()`                                  |
| `cascade`  | `cmd_cascade()`  | 循环 `args.runs` 次，每次创建 `CascadeRunner(config, scenario, run_index)` → `runner.run()` |
| `rag`      | `cmd_rag()`      | 若 `parallel > 1`：`ParallelExperimentScheduler.run_experiments_parallel()`；否则逐组串行      |
| `export`   | `cmd_export()`   | `ResultExporter.export_session()`                                                                |

---

## 七、数据流图

### 7.1 级联实验数据流

```
                    ┌─────────────────────┐
                    │   baseline_reports   │
                    │   .json (缓存/DB)   │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │ scenario1  │  │ scenario2  │  │ scenario3  │
     │ L1: goals  │  │ L1: pop    │  │ L2: industry│
     └──────┬─────┘  └──────┬─────┘  └──────┬─────┘
            │               │               │
            ▼               ▼               ▼
     ┌──────────────────────────────────────────┐
     │  _run_cascade_revision()                 │
     │  1. build_initial_state() + 注入反馈     │
     │  2. SSE 监听 → 等待 L{target}→L3 完成   │
     │  3. data_accessor.get_reports()          │
     └──────────────────┬───────────────────────┘
                        │
                        ▼
     ┌──────────────────────────────────────────┐
     │  _check_all_consistency()                │
     │  for each dim in scenario.keywords:      │
     │    check_consistency_detailed(           │
     │      baseline[dim], revised[dim],        │
     │      feedback, keywords                  │
     │    )                                    │
     └──────────────────┬───────────────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │ cascade_result  │
              │ .json           │
              └─────────────────┘
```

### 7.2 RAG 实验数据流

```
     ┌─────────────────────────────────────────────┐
     │  ParallelExperimentScheduler (可选)          │
     │  max_parallel = N                           │
     └──────────┬──────────┬──────────┬────────────┘
                │          │          │
                ▼          ▼          ▼
     ┌──────┐  ┌──────┐  ┌──────┐
     │  g1  │  │  g2  │  │  g3  │
     │全关  │  │L3开  │  │全开  │
     └──┬───┘  └──┬───┘  └──┬───┘
        │         │         │
        ▼         ▼         ▼
     ┌──────────────────────────────┐
     │  run_planning_graph(         │
     │    rag_config={L1:bool,      │
     │               L2:bool,       │
     │               L3:bool}       │
     │  )                           │
     │  → {dim_key: content}        │
     └──────────────┬───────────────┘
                    │
                    ▼
     ┌──────────────────────────────┐
     │  _evaluate_metrics(reports)  │
     │  for dim in L1_dims+L3_dims: │
     │    ├─ Faithfulness(content,  │
     │    │     kb_context)         │
     │    └─ Citation(content)      │
     └──────────────┬───────────────┘
                    │
                    ▼
     ┌──────────────────────────────┐
     │  rag_result.json             │
     │  ├─ metrics.dimensions       │
     │  └─ metrics.summary          │
     │     avg_faithfulness         │
     │     avg_depth                │
     │     total_citations          │
     └──────────────────────────────┘
```

---

## 八、维度体系

### 8.1 三层维度分布

| 层级                  | 维度数 | 维度列表                                                                                                                                                                                           |
| --------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **L1 现状分析** | 12     | location, socio_economic, villager_wishes, superior_planning, natural_environment, land_use, traffic, public_services, infrastructure, ecological_green, architecture, historical_culture          |
| **L2 规划定位** | 4      | resource_endowment, planning_positioning, development_goals, planning_strategies                                                                                                                   |
| **L3 规划编制** | 12     | industry, spatial_structure, land_use_planning, settlement_planning, traffic_planning, public_service, infrastructure_planning, ecological, disaster_prevention, heritage, landscape, project_bank |

### 8.2 级联影响方向

```
L1 (现状分析) ──→ L2 (规划定位) ──→ L3 (规划编制)

例: natural_environment (L1)
  → resource_endowment (L2)
    → industry (L3)
  → spatial_structure (L2)
    → land_use_planning (L3)
  → ecological (L3)
  → disaster_prevention (L3)
```

---

## 九、输出文件规范

### 9.1 级联实验输出

```
output/experiments/cascade_{scenario}/
├── baseline/
│   ├── baseline_reports.json       # 基线报告
│   └── *.md / *.json              # 规划文本
├── scenario1/
│   ├── run0/
│   │   ├── cascade_result.json    # 实验结果
│   │   └── revised_reports.json   # 修订后报告
│   └── run1/
│       ├── cascade_result.json
│       └── revised_reports.json
└── cache/
    └── baseline_jintian_run0.json # 缓存
```

### 9.2 RAG 实验输出

```
output/experiments/rag_quality/
├── g1/
│   ├── iter0/
│   │   ├── rag_result.json        # 评估结果
│   │   ├── reports.json           # 维度报告
│   │   └── *.md / *.json          # 规划文本
│   └── iter1/
│       └── ...
├── g2/
│   └── ...
├── g3/
│   └── ...
└── cache/
    └── rag_g1_iter0_run0.json    # 缓存
```

### 9.3 结果 JSON 格式

**cascade_result.json**:

```json
{
  "scenario": "scenario1",
  "session_id": "cascade_scenario1_run0_abc12345",
  "target_dimension": "development_goals",
  "target_layer": 1,
  "consistency": {
    "development_goals": {"score": 0.85, "keyword_coverage": 0.8, ...},
    "industry_planning": {"score": 0.72, "embedding_similarity": 0.68, ...}
  },
  "overall_consistency": 0.78
}
```

**rag_result.json**:

```json
{
  "group_name": "g3",
  "iteration": 0,
  "session_id": "rag_g3_iter0_def67890",
  "rag_config": {"1": true, "2": true, "3": true},
  "from_cache": false,
  "metrics": {
    "dimensions": {
      "industry": {
        "text_length": 3200,
        "faithfulness": 0.85,
        "depth_score": 4.2,
        "total_citations": 5,
        "existence_rate": 0.8,
        "supportive_rate": 0.6
      }
    },
    "summary": {
      "avg_faithfulness": 0.78,
      "avg_depth": 3.8,
      "total_citations": 42
    }
  }
}
```

---

## 十、并行运行可行性

### 10.1 验证清单

| 项目            | 验证方法                                             | 预期结果         |
| --------------- | ---------------------------------------------------- | ---------------- |
| SQLite 并发读   | 同时启动 2 个 session 读取报告                       | 无锁等待         |
| SQLite 并发写   | 2 个 session 同时写入 dimension_reports              | WAL 模式无冲突   |
| SSE 分桶隔离    | 2 个 session 并行，各收到自己的 layer_completed 事件 | 事件不交叉       |
| checkpoint 隔离 | 2 个 session 并行写入 checkpoints                    | thread_id 不冲突 |
| LLM 限流        | 2 个 session 并行，Semaphore(3)                      | 总并发 ≤ 3      |
| 数据库复用      | 从已有 56 行报告直接读取                             | 无需重新生成     |

### 10.2 并行运行示例

```bash
# 2路并行运行 g1+g2+g3
python scripts/experiments/run.py rag --groups g1,g2,g3 --iterations 2 --parallel 2

# 时序：
# t0: [g1_iter0, g2_iter0] 同时启动（g3_iter0 等待信号量）
# t1: g1_iter0 完成 → g3_iter0 获取信号量启动
# t2: g2_iter0 完成 → g1_iter1 获取信号量启动
# ...
```

### 10.3 限制

- **LLM API 限流**：全局 `asyncio.Semaphore(3)` 控制总并发，即使 `max_parallel=4`，同时执行的 LLM 调用也不超过 3 个
- **内存**：每个并行 session 独立持有 LangGraph StateGraph 实例，内存占用与并行数成正比
- **超时**：每层等待超时 900 秒（15 分钟），3 层总计最多 45 分钟

---

## 十一、与旧代码的对应关系

| 旧文件                                        | 新文件                                                          | 变化                                        |
| --------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------- |
| `config.py`                                 | `framework/config.py`                                         | 合并为 dataclass，保留所有常量              |
| `dependencies.py`                           | `framework/config.py`                                         | 依赖注入合入配置                            |
| `export_baseline.py`                        | `framework/exporter.py`                                       | 功能扩展，支持 RAG 知识导出                 |
| `cascade_consistency/run_baseline.py`       | `framework/runner.py` → `CascadeRunner._ensure_baseline()` | 基线生成逻辑合入基类                        |
| `cascade_consistency/run_experiment.py`     | `cascade/runner.py`                                           | 继承 ExperimentRunner，保留 fork + 级联逻辑 |
| `rag_text_quality/run_4group_experiment.py` | `rag_quality/runner.py`                                       | 继承 ExperimentRunner，单组运行 + 并行调度  |
| `sse_listener.py`                           | 不变                                                            | 两种实验共享                                |
| `consistency_checker.py`                    | 不变                                                            | 被 `framework/metrics.py` 懒加载引用      |
| `text_quality_metrics.py`                   | 不变                                                            | 被 `framework/metrics.py` 懒加载引用      |
| `citation_quality.py`                       | 不变                                                            | 被 `framework/metrics.py` 懒加载引用      |
| `statistical_analysis.py`                   | 不变                                                            | RAG 组间对比分析                            |
| `oracle_knowledge.py`                       | 不变                                                            | G4 Oracle 知识（暂未集成）                  |

---

## 十二、关键依赖

| 依赖                         | 用途                 | 位置                                                               |
| ---------------------------- | -------------------- | ------------------------------------------------------------------ |
| `PlanningRuntimeService`   | LangGraph 规划图执行 | `backend/app/services/runtime.py`                                |
| `ReportStore`              | 维度报告数据库 CRUD  | `backend/app/services/report_store.py`                           |
| `sse_manager`              | SSE 事件分发         | `backend/app/services/sse.py`                                    |
| `PlanningTextGenerator`    | 规划文本生成         | `backend/app/services/modules/planning_text/`                    |
| `InProcessEventListener`   | 进程内 SSE 监听      | `scripts/experiments/sse_listener.py`                            |
| `ConsistencyChecker`       | 一致性检验           | `scripts/experiments/cascade_consistency/consistency_checker.py` |
| `TextQualityMetrics`       | 文本质量评估         | `scripts/experiments/rag_text_quality/text_quality_metrics.py`   |
| `CitationQualityEvaluator` | 引用质量评估         | `scripts/experiments/rag_text_quality/citation_quality.py`       |
| `AliyunEmbeddings`         | Embedding 向量生成   | `backend/app/services/modules/rag/vector_store.py`               |
