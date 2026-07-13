# GIS 布局引擎：设计文档 vs 实际实现差距分析

> **审计日期**: 2026-07-08
> **设计文档**: `docs/GIS_LAYOUT_ARCHITECTURE_V2.md` + `docs/GIS_LAYOUT_V2_PLAN.md`
> **实现基线**: `feature/gis-layout-engine` 分支

---

## 总览

| 状态 | 数量 | 占比 |
|------|------|------|
| 已实现 | 21 | 55% |
| 部分实现 | 8 | 21% |
| 缺失 | 9 | 24% |

---

## P0 — 架构级偏差

### P0-1: 三子 Agent → 单一 ReAct Agent

| | 设计 | 实现 |
|---|------|------|
| **架构** | PARSE Agent + REASON Agent + GENERATE Agent | 单一 `create_react_agent(llm, 10_tools, GISAgentState)` |
| **编排** | 每个 Agent 独立管理工具子集 | 一个 Agent 持全部 10 工具 |
| **反馈** | 显式 VALIDATOR → REASON 循环 | LLM 自行读取 ToolMessage 决定重试 |

**评估**: 合理偏离。单 Agent 更简单、LLM 调用更少，`create_react_agent` 已内建 ReAct 循环。三子 Agent 设计适用于工具数>20 的场景，当前 10 工具不需要。

**结论**: 不修复，保留现有单 Agent 架构。

---

### P0-2: 硬约束 100% 满足 → 全软约束（带松弛变量）

| | 设计 | 实现 |
|---|------|------|
| **约束类型** | 硬约束（生态红线/基本农田）+ 软约束（面积偏差） | 保护性 DLBM 硬锁定 + KG 约束 slack |
| **保证** | "所有硬约束 100% 满足" | 保护性地块已硬锁定（变量不创建），KG 约束仍用 slack |
| **代码位置** | - | `mip_allocator.py` L137-139: `continue`（跳过变量创建） |

**已修复** (2026-07-09): MIP allocator 对 `PROTECTED_DLBM_CODES` 中的地块跳过建设区变量创建（`x[i,j]` 不存在 = 固定为 0），等效硬约束。KG 约束仍用 slack，但仅影响非保护性地块的面积偏差。

**影响**: 生态红线内可能分配建设用地，永久基本农田可能被非农化。这违反规划法规。

**修复方案**:
1. MIP 中将保护性 DLBM 的地块锁定为对应分区（`x[i][construction] = 0`），而非松弛
2. `ConstraintDrivenAllocator._greedy_alloc()` 中已正确处理（保护性地块优先分配），但 MIP 路径未对齐

**状态**: ✅ 已修复（MIP 硬锁定）

---

### P0-3: PlannerAgent 类 → create_react_agent

| | 设计 | 实现 |
|---|------|------|
| **接口** | `SpatialPlanningAgent.plan(intent, reports)` | `graph.invoke(input)` |
| **类定义** | `class SpatialPlanningAgent` | `create_gis_agent_graph()` 返回 compiled graph |

**评估**: 功能等价，`create_react_agent` 是 LangGraph 1.2 官方模式，比自定义类更可靠。

**结论**: 不修复，保留现有模式。

---

### P0-4: 显式验证反馈循环 → 隐式 LLM 自行重试

| | 设计 | 实现 |
|---|------|------|
| **循环** | VALIDATOR → REASON Agent 显式反馈 | LLM 读取 validate_layout ToolMessage 后自行决定 |
| **保证** | 强制重试直到 pass | 最多重试 3 次（system prompt 中约定） |
| **失败处理** | 返回最佳结果 + 标注未满足约束 | 同（system prompt 约定） |

**评估**: 当前模式依赖 LLM 遵守 system prompt，非确定性保证。`LayoutValidator.validate_with_retry()` 存在但由工具内部调用，非 Agent 级编排。

**结论**: 不修复，当前模式可工作。如需确定性保证，可在 `layer_completion_check` 级添加显式循环。

---

## P1 — 工具/功能缺失

### P1-1: 自由 SPARQL 查询 → 仅模板查询

