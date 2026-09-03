# 08 认知闭环实施顺序

> Status: TARGET PLAN
>
> 本文件只规定实施顺序、兼容门和回滚。它不证明任务已经完成；完成度见
> <code>05_MIGRATION.md</code>。

## 1. 目标

先闭合：

~~~text
DATA
  → WM bootstrap
  → Evidence
  → L1 observation
  → L1-GROUND
  → Cognition commit
  → WM update/rebase
  → L1 final view
~~~

不在本阶段扩大 ontology、provider 数量、target family 或 solver 类型。

## 2. 实施原则

1. contract 先于 producer，producer 先于 consumer；
2. 每一步同时完成 persist/reload/failure/recovery；
3. 新旧路径只能通过显式 adapter 共存；
4. shadow 只比较，不写第二份权威状态；
5. 每个切换门可按 session/branch 回退；
6. 代码存在不等于状态 CURRENT；
7. 先完成真实纵向闭环，再扩横向能力。

## 3. Phase A：统一状态与产品

交付：

- provider attempt 终态；
- Evidence gap 终态；
- L1 fact/location 状态；
- Ground subject 终态；
- Gate Transition Matrix 对应的 route contract；
- <code>L1ProductManifest</code>；
- <code>HumanDecisionArtifact</code>。

门：

- 不再产生 <code>passed=True + pending</code>；
- 所有兼容状态有单向映射和 reason code；
- schema round-trip 与非法状态转移测试通过。

回滚：

- 保留旧字段只读解析；
- 新写入只用新状态；
- adapter 不允许把细粒度终态压回 resolved 布尔值后再写。

## 4. Phase B：Assertion 生命周期

交付：

- proposal/decision/assertion contract；
- accepted/ambiguous/rejected/superseded validator；
- merge/split transaction；
- affected binding invalidation；
- stale-parent/rebase receipt；
- projection rebuild。

门：

- 旧 assertion 不被覆盖；
- merge/split 可重放；
- commit failure 不发布 child；
- source graph 与 planned graph 不被误改。

回滚：

- named ref 保持指向最后有效 snapshot；
- 未发布 child 进入 GC 候选；
- 不回退到破坏性 entity merge。

## 5. Phase C：Evidence Acquisition / Reasoning

交付：

- query plan artifact；
- provider attempt/分页 receipt；
- requirement authority policy；
- confidence components 与 authority；
- dedupe/candidate cluster/conflict set；
- requirement-specific sufficiency；
- Evidence→Cognition proposals。

门：

- quota/failed/not-attempted/empty/missing 不混淆；
- 分页不完整无法支持 absence；
- 外源 observation 不能成为 execution geometry；
- 相同 fingerprint 幂等。

回滚：

- 禁用外部 adapter 时仍可用本地 DATA/WM/text；
- 旧 cache 只读，通过兼容 normalizer 进入新 observation contract。

## 6. Phase D：L1 observation 与 final product

交付：

- source-span validation report；
- fact acceptance；
- conflict group/supersedes；
- spatial work-item admission；
- observation/binding/commit refs 的 product manifest；
- L2/L3 final-view projection。

门：

- accepted fact 全部可追溯；
- 规划成果不能进入 current fact；
- 非空间工作项不进入 GROUND；
- L2 只消费版本一致 final view。

回滚：

- 统一使用 <code>L1ObservationSnapshot</code> 作为 observation product；
- manifest 缺失时不得把旧 snapshot 当完整 final product。

## 7. Phase E：L1-GROUND

交付：

- subject state machine；
- candidate_count=0 reason；
- blocking/ranking/closed-set selection；
- relation/anchor resolution；
- binding/assertion proposals；
- Cognition commit transaction；
- post-commit revalidation；
- unresolved-only recovery。

门：

- 每个工作项唯一终态；
- GROUND 不直接写图；
- candidate ref/geometry 无法由模型生成；
- provider failure 不变成 missing；
- 新 evidence 只重跑受影响 subject。

回滚：

- 旧 <code>GroundedEntityBindingSnapshot</code> 可读；
- 无法映射的旧 unresolved 保持 unresolved，不猜测细分类。

## 8. Phase F：Typed World Views 与局部 digest

交付：

- Current/Intent/Planned query ports；
- adapter-level view enforcement；
- entity/relation/representation dependency digest；
- dependency index；
- row-level invalidation；
- index descriptor lifecycle。

门：

- L1/L2/L3 无法读取 planned；
- planned 更新不使 current-only artifacts stale；
- 小 assertion 更新不触发全链重跑；
- pagination 绑定 immutable snapshot。

回滚：

- 统一 <code>WorldModelPort</code> 作为只读兼容 facade；
- 兼容 facade 必须显式声明 view，不能恢复全图权限。

## 9. Phase G：HumanDecision

交付：

- review package 与 decision schema；
- admission/identity/representation/approval decision adapters；
- supersedes、scope 和 digest staleness；
- operator/audit projection。

门：

- 人工操作不直接改数据库状态；
- 旧 context/WM 决定会 stale；
- decision 必须经过原 owner validator；
- 重复提交幂等。

## 10. Phase H：语义 benchmark

最小标注集覆盖：

- schema mapping；
- entity merge/split；
- 设施 exact/feature-set；
- 道路 segment/centerline；
- 水体 locator/extent；
- 自然村 scope；
- 相对位置 anchor/relation；
- 非空间工作项；
- Evidence sufficiency；
- representation purpose。

指标：

~~~text
schema mapping precision
entity false merge/split
candidate recall@K
grounding precision
representation-purpose accuracy
sufficiency false positive/negative
hard constraint violation
~~~

工程 Gate 全 PASS 但语义指标未达门，不得标 CURRENT。

## 11. Phase I：中期规划 MVP

认知闭环 CURRENT 后才进入：

1. L2/L3 non-empty products；
2. TARGET pending/admitted route；
3. Planning GROUND executable domain；
4. SELECT feasible/infeasible certificate；
5. approval artifact；
6. generic point/line/polygon EXECUTE；
7. VALIDATE/RECONCILE/DELIVER。

## 12. Shadow 与切换

允许模式：

~~~text
legacy_read
shadow_v2
prefer_v2
v2_only
~~~

规则：

- shadow 不写第二个 current truth；
- compare 以 stable refs、status、lineage、candidate set 和 digest 为维度；
- 差异形成 artifact，不写日志即丢；
- 切换按 session/branch 配置；
- <code>v2_only</code> 前必须证明历史 artifact 的读兼容或明确拒绝策略。

## 13. 删除门

只有同时满足才删除兼容路径：

- 无生产调用者；
- fresh 纵向闭环通过；
- 历史 artifact replay 策略确定；
- rollback 演练通过；
- telemetry 观察期无隐式依赖；
- 文档、代码、测试和运行配置同时移除引用。

当前具体状态和最近出口只更新 <code>05_MIGRATION.md</code>。
