# GIS 村庄规划系统 - 文档索引

> **文档根目录**: `docs/gis/`
> **项目**: Village Planning Agent - 智能化乡村规划系统
> **更新**: 2026-07-23

## 文档导航

### 状态图例

| 标记 | 含义 |
|------|------|
| `[CURRENT]` | 描述当前实际实现的设计文档 |
| `[DIAGNOSTIC]` | 诊断/评估报告，描述现状和问题 |
| `[PROPOSAL]` | 未来提案，尚未实现 |
| `[IMPLEMENTING]` | 实施中 - 部分阶段已完成 |
| `[DEPRECATED]` | 已过时，保留作为历史参考 |

---

## 文档地图

```
docs/gis/
│
├── INDEX.md                          ← 你在这里
├── BIBLIOGRAPHY.md                   ← 统一参考文献索引
│
├── 🌟 系统愿景 (Vision)
│   └── 00_PLANNING_SYSTEM_VISION.md     [CURRENT] 北极星 v2.0 — 初期目标(Plan-then-Execute) + 终极目标(闭环 ANALYZE/PLAN/DELIVER)
│
├── 📘 设计规范 (Design Specifications)
│   ├── 01_DESIGN_GOALS.md            [CURRENT] Trinity架构、编码体系、技术决策（v6.0 对齐愿景）
│   ├── 02_OUTPUT_ARCHITECTURE.md     [CURRENT] 输出架构 — 14层数据底座 -> 一图一表一规则+库（v3.5）
│   ├── 03_DATA_SOURCE.md            [CURRENT] 数据源 — 金田村实测数据、GDB图层、数据版本
│   └── 04_DATA_ACQUISITION_PLAN.md  [CURRENT] 数据获取计划 — 全国+广东平台→Schema全覆盖+扩展需求
│
├── 📚 参考资料 (Reference)
│   ├── reference/HUMAN_PLANNING_WORKFLOW.md  [CURRENT] 人类规划产出方式 — 工作流/成果/汇交/分析方法/空间定位方法论
│   └── reference/EXA_FINDINGS.md             [CURRENT] Exa 搜索发现 — 外部可行性验证（6篇论文 + 3个技术决策）
│
├── 🔍 诊断报告 (Diagnostics)
│   ├── diagnostics/01_PARSE_AGENT_STATUS.md     [DIAGNOSTIC] PARSE Agent当前状态与v11修复方案
│   ├── diagnostics/02_RELIABILITY_ASSESSMENT.md [DIAGNOSTIC] 可靠性评估 - 3个核心鸿沟分析
│   ├── diagnostics/03_DATA_GAP_ANALYSIS.md      [DIAGNOSTIC] 数据缺口分析 - 教材要求 vs 系统现状
│   └── diagnostics/04_PROFESSIONAL_PARADIGM_GAPS.md [DIAGNOSTIC] 专业范式缺口分析
│
├── 💡 提案 (Proposals)
│   ├── proposals/01_PARSE_SPATIAL_ENHANCEMENT.md  [PROPOSAL] 空间理解增强提案 - SpatialContext争议
│   ├── proposals/02_GIS_PLANNING_INTEGRATION.md   [PROPOSAL] GIS工具集成提案 - 6个规划查询工具
│   ├── proposals/03_TOOL_FIRST_ARCHITECTURE.md    [IMPLEMENTING] 架构重构提案 - Phase A/B/C ✅, D/E ⬜
│   └── proposals/04_MULTI_SOURCE_DATA_ARCHITECTURE.md [CURRENT] 多源GIS数据管理架构 - P0/P1/P2 全部驱动已实现 (5 drivers + catalog + yaml)
│
└── 📝 设计日志 (Design Log)
    └── design-log/01_DECISION_LOG.md              关键设计决策日志
```

---

## 推荐阅读路径