| | 设计 | 实现 |
|---|------|------|
| **接口** | `query_kg(sparql: str)` — LLM 输入原始 SPARQL | `query_knowledge_graph(template_name: str, ...)` — 12 个预定义模板 |
| **灵活性** | 任意查询 | 受限于模板参数 |
| **安全性** | 可能生成无效 SPARQL | 模板预验证，安全 |

**评估**: 合理偏离。LLM 生成 SPARQL 错误率高，模板模式更可靠。12 个模板覆盖了主要查询场景。

**结论**: 不修复。如需扩展，可新增模板而非开放自由 SPARQL。

---

### P1-2: 4 个工具未实现

| 设计工具 | 状态 | 替代方案 |
|----------|------|----------|
| `extract_metrics` | 缺失 | `parse_planning_text` 包含指标提取 |
| `parse_zoning_table` | 缺失 | `parse_planning_text` 包含分区表解析 |
| `check_constraint` | 缺失 | `query_knowledge_graph("get_constraint_by_field")` 可替代 |
| `detect_zone_conflict` | 缺失 | `detect_conflicts` 包含分区冲突检测 |
| `place_facility` | 缺失 | `generate_layout` 内部调用 FacilityPlacer |
| `generate_axis` | 缺失 | `generate_layout` 内部调用 AxisBuilder |

**评估**: 部分工具有等价替代。`extract_metrics` 和 `parse_zoning_table` 被合并到 `parse_planning_text`，但粒度更粗。`place_facility` 和 `generate_axis` 作为内部调用而非独立工具，LLM 无法单独调用。

**结论**: 不修复。当前工具划分已够用，拆分更细会增加 ReAct 步数。

---

### P1-3: 生态红线空间约束缺失

| | 设计 | 实现 |
|---|------|------|
| **约束** | "生态红线内禁止建设用途"（空间连接检查） | 无显式空间约束 |
| **MIP** | `x[i][construction] = 0` for parcels in ecological redline | 保护性 DLBM 优先分配但非硬锁定 |

**影响**: 生态红线区域的地块可能被 MIP 分配为建设用地（虽然概率低，因为偏好成本高）。

**修复方案**: MIP 中对 `PROTECTED_DLBM_CODES` 的地块添加硬约束 `x[i][construction_zone] = 0`。

**状态**: 待修复（与 P0-2 合并处理）

---

### P1-4: 设施点位在建设区内验证缺失

| | 设计 | 实现 |
|---|------|------|
| **约束** | "设施用地需在建设区内" | LayoutValidator 无此项检查 |
| **当前** | - | `facility_placer.py` 有 `target_zone` 参数但无验证 |

**修复方案**: LayoutValidator 添加第 9 项检查 `_check_facility_in_construction_zone`。

**状态**: 待修复

---

### P1-5: zone_generator.py 未改造

| | 设计 | 实现 |
|---|------|------|
| **计划** | DLBM 重分类 → MIP solver 调用 | 仍保留原 DLBM 重分类路径 |
| **当前** | `zone_generator.py` 554 行 | `ConstraintDrivenAllocator` 是独立模块，未替换 |

**评估**: 实际上 `generate_layout()` 同时调用了两者——`ZoneGenerator` 生成 `function_zone` 层，`ConstraintDrivenAllocator` 生成 `planning_zone` 层。两者服务不同分类体系（7 类功能区 vs 4 类规划分区），并非替代关系。

**结论**: 不修复。设计文档误判为替代关系，实际是互补关系。

---

## P2 — 验证/评估未完成

### P2-1: 端到端集成测试缺失

| | 设计 | 实现 |
|---|------|------|
| **要求** | 真实 L3 报告 + 真实 GIS 数据的 E2E 测试 | 仅有单元测试（validator 16 + layout_tools 14） |
| **覆盖** | 完整 ReAct 循环 + SSE 推送 + 前端渲染 | 无 |

**状态**: 待实现

---

### P2-2: MIP vs greedy 对比基准缺失

| | 设计 | 实现 |
|---|------|------|
| **要求** | 两种模式的面积偏差、求解时间对比 | 无基准测试 |

**状态**: 待实现

---

### P2-3: 项目覆盖率 > 80% 未验证

