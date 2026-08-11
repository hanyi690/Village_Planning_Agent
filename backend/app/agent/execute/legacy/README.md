# EXECUTE legacy helpers

本目录只保留 EXECUTE 迁移期间的兼容辅助函数，例如旧图层字段转换。它不是新的业务入口，也不应承载新的空间算法。

## 使用规则

- 新代码不得直接依赖本目录；优先使用 `app.modules.spatial_ops`、`schema/contracts` 和 `agent/execute/nodes`。
- 若必须兼容旧 checkpoint，调用方应在边界处完成一次迁移并记录来源，而不是把旧字段继续扩散到 worker。
- 删除条件：所有生产调用方和回放测试都改为 typed artifact/contract，且旧 checkpoint 迁移测试通过。

当前唯一实现为 `layer_helpers.py`，状态为 `DEPRECATED / COMPATIBILITY ONLY`。
