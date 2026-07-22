# GIS 村庄规划系统 — 文档索引

> **文档根目录**: `docs/gis/`
> **项目**: Village Planning Agent — GIS Layout Engine (Trinity 架构)
> **更新**: 2026-07-22

## 文档导航

### 状态图例

| 标记 | 含义 |
|------|------|
| `[CURRENT]` | 描述当前实际实现的设计文档 |
| `[DIAGNOSTIC]` | 诊断/评估报告，描述现状和问题 |
| `[PROPOSAL]` | 未来提案，尚未实现 |
| `[DEPRECATED]` | 已过时，保留作为历史参考 |

---

## 文档地图

```
docs/gis/
│
├── INDEX.md                          ← 你在这里
├── BIBLIOGRAPHY.md                   ← 统一参考文献索引
│
├── 📘 设计规范 (Design Specifications)
│   ├── 01_DESIGN_GOALS.md            [CURRENT]  权威设计规范 — Trinity架构、编码体系、技术决策
│   ├── 02_OUTPUT_ARCHITECTURE.md     [CURRENT]  输出架构规范 — 14层输出、字段定义、省标对齐
│   └── 03_DATA_SOURCE.md            [CURRENT]  数据源规范 — 金田村实测数据、GDB图层、数据版本
│
├── 🔍 诊断报告 (Diagnostics)
│   ├── diagnostics/01_PARSE_AGENT_STATUS.md     [DIAGNOSTIC] PARSE Agent当前状态与v11修复方案
│   ├── diagnostics/02_RELIABILITY_ASSESSMENT.md [DIAGNOSTIC] 可靠性评估 — 3个核心鸿沟分析
│   └── diagnostics/03_DATA_GAP_ANALYSIS.md      [DIAGNOSTIC] 数据缺口分析 — 教材要求 vs 系统现状
│
├── 💡 提案 (Proposals)
│   ├── proposals/01_PARSE_SPATIAL_ENHANCEMENT.md  [PROPOSAL] 空间理解增强提案 — SpatialContext争议
│   ├── proposals/02_GIS_PLANNING_INTEGRATION.md   [PROPOSAL] GIS工具集成提案 — 6个规划查询工具
│   └── proposals/03_TOOL_FIRST_ARCHITECTURE.md    [PROPOSAL] 架构重构提案 — Tool-First，Agent-Orchestrated
│
└── 📝 设计日志 (Design Log)
    └── design-log/01_DECISION_LOG.md              关键设计决策日志
```

---

## 推荐阅读路径

### 🆕 新人入门
1. `01_DESIGN_GOALS.md` §1-3 — 了解问题定义和Trinity架构
2. `02_OUTPUT_ARCHITECTURE.md` §0 — 了解编码体系和输出结构
3. `03_DATA_SOURCE.md` — 了解实际数据

### 🔧 深入理解
4. `01_DESIGN_GOALS.md` §4-7 — 详细技术决策
5. `02_OUTPUT_ARCHITECTURE.md` §1-6 — 逐层输出规范
6. `design-log/01_DECISION_LOG.md` — 了解决策背后的思考

### 🐛 问题诊断
- `diagnostics/01_PARSE_AGENT_STATUS.md` — 当前实现瓶颈
- `diagnostics/02_RELIABILITY_ASSESSMENT.md` — 已知鸿沟和风险
- `diagnostics/03_DATA_GAP_ANALYSIS.md` — 数据缺口根因

### 🚀 未来方向
- `proposals/03_TOOL_FIRST_ARCHITECTURE.md` — 架构重构（Tool-First，Agent-Orchestrated）
- `proposals/01_PARSE_SPATIAL_ENHANCEMENT.md` — 空间理解增强
- `proposals/02_GIS_PLANNING_INTEGRATION.md` — 规划Agent工具集成

---

## 按主题快速查找

| 主题 | 主要文档 | 相关文档 |
|------|----------|----------|
| Trinity 架构 | 01_DESIGN_GOALS §3 | design-log/01 |
| 6套编码体系 | 02_OUTPUT_ARCHITECTURE §0 | 01_DESIGN_GOALS §4 |
| 5种原子操作 | 01_DESIGN_GOALS §5 | proposals/01 |
| 14层输出 | 02_OUTPUT_ARCHITECTURE §1-6 | 03_DATA_SOURCE |
| PARSE Agent | diagnostics/01 | proposals/01 |
| 空间锚定问题 | diagnostics/02 §三 | proposals/01 |
| 数据缺口 | diagnostics/03 | 02_OUTPUT_ARCHITECTURE §4 |
| MIP 优化器 | 01_DESIGN_GOALS §7 | diagnostics/02 |
| 合规检查 | 02_OUTPUT_ARCHITECTURE §8 | proposals/02 |
| 架构重构 | proposals/03 | 01_DESIGN_GOALS §3.7, §8 |
| EXECUTE_OPS Agent | proposals/03 §4 | 01_DESIGN_GOALS §3.3 |
| Tool-First 架构 | proposals/03 §2-3 | 01_DESIGN_GOALS §5 |

---

## 版本历史

| 日期 | 变更 |
|------|------|
| 2026-07-22 | 新增 proposals/03 Tool-First 架构重构提案；01_DESIGN_GOALS §3.7/§5/§8 标注实现差距 |
| 2026-07-22 | 文档重组：分离设计/诊断/提案，添加状态标注，统一参考文献 |
| 2026-07-21 | DESIGN_GOALS v5.1, OUTPUT_ARCHITECTURE v3.4 |
