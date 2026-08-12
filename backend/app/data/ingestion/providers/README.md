# Data Providers — POI / 外源锚点搜索子模块

> **定位**：地图 API 的**能力提供者**（Provider）子模块，供 POI 搜索、外源锚点补全与旧分析工具消费。每个 Provider 目录封装一家地图服务商的 HTTP API。
> **Updated: 2026-08-05**（Batch B 复核：`base.py` / `base_types.py` / `orchestrator.py` / `adapters` / `dem_provider.py` / `osm/` 已删除）

---

## 职责边界

**负责**：
- `poi.py`：POI 统一搜索接口（高德优先，失败回退天地图；批量公共设施类型码搜索）
- `amap/` / `baidu/` / `tencent/` / `tianditu/`：各服务商核心 API 封装（POI / 地理编码 / 路线 / 瓦片 / WFS）

**不负责**：
- 不做连接/限速管理（那是 `connections/`）
- 不做数据读取编排（那是 `catalog/`）
- 不做业务决策

---

## 输入/输出契约

**输入**：查询参数（关键词 / 中心点 / 半径 / 类型码）+ 凭证（来自 `app.core.settings` 或连接层）。

**输出**：各 Provider 的 `*Result` 数据类（`success` + `data` + 元数据）与统一 POI 结果。

**目录清单**：

| 子目录 | Provider | 要点 |
|---|---|---|
| `amap/` | `AmapProvider` + `AnchorService` | POI 文本/周边/驾车/步行；外源锚点（村委会 + 设施 + 道路名 + 水库名）；GCJ02 |
| `baidu/` | `BaiduProvider` | bd09ll，`coord_type=1` 强制 WGS84 |
| `tencent/` | `TencentProvider` + `AnchorService` | GCJ02，`coord_type=wgs84` 可直接返 WGS84 |
| `tianditu/` | `TiandituProvider` + `TileService` + `WFSService` + `GDService` | 搜索/地理编码/行政区；瓦片；WFS（HYDA/HYDL/LRDL）；广东省专题服务（WMS/WMTS/WFS） |

---

## 依赖方向

```
providers/ → data/connections（RateLimiter）、app.core.settings、app.utils
   ▲ 被 data/catalog（external_anchors）和显式 POI/KG 适配器消费
```

- 允许：`data/connections`、`app.core.settings`、`app.utils`、第三方 HTTP 库
- 禁止：`agent` / `services` / `api`；不 import 上层工具

---

## 禁止行为

- 在 Provider 内做规划逻辑 / LLM 调用
- 硬编码凭证 / 绕过限速器
- 新增"第 N 套 Provider 抽象"——新数据访问应走 `catalog/` + `adapters/` 策略模式；本子模块仅保留 POI/外源锚点能力
- 使用 GCJ02/BD09 坐标而不同步做 WGS84 归一（统一坐标口径）
