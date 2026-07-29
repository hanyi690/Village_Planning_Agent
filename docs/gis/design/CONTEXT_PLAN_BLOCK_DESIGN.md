# ContextBlock & PlanBlock 设计 v1.0

> 最后更新: 2026-07-27
> 依赖: spatial_ops 几何计算（数据边界保留）

---

## 一、定位

ContextBlock 和 PlanBlock 是为 LLM 提供结构化认知的**两个摘要层**：

| | ContextBlock | PlanBlock |
|---|---|---|
| 本质 | 现状空间认知摘要 | 增量规划操作记录 |
| 生命周期 | 不持久化（每轮计算） | 会话级（多轮 PARSE↔EXECUTE 传递） |
| 消费者 | PARSE prompt 注入 | PARSE 迭代上下文 |
| 数据来源 | spatial_ops 几何 + KG 语义聚合 | PARSE/EXECUTE 产出 |

---

## 二、ContextBlock 四修复（P1-9）

### 1. CJK token 估算修复
**文件**: `spatial_ops/context.py:compute_context_blocks`
**修改**: `len(text)//4` → CJK 感知：`cjk_count + non_cjk/4`

### 2. explore_* prompt 注入
**文件**: `parse/agent.py:explore_targets_node, explore_projects_node`
**修改**: 调用 `format_spatial_context_for_prompt(state.context_blocks)` 注入 prompt
**验证**: 之前 ContextBlock 仅在 validate_and_merge 和 resolve_place 中被消费，explore_* 提取节点完全不使用。修复后 LLM 在提取阶段即可感知空间上下文。

### 3. ConstraintZoneAnchor.overlaps_with 填充
**状态**: 待 spatial_ops 实现（需 parcel→protection 几何交集计算）
**文件**: `spatial_ops/context.py:_build_constraints`
**方案**: 用 ConstraintIndex.parcel_in_constraint(bsm) 填充每个约束面内重叠地块的 BSM 列表

### 4. 居民点聚类缓存
**状态**: 待实现
**文件**: `spatial_ops/context.py:_build_residential_clusters`
**方案**: 模块级缓存 `_clusters_cache`，`SPATIAL_RELATIONS` 复用而非重算

---

## 三、数据边界

```
spatial_ops（几何权威）:
  全几何运算（Shapely/geopandas）/ 空间索引 / 聚类 / 约束面交集
  输入: VillageBundle, 输出: 结构化结果

KG（语义权威）:
  BSM+派生属性 / 空间关系 / 语义层 / 图层组虚拟实体
  绝不存全几何

ContextBlock（组合输出）:
  几何部分 ← spatial_ops 计算（聚类/面积/重叠BSM）
  语义聚合部分 ← KG 查询（图层卡/约束简报/地类分布）
  二者组合，不重复，不跨边界
```

---

## 四、PlanBlock 设计（待实施）

### 定位
PlanBlock 是**增量式 PARSE↔EXECUTE 迭代的语义上下文载体**，
传递"本轮已决策内容"供下一轮参考。

### round_summary 三元结构
```
current_intent    - 本轮待解决的意图
decided_steps     - 已完成的步骤摘要
pending_conflicts - 未解决的冲突/模糊点
```

### 迭代管线
```
Round 1: PARSE → PlanBlock(v1) → EXECUTE → PlanBlock(v1+)
Round 2: PARSE 读 PlanBlock(v1+) → 新 intent → EXECUTE → PlanBlock(v2)
...
Final: PlanBlock 累积 → PlannedState → KG L4
```

### 需实现
1. PlanBlock 继承 SpatialCognitiveUnit（修 audit S4）
2. _apply_plan_block(plan_block) → 累积变更 → PlannedState
3. PlanBlockAccumulator：多轮累积
4. PARSE/EXECUTE 图节点读取上一轮 PlanBlock

---

## 五、ContextBlock 与 KG 查询的关系

ContextBlock 由 KG 查询结果生成（单一语义来源）：
- 冷启动时：轻量构建基础 KG（毫秒级）→ KG 查询 → ContextBlock
- 无需长期维护两条计算路径

ContextBlock 各层与 KG 查询的对应：
| ContextBlock 内容 | 来源 | 对应 KG 查询 |
|---|---|---|
| 村域 bbox/总面积/质心 | spatial_ops（几何） | 无（KG 不存全几何） |
| 居民点聚类/空间关系 | spatial_ops（聚类） | 无 |
| 约束重叠地块 BSM | spatial_ops（ConstraintIndex） | get_constraint_coverage |
| 地类分布统计 | KG 语义聚合 | get_village_cognition(layer_cards) |
| 图层组卡片 | KG 语义聚合 | get_village_cognition |
| 设施/道路列表 | KG 查询 | get_facility_locations 等 |
