# 模块成熟度验收

> Status: CURRENT ASSESSMENT SURFACE

本目录只记录模块当前达到 P0/P1/P2 的证据与缺口，不承载模块设计。设计规则见
<code>../EXECUTABLE_DESIGN_STANDARD.md</code>，当前代码事实总览见
<code>../../architecture/CURRENT_RUNTIME.md</code>，差距只在 <code>../05_MIGRATION.md</code> 维护。

当前范围修正：本轮 MVP 只执行 <code>01_data_acceptance.md</code> 的 DATA 文件读取探针。
其余卡片保留为后续阶段的设计/验收面，不因本轮探针运行而宣称下游闭环已完成。

## 阅读顺序

1. <code>00_common.md</code>：成熟度、证据和判定规则；
2. 核心闭环：DATA → World Model → Evidence → L1 → L1-GROUND；
3. 规划主链：L2 → L3 → Target Projection → Planning Ground → SELECT → EXECUTE；
4. 交付闭环：VALIDATE → Delivery Readiness Reconcile → DELIVER。

文件名中的序号只表示阅读顺序，不表示 workflow stage id。

## 规则

- 卡片链接设计 owner，不复制第二份状态机或字段规范；
- <code>TARGET</code> 不能勾选为当前通过；
- P0/P1/P2 分级判断，不因生产级缺口否定已验证的早期闭环；
- 任何“通过”都必须能由代码、artifact、命令或真实 fixture 复现；
- 证据变化时更新卡片，设计变化时先更新对应设计 owner。