### 🆕 新人入门
1. `00_PLANNING_SYSTEM_VISION.md` §0 — 先读初期 vs 终极目标，理解当前推进方向
2. `reference/EXA_FINDINGS.md` — 外部可行性验证（Plan-then-Execute 是 SOTA）
3. `01_DESIGN_GOALS.md` §1-3 — 问题定义与 Trinity 架构
4. `02_OUTPUT_ARCHITECTURE.md` §0 — 编码体系与输出结构
5. `reference/HUMAN_PLANNING_WORKFLOW.md` §1-4 — 人类规划师怎么做，系统对标什么
6. `04_DATA_ACQUISITION_PLAN.md` — 数据获取路线图：需要哪些数据集、对应哪些 Schema 类型

### 🔧 深入理解
6. `00_PLANNING_SYSTEM_VISION.md` §4-7 — 目标架构、闭环范式、路线图
7. `reference/HUMAN_PLANNING_WORKFLOW.md` §5-5.5 — 空间定位与地名解析方法论
8. `01_DESIGN_GOALS.md` §4-7 — 编码体系、工具流水线、技术决策
9. `02_OUTPUT_ARCHITECTURE.md` §1-6 — 逐层输出规范
10. `design-log/01_DECISION_LOG.md` — 决策背后的思考

### 🐛 问题诊断
- `diagnostics/01_PARSE_AGENT_STATUS.md` - 当前实现瓶颈
- `diagnostics/02_RELIABILITY_ASSESSMENT.md` - 已知鸿沟和风险
- `diagnostics/03_DATA_GAP_ANALYSIS.md` - 数据缺口根因
- `diagnostics/04_PROFESSIONAL_PARADIGM_GAPS.md` - 专业范式缺口（G1-G8, K1-K6）

### 🚀 实现路线
- `00_PLANNING_SYSTEM_VISION.md` §7 - Phase R0-R4 重排路线图（闭环→分析→落地→成果→质量）
- `proposals/03_TOOL_FIRST_ARCHITECTURE.md` - 架构重构（Phase A/B/C ✅，D/E ⬜）
- `01_DESIGN_GOALS.md` §3.7 - 当前代码位置（Tool-First 结构）

---

## 按主题快速查找

| 主题 | 主要文档 | 相关文档 |
|------|----------|----------|
| **系统北极星** | 00_PLANNING_SYSTEM_VISION | reference/EXA_FINDINGS |
| **初期目标 (Plan-then-Execute)** | 00 §0.1, §7 | reference/EXA_FINDINGS §2-5 |
| **文本↔空间闭环** | 00 §3.1, §5 | 01 §3.2 |
| **三阶段模型 ANALYZE/PLAN/DELIVER** | 00 §2 | reference §1-5 |
| **栅格/DEM/双评价分析** | 00 §3.2, §7 Phase R1 | reference §5, 02 §1.2.1 |
| **人类规划工作流** | reference/HUMAN_PLANNING_WORKFLOW | 00 §2 |
| **一图一表一规则+库** | 00 §3.3, reference §3-4 | 02 §二, §6 |
| Trinity 架构 | 01 §3 | design-log/01 |
| 6套编码体系 | 02 §0 | 01 §4 |
| 5种原子操作 | 01 §3.4, §5 | proposals/01 |
| 14层输出 | 02 §二 | 03_DATA_SOURCE |
| 管制规则（一规则） | reference §3.3 | 02 §6.2, diagnostics/04 G5 |
| 数据库汇交（5目录+4图层） | reference §4 | 02 附录A |
| 8条质量硬约束 | reference §4.3 | 02 §5 |
| PARSE Agent | diagnostics/01 | proposals/01 |
| 空间锚定 / 空间定位 | reference/HUMAN_PLANNING_WORKFLOW §5.5 | diagnostics/02 §三, reference/EXA_FINDINGS §4 |
| 数据缺口 | diagnostics/03 | 02 §1.2.1 |
| 数据获取计划 | 04_DATA_ACQUISITION_PLAN | diagnostics/03, 03_DATA_SOURCE |
| 多源数据管理 | proposals/04 | 04_DATA_ACQUISITION_PLAN, tiles.py, gd_service.py |
| MIP 优化器 | 01 §6, §7 | diagnostics/02 |
| 架构重构 (Tool-First) | proposals/03 (A/B/C ✅) | 01 §3.7 |
| EXECUTE_OPS Agent | 01 §3.4 | agent/gis/execute/ (空壳) |
| 路线图（重排） | 00 §7 | 01 §8 |

