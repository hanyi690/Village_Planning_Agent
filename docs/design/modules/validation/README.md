# 校验 / 反馈 / 自动迭代设计

> 模块：`backend/app/domain/validation/`
> 当前校验与交付证据：[10_IMPLEMENTATION_STATUS_CURRENT_20260818.md](../../10_IMPLEMENTATION_STATUS_CURRENT_20260818.md)

| 文档 | 内容 | 状态 |
|---|---|---|
| [07_VALIDATION_FEEDBACK.md](07_VALIDATION_FEEDBACK.md) | 校验、门控与定向反馈原则 | TARGET |
| [13_AUTOREPAIR_MULTIMODAL.md](13_AUTOREPAIR_MULTIMODAL.md) | 自动迭代与多模态规划设计 | TARGET |
| [26_LLM_VALIDATION_ORCHESTRATION.md](26_LLM_VALIDATION_ORCHESTRATION.md) | LLM 监督式校验编排方案 | TARGET |

当前事实：`domain/validation/` 实现 10 个确定性校验（`validate_checks.py`）、修复指令
（`repair_directives.py`）与对账（`reconcile.py`）；LLM 监督式编排尚未落地。
