# 如何新增一个数据图层

> 本指南只覆盖当前 `data → spatial → evidence/delivery` 边界。不要把新图层直接塞进
> LangGraph state，也不要通过名称或编码 crosswalk 自动产生规划决定。

## 1. 先确定图层属于哪一类

- 数据来源和解析：`backend/app/data/ingestion/`；
- 数据/图层类型：`backend/app/data/model/`；
- 编码和字段规则：`backend/app/data/encodings/dicts/`；
- 几何、查询或拓扑能力：`backend/app/spatial/`；
- 证据索引或 KG 投影：`backend/app/infrastructure/evidence_runtime/` / `backend/app/infrastructure/kg/`；
- 交付图层：`backend/app/spatial/delivery/` 和 `backend/app/workflow/delivery/`。

## 2. 推荐步骤

1. 在 `backend/app/data/model/` 或 `backend/app/contracts/spatial/` 定义最小 typed model，
   明确 geometry、CRS、来源、唯一标识和质量字段。
2. 在 `backend/app/data/model/gis_layer_registry.yaml` 注册外部 layer name、geometry type
   和允许的属性；不要把规划分类写成默认值。
3. 在 `backend/app/data/ingestion/` 增加解析/适配器，并为缺文件、空集合、CRS 错误和字段
   冲突返回显式诊断。
4. 如果需要空间运算，在 `backend/app/spatial/` 增加 query/geometry port 或实现，输入
   使用 workspace/typed model，不读取 workflow state 的裸 payload。
5. 如果需要证据检索，在 `backend/app/infrastructure/evidence_runtime/` 增加来源和 provenance；KG/RAG 结果只
   支持分析，不直接写 `PlanningProgram` 或 `ParcelChange`。
6. 如果需要交付，在 `DeliverySpatialSnapshot` 的统一来源上增加 RenderLayer/export
   映射，并确认 HTML、PNG、GeoJSON、土地平衡和 manifest 共享 checksum。
7. 添加 contract、空结果、坏几何/CRS、来源冲突和端到端 projection 测试。

## 3. 验证

```powershell
$env:PYTHONPATH = 'backend'`npython -m compileall -q backend/app
python scripts/acceptance/l1_facade_probe.py --help
```

新增图层若影响地图，必须读取实际交付产物；“能解析文件”不等于“已进入规划成果”。
