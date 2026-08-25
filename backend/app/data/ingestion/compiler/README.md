# Parsing Compiler — 共享编译内核

> **定位**：把 L1 现状 / L2 策略报告编译为类型化阶段 fragment 的共享内核。L3 不进入本解析器，而由 worker 直接产出 `PlanningClaimSet`。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：
- profile 分派：`compile_dimension_report(dimension_key, profile, ...)` 仅负责 L1/L2 报告投影
- 诊断收集：确定性检测解析质量问题（`collect_diagnostics` → `ParseDiagnostic`）
- fragment 溯源构建（`build_fragment_provenance` → `Provenance`）
- 空间参考映射只由 target projection 的确定性入口调用；它不是 L3 claims 的生产路径。

**不负责**：
- 不做 LLM 调用（编译是确定性的）
- 不做任何空间计算
- 不承载 workflow 编排（编排在 bootstrap/workflow 层）

---

## 输入/输出契约

**入口**：`compiler/__init__.py` 导出 `compile_dimension_report` + `CompilationProfile`。

**输出**：L1 使用 `L1Snapshot`。L2 由 worker 直接生成
`L2DecisionSet`，不再从报告文本重建语义。

**文件清单**：

| 文件 | 职责 |
|---|---|
| `core.py` | L1/L2 profile 分派核心 |
| `diagnostics.py` | 确定性解析质量诊断（章节缺失 / 表格问题 → `ParseDiagnostic`） |
| `provenance.py` | fragment 溯源构建（`source_module` 默认 `l1_observe`） |
| `spec_mapper.py` | target projection 的确定性空间引用映射 |

---

## 依赖方向

```
compiler/ → app/contracts（l1/l2/l3、parse_result、parsing、provenance、spatial_reference、classification_ref）
          → app/data/ingestion（tables、spatial_language）
   ▲ 被 L1/L2 profiles 与 target projection domain 消费
```

- 允许：`app/contracts`、`app/data/ingestion` 内部、`app.utils`
- 禁止：`agent` / `services` / `api` / `tools`；禁止空间计算

---

## 禁止行为

- 在 compiler 内做 LLM 调用 / KG 查询 / 几何计算（必须是确定性管线）
- 让 compiler 推导规划用途/分区/点位（roadmap 约束：只携带报告已声明内容）
- 绕过 `CompilationProfile` 枚举直接硬编码分支
- 新 profile 不复用 `core.py` 分派而另起编译入口
