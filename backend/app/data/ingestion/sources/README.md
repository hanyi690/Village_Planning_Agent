# Data Sources — 形态驱动读取（Driver 层）

> **定位**：数据层 **Layer 2（Source / Driver，形态驱动读取）**。每种数据形态一种 Driver，把原始数据抓取为 `DataResult`。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：
- `base.py`：`DataSourceDriver` ABC + `DriverRegistry`（装饰器自动发现）
- 各形态 Driver：`file_vector` / `api_vector` / `wmts_tile` / `local_raster` / `remote_raster` / `document`
- 统一返回 `DataResult`（成功/数据/元数据/错误/缓存路径，**永不抛异常**）

**不负责**：
- 不做连接/凭证管理（那是 `connections/`）
- 不做类型化 ingest（那是 `adapters/` + `catalog/`）
- 不做业务决策

---

## 输入/输出契约

| 文件 | Driver | 输入 → 输出 |
|---|---|---|
| `file_vector.py` | `FileVectorDriver` | 本地 GeoJSON / Shapefile → `DataResult`（geojson） |
| `api_vector.py` | `ApiVectorDriver` | WFS / MapServer REST → `DataResult` |
| `wmts_tile.py` | `WmtsTileDriver` | WMTS 瓦片下载 + 缓存 → 瓦片路径 |
| `local_raster.py` | `LocalRasterDriver` | 本地 GeoTIFF → 栅格路径 |
| `remote_raster.py` | `RemoteRasterDriver` | 远程栅格下载指引 |
| `document.py` | `DocumentDriver` | MinerU Markdown（`.md`/`.markdown`）→ 文档内容 |
| `registry.py` | `DriverRegistry` | 装饰器注册 + 按名实例化 |
| `base.py` | `DataSourceDriver` ABC | fetch() 契约 + 注册机制 |

**获取连接**：Driver 经 `ConnectionRegistry.require(name)` 获取对应 Connection（共享实例 + 限速器）。

---

## 依赖方向

```
sources/ → data/connections（Connection / ConnectionRegistry / RateLimiter）、data/contracts（DataResult）
   ▲ 由显式 provider acquisition 或测试 probe 实例化
```

- 允许：`data/connections`、`data/contracts`、`app.core.settings`、`app.utils`
- 禁止：`agent` / `services` / `api` / `tools`

---

## 禁止行为

- 在 Driver 内做 CRS 转换 / ingest / 类型化（转换在驱动层/adapters 完成，职责分层）
- Driver 抛异常（`fetch()` 必须返回失败 `DataResult` 而非抛出）
- 绕过 `DriverRegistry` 手动实例化（破坏自动发现与统一注册）
- 新增形态 Driver 不登记到 registry（Catalog 无法分发）
