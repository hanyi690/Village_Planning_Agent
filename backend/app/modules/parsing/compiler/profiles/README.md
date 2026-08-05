# Compiler Profiles — 阶段专用编译策略

> **定位**：共享编译内核（`parsing/compiler/`）的**阶段化编译 profile 集合**。每个 profile 把某一层维度报告编译为对应类型化 fragment。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：按 roadmap 波次实现各阶段编译策略（`profiles/__init__.py` 导出 `compile_l1_observation` / `compile_l2_strategy` / `compile_l3_planning` / `compile_revision`）。

**不负责**：
- 不做编译内核/分派（那是 `compiler/core.py`）
- 不做 LLM 调用 / 空间计算
- 不推导报告未声明的规划内容

---

## 输入/输出契约

| profile 文件 | 输入报告 | 输出 fragment | 关键约束 |
|---|---|---|---|
| `l1_observation.py` | L1 维度报告（现状） | `L1DimensionFragment`（`ClassificationRef` / `EvidenceGap`） | 现状地类只提供分类代码与名称；禁止从现状 DLBM 自动推规划用途/分区/三生空间；只使用 same-system code→name，**不 import advisory_crosswalks** |
| `l2_strategy.py` | L2 维度报告（定位/目标/策略文本） | `L2StrategyFragment`（goals / strategies / priorities / conflicts / evidence gaps） | 禁止自动推规划用途/分区/点位 |
| `l3_planning.py` | L3 维度报告（类型化项目/意图） | `L3ProgramFragment`（interventions / dependencies / evidence gaps / program issues） | 禁止推导报告之外的规划分区/用途/点位 |
| `revision.py` | 用户结构化修订（`ParseRevisionRequest.user_revisions`） | 修订后的 `L3ProgramFragment` | 确定性 dotted-path 覆盖，无 LLM；基线由 L3_PLANNING 产出 |

**注意**：`compiler/profiles/` 与 `parsing/compiler/profiles/` 同义——本目录是 `modules/parsing/compiler/profiles/`，是共享编译内核下的唯一 profile 集合。

---

## 依赖方向

```
profiles/ → compiler/core.py（分派）、schema/contracts（l1/l2/l3、parsing、classification_ref）
   ▲ 被 agent/parse 阶段按 CompilationProfile 选择调用
```

- 允许：`compiler/`、`schema/contracts`、标准库（`re` 等）
- 禁止：`advisory_crosswalks`（L1 profile 显式禁止）、`agent` / `services` / `api` / `tools`

---

## 禁止行为

- 在 profile 内 import `advisory_crosswalks`（会把 cross-system 推导泄漏进编译，roadmap 约束）
- 让 profile 做几何 / LLM / 意图推导
- 新增 profile 不登记到 `profiles/__init__.py` 导出与 `CompilationProfile` 枚举
- 把 REVISION 覆盖逻辑混入 L3 基线编译（保持两阶段分离：先基线后修订）
