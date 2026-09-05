# KG adapters：当前 World Model 的窄适配

当前保留的适配器只服务于 DATA-backed World Model：

| 文件 | 用途 |
|---|---|
| `current_world_adapter.py` | 给 WM/Evidence/GROUND 提供按 snapshot digest 缓存的有界只读查询。 |
| `source_catalog_adapter.py` | 把已准入 DATA catalog 投影为 source/world RDF。 |
| `world_model_adapter.py` | 提供 Cognition commit 和网络重试的窄边界。 |
| `external_observation_adapter.py` | 读取 provider observation cache，并保留 provider、scope、CRS、coverage 和 digest。 |

适配器不读取文件名、不回退旧 Bundle、不猜 CRS、不修改 catalog 几何，也不向 Evidence
直接发布未经验证的世界事实。消费方依赖 `app.contracts.ports` 或 Evidence contract，
不会反向导入已删除的 KG builder/query/gazetteer 实现。
