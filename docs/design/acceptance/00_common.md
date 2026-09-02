# 通用成熟度验收规则

> Status: CURRENT
>
> 设计标准 owner：<code>../EXECUTABLE_DESIGN_STANDARD.md</code>。

## 本轮 MVP 范围修正（2026-09-02）

本轮 MVP 是一次测试/运行验收探针，不是新增的业务模块。当前只验收 DATA 对声明文件的
读取、准入、失败记录和 CAS 重载；不推进 Cognition、World Model、Evidence enrichment、
L1、L1-GROUND 或 L2。任何把 MVP 写成下游模块实现的方案都超出本轮范围。

## 成熟度

| 等级 | 判定目标 | 必须回答 |
|---|---|---|
| P0 / Loop Ready | 当前认知闭环真实闭合 | 边界、artifact、状态、失败、恢复、重载、下游消费 |
| P1 / MVP Ready | 稳定服务规划主链 | 版本稳定、增量失效、人工边界、真实端到端规划探针 |
| P2 / Production Ready | 可生产运营 | 输入广度、并发、安全、性能、治理、监控和灾难恢复 |

后一级继承前一级。验收结论必须写成“模块在已声明输入边界内达到某级”，不得只写“完成”。

## 证据等级

| 标签 | 能证明什么 | 不能证明什么 |
|---|---|---|
| <code>IMPLEMENTED</code> | 代码路径或 contract 已存在 | 真实运行与边界正确 |
| <code>RUNTIME_VERIFIED</code> | 指定 probe/test 在指定输入上通过 | 未覆盖输入和生产规模 |
| <code>PARTIAL</code> | 部分链路存在 | 对应成熟度整体通过 |
| <code>TARGET</code> | 已定义目标规范 | 当前已经实现 |
| <code>HISTORICAL</code> | 历史时点曾观察到 | 当前仍保持 |

## 每一级的四个 Gate

1. Entry Gate：输入和版本是否满足准入；
2. Product Gate：typed artifact 是否完整、可重载、诚实表达 partial/failure；
3. Consumer Gate：指定下游是否通过公开 facade 实际消费；
4. Recovery Gate：gap 是否有 owner、恢复动作、停止条件和重放证据。

任一 required gate 缺少证据，该级就是 <code>PARTIAL</code> 或未达到。可保存 diagnostic artifact
不等于可继续主链；<code>passed=true + pending</code> 不得作为完成证据。

## 金田村 P0 MVP 输入闭包

所有本轮 DATA-only fresh probe 必须明确记录以下输入，不得以
<code>boundary.geojson</code> 单文件代替完整输入系统：

- 10 个 <code>data/gis/jintian/current/*.geojson</code> 现状图层：行政界线、注记、村界、
  建设分区、生态保护、耕地保护、地质灾害点、历史保护、现状地类、道路；
- 唯一 DEM 文件 <code>data/gis/jintian/terrain/dem.tif</code>；本轮不假设存在额外 source
  package；
- <code>docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md</code>；
- <code>data/cache/map_observations/amap/</code>、<code>tianditu/</code>、<code>tencent/</code> 的统一
  缓存；旧 <code>output/map_validation/</code> 已物理删除；
  provider cache manifest、normalized rows、attempt/request lineage、raw response/cache refs；
  这些是独立缓存盘点输入，不是本轮 DATA current catalog 的文件。

验收必须逐项报告 source ref、content/semantic digest、输入角色、文件或缓存状态、
覆盖范围和下游消费位置。三家地图缓存即使返回空、未尝试、部分完成、失败或配额耗尽，
也必须以 provider attempt/gap 保留；不能把缓存缺失折叠成成功，也不能把外源坐标直接
写入本地执行 representation。

DATA 读取只依赖声明的文件格式、编码、CRS、adapter 和输入角色。源文件的属性列作为通用
mapping 保留，不得要求 BSM、DLBM、固定字段集合、固定图层名或某个领域输入类实例。

以下内容必须在输入快照中为零：<code>data/gis/jintian/planned/</code> 下文件、规划文本、
规划图件、规划工程包及任何 planned output。验收若发现其中任一项进入 current catalog、
World Model current、Evidence current observation 或 L1 fact rows，则 Entry Gate 失败。

## 验收记录模板

| 项 | 内容 |
|---|---|
| 目标等级 | P0 / P1 / P2 |
| 声明输入边界 | adapter、fixture、provider、规模和配置 |
| 设计 owner | 唯一链接 |
| 证据 | 标签、代码/artifact/test 路径、复现命令 |
| 观察结果 | 实际输出与 reason code |
| 判定 | PASS / PARTIAL / NOT READY |
| Remaining gap | <code>../05_MIGRATION.md</code> 中的唯一条目 |

## 禁止性判定

- 只有字段、类或接口：不能从 <code>IMPLEMENTED</code> 提升为 <code>RUNTIME_VERIFIED</code>；
- mock、空列表、手工拼接或未保存输出：不能证明真实闭环；
- 设计文档中的未来时态：不能作为当前证据；
- 一次性审计或周报：只能标记 <code>HISTORICAL</code>；
- P2 未完成：不能自动把 P0/P1 判为失败；
- P0 探针通过：不能推断任意输入、并发、安全和性能已经生产就绪。
