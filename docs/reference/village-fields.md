# 村庄字段参考

> 本文只列出当前字段模型入口。具体字段以 Pydantic contract、数据模型和运行中的
> artifact schema 为准，不以本页复制的表格作为第二套 schema。

## 当前模型入口

| 内容 | 代码位置 |
|---|---|
| 数据快照、空间和表格模型 | `backend/app/data/model/` |
| 空间 contract | `backend/app/contracts/ground/`、`backend/app/contracts/spatial/`、`backend/app/spatial/model/` |
| 规划/执行/交付 contract | `backend/app/contracts/l2/`、`backend/app/contracts/l3/`、`backend/app/contracts/select/`、`backend/app/contracts/execute/`、`backend/app/contracts/artifacts/` |
| GIS layer registry | `backend/app/data/model/gis_layer_registry.yaml`、`layer_registry.py` |
| 编码和字段规则 | `backend/app/data/encodings/dicts/` |
| 上传和文档字段 | `backend/app/data/ingestion/` |

## 常见字段语义

- `bsm`：要素标识，是否必填由具体 contract 决定；
- `ysdm` / `dlbm`：来源或分类编码，不能直接当作规划目标编码；
- `geometry`：由空间 contract 和 CRS 约束，不应在 workflow state 中保存完整集合；
- `layer_type`：由 layer registry 解释，不能代替规划分类决定；
- `artifact_id`、`digest`、`parents`：用于结果身份和血缘，不是 GIS 属性。

成果图层、土地平衡和交付字段由 `DeliverySpatialSnapshot` 统一派生；相关设计见
[SELECT / EXECUTE](../design/06_SELECT_EXECUTE_AND_CODE.md)。
