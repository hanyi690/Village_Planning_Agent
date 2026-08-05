# Ports — 依赖倒置协议层

> 领域层定义、应用层实现的 **9 个 Protocol 端口** + 类型化容器 `PlanningPorts`。
> 定位：让 `modules/` 内部（尤其 `spatial_ops` / `kg`）消费服务时只依赖接口，不反向 import `app.agent` / `app.services` / `app.tools` / `app.modules.data`。

---

## 职责边界

**负责**：定义依赖倒置的抽象边界（`typing.Protocol`）与统一的端口容器。端口只描述"做什么"（方法签名），不描述"怎么做"（无实现）。

**不负责**：
- 不提供任何具体实现（实现由各层注入：kg 适配器、data 适配器、spatial_ops allocation、services 文件存储等）
- 不包含业务逻辑 / 状态 / 单例
- 不属于任一规划阶段，是所有阶段的共享基础设施

---

## 输入/输出契约

### 9 个 Protocol 端口（`app.modules.ports.*`）

| 文件 | 端口 | 核心方法 | 实现方（注入） |
|---|---|---|---|
| `zone_allocator.py` | `ZoneAllocatorPort` | `allocate(targets, candidates, constraints, metadata)` | `spatial_ops.allocation.zone_allocator_adapter`（PuLP MIP，infeasible 不抛异常） |
| `road_planner.py` | `RoadPlannerPort` | `plan(state)` / `is_available()` | EXECUTE road-construction worker 包装 staged 道路服务 |
| `spatial_query.py` | `SpatialQueryPort` | `query_by_bbox` / `query_by_geometry` / `compute_overlap` / `nearest_features` / `resolve_candidates` | `kg.adapters.spatial_query_adapter.KGSpatialQueryAdapter` |
| `artifact_store.py` | `ArtifactStorePort` | `store` / `retrieve` / `list_by_run` / `list_by_module` / `delete` | `services.artifact_store.FilesystemArtifactStore`（原子写 + 路径约束） |
| `bundle_assembly.py` | `BundleAssemblyPort` | `merge_geojson_into_bundle(bundle, layer_key, geojson)` | `data.bundle_assembly_adapter.DataBundleAssemblyAdapter` |
| `context_provider.py` | `ContextProviderPort` | `get_context` / `get_dataset` / `get_version` | 应用层 context 服务 |
| `gazetteer.py` | `GazetteerPort` | `resolve_place_name` / `get_cluster_by_name` / `resolve(name, fuzzy)` | `kg.adapters.gazetteer_adapter.KGGazetteerAdapter` |
| `nomenclature_registry.py` | `NomenclatureRegistryPort` | `get_canonical_name` / `get_code` / `list_by_system` | 编码体系注册表适配 |
| `semantic_query.py` | `SemanticQueryPort` | `query_entities` / `query_relations` / `resolve_ambiguous` | KG 语义查询适配器 |

### 容器：`PlanningPorts`（`planning_ports.py`）

```python
@dataclass
class PlanningPorts:
    artifact_store: ArtifactStorePort | None = None
    context_provider: ContextProviderPort | None = None
    semantic_query: SemanticQueryPort | None = None
    spatial_query: SpatialQueryPort | None = None
    gazetteer: GazetteerPort | None = None
    nomenclature_registry: NomenclatureRegistryPort | None = None
    bundle_assembly: BundleAssemblyPort | None = None
    zone_allocator: ZoneAllocatorPort | None = None
    road_planner: RoadPlannerPort | None = None
```

`PlanningPorts` 替换了 `PlanningContext` 上旧的 `ports: dict[str, Any]`，让下游以类型化 Protocol 消费而非 dict 查找。所有字段可选（`None` = 未注入，调用方需判空）；提供 `has_artifact_store` 便捷属性。

---

## 依赖方向

```
领域层（modules/）               应用/数据层（实现注入）
  ports/（只定义 Protocol）  ←──  kg/adapters/*、data/bundle_assembly_adapter.py
       │                          spatial_ops/allocation/、services/artifact_store.py
       └── 被 PlanningContext 持有（PlanningPorts 容器），由 services/context 工厂组装
```

- **依赖规则**：领域模块（`spatial_ops` / `kg` 等）依赖 `ports/`；实现（适配器）依赖 `ports/` 并实现其 Protocol。领域层永远不 import 实现方所在层。
- `ports/` 自身只依赖 `typing.Protocol` + `pydantic`（`ArtifactRef`）+ `schema/contracts`（`ContractMeta` / `GazetteerEntryLike` / `SpatialReferenceSpec`）。

---

## 禁止行为

- 在端口文件里写任何实现逻辑 / 持有状态 / 定义单例 —— 端口必须保持纯接口
- 让领域模块直接 import 实现方（如 `spatial_ops → services.artifact_store`）—— 必须经端口
- 为"顺手"把未实现的方法加进 Protocol —— 端口应反映真实被消费的边界
- 在端口签名中引入 `app.agent` / LangGraph State 类型 —— 端口必须与编排层解耦
