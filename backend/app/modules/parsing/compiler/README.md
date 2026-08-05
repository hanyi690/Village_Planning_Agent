# Parsing Compiler — 共享编译内核

> **定位**：把维度报告（L1 现状 / L2 策略 / L3 项目 / REVISION）**编译为类型化阶段 fragment** 的共享内核。`agent/parse` 顶层是包住此内核的薄 LangGraph 包装。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：
- profile 分派：`compile_dimension_report(dimension_key, profile, ...)` 按 `CompilationProfile` 选择编译策略
- 诊断收集：确定性检测解析质量问题（`collect_diagnostics` → `ParseDiagnostic`）
- `【INSTRUCTION】` 段切分（`split_content_instruction`）
- fragment 溯源构建（`build_fragment_provenance` → `Provenance`）
- L3 → 空间参考 DSL 的确定性映射（`spec_mapper`：`PlanningIntervention -> SpatialReferenceSpec`，零 LLM / 零 KG / 零几何）

**不负责**：
- 不做 LLM 调用（编译是确定性的）
- 不做任何空间计算
- 不承载 agent 编排（编排在 `agent/parse`）

---

## 输入/输出契约

**入口**：`compiler/__init__.py` 导出 `compile_dimension_report` + `CompilationProfile`。

**输出 fragment**（按 profile，契约见 `schema/contracts/`）：`L1DimensionFragment` / `L2StrategyFragment` / `L3ProgramFragment`。

**文件清单**：

| 文件 | 职责 |
|---|---|
| `core.py` | profile 分派核心（Wave B L1 / Wave D L2 / Wave E L3 / Wave F REVISION） |
| `diagnostics.py` | 确定性解析质量诊断（章节缺失 / 表格问题 → `ParseDiagnostic`） |
| `instruction_parser.py` | `【INSTRUCTION】` 段解析（包装 `parsing.tables` 结构表提取） |
| `provenance.py` | fragment 溯源构建（`source_module` 默认 `l1_observe`） |
| `spec_mapper.py` | `PlanningIntervention -> SpatialReferenceSpec` 确定性映射（方向提示从 `spatial_requirements` 提取） |

---

## 依赖方向

```
compiler/ → schema/contracts（l1/l2/l3、parse_result、parsing、provenance、spatial_reference、classification_ref）
          → modules/parsing（tables、spatial_language）
   ▲ 被 agent/parse 与 profiles/ 消费
```

- 允许：`schema/contracts`、`modules/parsing` 内部、`app.utils`
- 禁止：`agent` / `services` / `api` / `tools`；禁止空间计算

---

## 禁止行为

- 在 compiler 内做 LLM 调用 / KG 查询 / 几何计算（必须是确定性管线）
- 让 compiler 推导规划用途/分区/点位（roadmap 约束：只携带报告已声明内容）
- 绕过 `CompilationProfile` 枚举直接硬编码分支
- 新 profile 不复用 `core.py` 分派而另起编译入口