| | 设计 | 实现 |
|---|------|------|
| **要求** | located_projects / total_projects > 80% | 无项目覆盖率计算 |

**状态**: 待实现

---

### P2-4: 与 CAD 参考图相似度 > 60% 未实现

| | 设计 | 实现 |
|---|------|------|
| **要求** | IoU of zone boundaries > 60% | 完全未实现（无 SVG/CAD 解析和对比功能） |

**评估**: 需要参考图数字化 + IoU 计算，工作量较大。可作为长期目标。

**状态**: 远期目标

---

### P2-5: 面积偏差 < 5% 未强制

| | 设计 | 实现 |
|---|------|------|
| **要求** | Σ|actual-target|/total < 5% | MIPTrace 追踪偏差但不强制 |

**修复方案**: LayoutValidator 添加面积偏差阈值检查。

**状态**: 待修复（简单）

---

### P2-6: 变化检测率 > 5% 未强制

| | 设计 | 实现 |
|---|------|------|
| **要求** | changed_parcels / total > 5% | MIPTrace 追踪 changed_pct 但不强制 |

**评估**: 如果 MIP 目标函数包含 change_penalty，优化结果可能变化率极低（规划图=现状图）。但加权重可调。

**结论**: 不修复为强制。应在 MIP 参数调优时确保 change_penalty_weight 不会过高。

---

## P3 — 细节差异

### P3-1: 工具数量差异

| 设计 | 实现 | 差异 |
|------|------|------|
| 10 个（4 解析 + 3 推理 + 3 生成） | 12 个（4 数据 + 8 布局） | 多了 `build_knowledge_graph`、`query_knowledge_graph`、`measure_divergence`；少了 `extract_metrics`、`parse_zoning_table`、`check_constraint`、`detect_zone_conflict` |

**结论**: 不修复。实际工具划分更合理。

---

### P3-2: 几何工具数量

| 设计 | 实现 | 差异 |
|------|------|------|
| 6 个 | 4 个（merge/split/simplify/buffer） | 缺 `union_by_attribute`、`clip_to_boundary` |

**结论**: 低优先级。现有 4 个覆盖主要场景。

---

### P3-3: 验证类别超出设计

| 设计 | 实现 | 差异 |
|------|------|------|
| 5 类 | 8 类 | 多了：GeoJSON 结构验证、邻接兼容性、空间紧凑度 |

**结论**: 正向差异，不修复。

---

## 修复优先级汇总

| 优先级 | 编号 | 修复内容 | 预估工作量 |
|--------|------|----------|-----------|
| **P0** | P0-2 + P1-3 | MIP 硬约束：保护性 DLBM 地块锁定 + 生态红线禁止建设 | 0.5 天 |
| **P1** | P1-4 | 设施点位在建设区内验证 | 0.5 天 |
| **P2** | P2-5 | 面积偏差 < 5% 强制检查 | 0.1 天 |
| **P2** | P2-1 | E2E 集成测试 | 1-2 天 |
| **P2** | P2-2 | MIP vs greedy 对比基准 | 0.5 天 |
| **P2** | P2-3 | 项目覆盖率计算 | 0.5 天 |
| **远期** | P2-4 | CAD 参考图相似度 | 3+ 天 |

---

## 合理的设计偏离（不修复）

1. **单 Agent 替代三子 Agent** — 更简单，工具数不足以需要多 Agent
2. **模板查询替代自由 SPARQL** — 防止 LLM 生成无效查询
3. **Command(update=...) 替代 PlannerAgent** — LangGraph 1.2 官方模式
4. **8 验证类替代 5 类** — 超出设计，更严格
5. **12 工具替代 10 个** — 工具拆分更细，InjectedState 模式更优
6. **zone_generator 保留而非替换** — 服务 7 类功能区（与 MIP 的 4 类规划分区互补）

---

## 参考文献

- 设计文档: `docs/GIS_LAYOUT_ARCHITECTURE_V2.md` (Trinity 三层架构)
- 实施计划: `docs/GIS_LAYOUT_V2_PLAN.md` (4 Phase 实施路线)
- 架构文档: `docs/architecture/gis-system-architecture.md` (v4.0)