---

## 文档间的权威关系

```
00_PLANNING_SYSTEM_VISION.md   ← 北极星，冲突时以此为准
    ↓ 指导
01_DESIGN_GOALS.md             ← 技术设计规范
02_OUTPUT_ARCHITECTURE.md      ← 输出规范
    ↓ 对标
reference/HUMAN_PLANNING_WORKFLOW.md  ← 人类规划产出方式基线
    ↓ 诊断
diagnostics/*                  ← 现状与差距
    ↓ 推进
proposals/*                    ← 实施提案
```

> **重要**：`00_PLANNING_SYSTEM_VISION.md` 是 v6.0 新增的北极星文档。它重新定义系统为
> "文本与空间闭环的智能化规划系统"，三阶段 ANALYZE/PLAN/DELIVER。`01_DESIGN_GOALS §3.4`
> 的"操作执行引擎/绘图员"据此降格为 PLAN 阶段的一种落地机制，不再是系统全貌。

---

## 版本历史

| 日期 | 变更 |
|------|------|
| 2026-07-24 | **P0/P1/P2 全部驱动实现**：5个驱动 (`file_vector`, `tianditu_vector`, `tianditu_tile`, `local_raster`, `remote_raster`) + `catalog/catalog.py` (DataCatalog + 路径解析) + `catalog/config.py` (Pydantic) + `catalog/sources.yaml` (23 sources) + `scripts/test_data_drivers.py` (validation) |
| 2026-07-24 | 新增 `proposals/04_MULTI_SOURCE_DATA_ARCHITECTURE.md` — 多源GIS数据管理架构设计（矢量+栅格双轨驱动，DriverRegistry装饰器注册，YAML声明式配置） |
| 2026-07-24 | 新增 `04_DATA_ACQUISITION_PLAN.md` — 全国+广东平台数据集→Schema全覆盖分析，7个新建类型+1个扩展类型 |
| 2026-07-23 | **v2.0 初期/终极分离 + Exa 验证**：`00` 重写 v2.0（区分 Plan-then-Execute 初期目标 vs 闭环终极目标）；新增 `reference/EXA_FINDINGS.md`（6篇论文验证 Plan-then-Execute 范式）；`reference/HUMAN_PLANNING_WORKFLOW` 新增 §5.5 空间定位方法论（Gazetteer + LLM 推理）；`01` §3.4 原子操作精简；`INDEX` 更新阅读路径 |
| 2026-07-23 | **v6.0 北极星重定向**：新增 `00_PLANNING_SYSTEM_VISION.md`（系统终极目标：文本空间闭环、ANALYZE/PLAN/DELIVER、可解释汇交）；新增 `reference/HUMAN_PLANNING_WORKFLOW.md`（人类规划产出方式对标基线）；`01_DESIGN_GOALS` v6.0 对齐愿景（§1 目标、§3.4 绘图员定位、§8 路线图重排）；`02_OUTPUT_ARCHITECTURE` v3.5（14层→一图一表一规则+库，管制规则升 P0） |
| 2026-07-23 | Phase A/B/C 完成：Tool-First 架构迁移（commit 415dbf5/2006d30/c8a76d4）；proposals/03 状态更新为 [IMPLEMENTING]；01_DESIGN_GOALS §3.7/§5/§8 更新为当前结构 |
| 2026-07-22 | 新增 proposals/03 Tool-First 架构重构提案；01_DESIGN_GOALS §3.7/§5/§8 标注实现差距 |
| 2026-07-22 | 文档重组：分离设计/诊断/提案，添加状态标注，统一参考文献 |
| 2026-07-21 | DESIGN_GOALS v5.1, OUTPUT_ARCHITECTURE v3.4 |
