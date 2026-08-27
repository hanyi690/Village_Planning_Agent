# 05 业务阶段迁移验收

> 本文件只记录目标业务阶段到当前代码的迁移状态，不从当前目录反推目标设计。

## 推进顺序

```text
L1 → L2 → L3 → Evidence → TARGET_PROJECTION → GROUND
→ SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
```

后一阶段必须以前一阶段真实产物可生成、可重载、可消费为前提。

## 每阶段状态

```text
CURRENT   边界、产物、适配和测试均已完成
PARTIAL   有实现但边界、真实产出或适配不完整
GAP       尚无满足目标的实现
RETIRE    旧路径无调用者，可清理
BLOCKED   有明确外部阻塞并已记录验证限制
```

## 每次迁移记录

```text
目标阶段
目标 facade 和目录
当前代码映射
权威 artifact
真实运行产出
contract/integration/regression tests
下游适配结果
遗留风险
```

## 当前映射

| 目标阶段 | 当前主要实现 |
|---|---|
| L1 | `domain/assessment/`、L1 contracts、`evidence/identity/` |
| L2 | `domain/demand/`、`objectives/`、`suitability/` |
| L3 | `domain/program/`、L3 contracts |
| Evidence | `evidence/`、`infrastructure/rag/`、`kg/`、`search/` |
| TARGET_PROJECTION | `domain/program/target_projection/`、workflow stage |
| GROUND | `domain/ground/`、`spatial/grounding/`、workflow stage |
| SELECT | `domain/allocation/`、workflow stage |
| EXECUTE | `domain/materialization/`、workflow execute/tools |
