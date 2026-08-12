# Config 层（领域配置）

> 维度/阶段/依赖的 YAML 声明式配置。**与 `app/core/settings.py` 分工明确**：本层是"业务领域配置"（28 维度分几层、每层哪些维度、依赖与执行波次、RAG 查询词），`core/settings.py` 是"环境/运行参数配置"（API Key、限流、路径）。

---

## 一、分工边界

| 层 | 内容 | 载体 |
|----|------|------|
| `app/config/`（本层） | 规划阶段/维度定义、同层与跨层依赖、执行波次、RAG 查询词、文档类型偏好 | `phases.yaml` + Python 规则 |
| `app/core/settings.py` | 环境变量 → 模块常量（LLM/RAG/GIS/日志/路径） | `.env` + 硬编码默认值 |

修改维度/依赖 → 改 `phases.yaml`；修改运行参数 → 改 `.env`。

---

## 二、文件清单

| 模块 | 职责 |
|------|------|
| `phases.yaml` | **28 维度的唯一来源**：三个 phase（layer1/2/3）+ 每维度的 `tools`/`rag_query`/`prefer_doc_types`/`depends_on`/`layer_depends_on`/`phase_depends_on` |
| `loader.py` | YAML → `PlanningConfig`（Pydantic 校验），缓存单例 + 维度查询 API |
| `dependency.py` | 依赖计算器：Wave 波次、下游依赖、影响树、修订执行序列 |

---

## 三、配置模型（`loader.py` + `phases.yaml`）

**三阶段**（ANALYZE → PLAN → DELIVER 的 PLAN 侧）：

| phase | 名称 | 执行方式 | 维度数 |
|-------|------|----------|--------|
| `layer1` | 现状分析 | `parallel`（12 维） | 12 |
| `layer2` | 规划思路 | `wave` | 若干 |
| `layer3` | 详细规划 | `wave` | 若干 |

每个 `DimensionConfig` 字段：

| 字段 | 含义 |
|------|------|
| `key` / `name` | 维度标识 / 中文名 |
| `tools` | 该维度可用的工具列表 |
| `rag_query` | RAG 检索查询词（知识库增强） |
| `prefer_doc_types` | 偏好文档类型（policy/standard/guide/case 等） |
| `depends_on` | **同层**依赖（决定执行波次） |
| `layer_depends_on` | 跨层依赖（L2 依赖 L1，L3 依赖 L2） |
| `phase_depends_on` | 跨阶段依赖 |

**查询 API**：`get_dimension_config` / `get_dimension_layer` / `get_layer_dimensions` / `list_dimensions` / `get_analysis_dimension_names` 等，全局缓存单例（`_get_cached_config`）。

---

## 四、依赖计算器（`dependency.py`）

- **Wave 波次**：`calculate_waves(phase)` — `Wave = max(依赖维度 Wave) + 1`，无依赖为 Wave 1；`get_wave_dimensions(phase, wave)` / `get_total_waves(phase)`
- **下游依赖**：`get_downstream_dependencies`（同层）+ `get_downstream_dependencies_compat`（跨层合流，修订用）
- **影响树**：`compute_impact_tree(dimension_key)` — 迭代稳定计算修订影响波次（处理跨层依赖与基线维度，ADR-004），`get_next_revision_wave` 取下一个待执行波次
- **三层依赖链**：`get_full_dependency_chain()` 汇总所有维度 `{layer, layer_depends_on, phase_depends_on, depends_on_same_layer, wave}`
- **修订序列**：`get_revision_wave_dimensions(target, completed)` — 对多目标维度取各波次并集
- **就绪检查**：`check_detailed_dependencies_ready(dim, completed)` — L3 执行前校验跨层依赖完成

> **两套依赖 API**：`*_compat`（修订/影响树路径）基于跨层 + 同层依赖合并遍历；非 compat 版（`calculate_waves`）基于同层 `depends_on`。L1 并行由 `execution: parallel` 声明。

---

## 六、相关文档

- `app/core/README.md` — 运行参数层（`settings.py`）与 LLM/SSE/Tracing 基础设施
- `app/agent/README.md` — 主图如何消费 Wave/依赖配置执行维度
- `app/infrastructure/rag/README.md` — `rag_query` / `prefer_doc_types` 的实际消费方
