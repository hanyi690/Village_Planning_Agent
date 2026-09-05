# infrastructure/kg：DATA-backed World Model 的 RDF 适配层

本目录只保留当前实现：DATA catalog 投影出的不可变 World Model、当前视图读取适配器、
外部观测适配器和统一 ontology。旧的 KG builder、manager、session KG、SPARQL 查询包、
enrichment、gazetteer 和空间索引已经物理删除；它们不再是运行时或文档契约的一部分。

## 当前文件职责

| 文件 | 职责 |
|---|---|
| `ontology.py` | World Model 使用的 `PLN`/`GEO` 命名空间和受控谓词集合。 |
| `adapters/source_catalog_adapter.py` | 将已准入的 `DataResourceCatalog` 投影为确定性的 source/world RDF 三元组。仅读 catalog，不修改原始/归一化几何。 |
| `adapters/current_world_adapter.py` | 给 WM、Evidence、GROUND 提供当前 world/source 图的有界只读查询，并按 WM snapshot digest 缓存索引。 |
| `adapters/world_model_adapter.py` | Cognition 提交边界和网络重试的窄适配；不是旧 KG 查询入口。 |
| `adapters/external_observation_adapter.py` | 将 provider observation cache 变成带来源、范围和 digest 的只读外部观察。 |

## 唯一数据流

```text
admitted DataResourceCatalog
  -> source_catalog_adapter
  -> WorldModelKGStore (CAS + compare-and-set)
  -> CurrentWorldQueryAdapter
  -> WM / Evidence / GROUND
```

World Model 只消费已准入 DATA。原始文件、normalized geometry、provider cache 均不在这里
被改写；Evidence 可以引用 source/world entity 和 external observation，但不能把观察升级为
世界事实。所有写入通过 Cognition/World Model commit port，并绑定 source snapshot digest。
