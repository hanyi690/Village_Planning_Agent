# Wave Roadmap — 后续波次 B-M（项目驱动式规划管线逐模块完善）

> Wave A 已交付：advisory_crosswalks 隔离、22 个契约文件、6 个 ports、ArtifactStore + 审查包协议。
> 每个波次完成后生成审查包（summary.md + artifact.json + trace.json + preview.geojson）并进入 awaiting_review，
> 通过后才切换下一波次；旧路径在对应新模块通过后原子删除。

## 全局验收条件（每波次通用）
- 默认测试不依赖网络、外部服务或 gitignored 数据并全部通过
- 架构不变式无 modules → agent/services、spatial → kg、kg → data 反向依赖
- 活动规划链对跨体系映射符号扫描为零（advisory_crosswalks 隔离区已建立）
- 每个模块能单独运行、重放并生成标准审查包

| 波次 | 模块 | 关键变更 | 审查包内容 | 消除的已知问题 |
|---|---|---|---|---|
| B | L1 OBSERVE | 收敛报告式输出为 L1Snapshot；现状分类仅为事实（ClassificationRef）；明确证据缺口 | 事实、证据、约束、问题、证据缺口 | - |
| C | EXPLORE | 删除候选地块/BBox 决策/intent 写入；只返回 EvidenceBundle | 请求、证据、来源、置信度、未解决项 | - |
| D | L2 STRATEGIZE | 独立策略子图 + 一致性 Gate；输出 L2Strategy；不生成坐标/候选/分区 | 目标—问题—策略—证据矩阵、策略冲突 | - |
| E | L3 PLAN | 从"先列分区面积"改为生成 PlanningProgram；项目需求/用地需求/实施计划子图 | 项目表、土地需求表、项目依赖图、遗漏项 | - |
| F | PARSE | 独立 Intent Compiler 子图；编译为 IntentCompilationResult + SpatialReferenceSpec | 源字段→结构化字段逐项对应、编译错误 | - |
| G | GROUND | 注入 Gazetteer/SemanticQuery/SpatialQuery ports 消除对 KG 反向依赖；生成 CandidateSite | 候选区域 GeoJSON、候选地块组合、约束覆盖、未解析原因 | spatial_ops→kg 反向依赖 |
| H | SELECT | 硬约束过滤 + 多因子评分 + 冲突分配；输出 SiteSelectionDecision；删除"第一个可用候选"逻辑 | 完整排名、淘汰理由、最终组合、地图预览 | - |
| I | EXECUTE | Land Design Worker 生成项目轮廓 + ParcelChangeSet；其他 Worker 只消费决定；删除现状驱动 ZoneGenerator/MIP 正式路径 | PlannedState、操作日志、面积守恒、地块谱系、前后对比图 | 8 个 EXECUTE 链 advisory_crosswalks 违规 |
| J | VALIDATE | 独立 Gate；校验硬约束/面积/拓扑/重叠/连续性/可达性/契约完整性/规划分类缺失；按责任阶段标记 | ValidationReport、责任阶段归属 | - |
| K | RECONCILE | PlanningIntervention→SpatialReferenceSpec→CandidateSite→SiteSelectionDecision→ParcelChangeSet→PlannedState 覆盖矩阵 | 覆盖矩阵、不一致清单 | - |
| L | DELIVER | 仅 Validate+Reconcile 通过的版本可导出；DeliveryManifest；缺规划分类时阻止"完整法定成果" | 交付清单、溯源、未决人工项 | - |
| M | BOOTSTRAP 集成 | 目标主图替换六节点图；State 只留阶段/Gate/context/artifact 引用/issues/human_review；Graphify 依赖图 | 主图拓扑、阶段状态机、依赖图 | kg→data 反向依赖 |

## 依赖顺序
B → C（EXPLORE 横向服务，可并行于 B/D/E）→ D → E → F → G → H → I → J → K → L → M。
G 需要 C 的证据契约；H 需要 G 的 GroundingResult；I 需要 H 的 SiteSelectionDecision + LandDesignBrief。

## 关键约束（源自主 spec §2/§3）
- 现状地类只提供：分类代码与名称（ClassificationRef）、几何/面积/权属、利用状态/转换成本/适宜性、与道路/设施/居民点/控制线的关系。禁止从现状 DLBM 自动推出规划用途/规划分区/三生空间/项目位置。
- 规划分区改为后置综合结果（由 L2 空间结构 + 已选项目 + 规划地块 + 控制线 + 非建设性干预生成）。
- 受控地块重构：项目轮廓可跨多个现状地块；split_ratio 只能作为面积提示，实际切割由项目轮廓/切割线/约束几何执行；源地块面积守恒、几何有效、无未说明重叠；记录 derived_from_bsms 谱系。
- 跨体系映射保留在 advisory_crosswalks 隔离区，默认禁用、不提供给 LLM；L2/L3/PARSE/GROUND/SELECT/EXECUTE 禁止导入。
- 未明确规划分类的未调整地块使用 preserve，不自动伪造规划编码。

## Wave A 交付物（已完成）
- schema/advisory_crosswalks/（隔离区 + 19 YAML + 静态扫描测试）
- schema/contracts/ 22 个契约文件（输入/输出/控制全覆盖）+ 6 个 ports
- services/artifact_store.py + services/review_package.py（.run-tmp/{run_id}/{module}/）
- 13 个阶段 I/O 契约覆盖：Bootstrap/Router/L1/Explore/L2/L3/PARSE/GROUND/SELECT/EXECUTE/VALIDATE/RECONCILE/DELIVER
