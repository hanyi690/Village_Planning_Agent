# Data Connections — API 连接管理

> **定位**：数据层 **Layer 1（连接管理）**。凭证 / 限速 / 重试 / session / 健康检查的持有者，与读取逻辑解耦。多个 DataSourceDriver 共享同一 Connection 实例。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：
- 管理各地图 API 的凭证（从 `app.core.settings` 环境变量读取）、限速、重试与超时
- 线程安全的共享 `RateLimiter`（按服务名单例，聚合 QPS 不超提供商限额）
- 提供 provider transport 所需的凭证、限速、session 和健康检查能力

**不负责**：
- 不做数据读取 / 驱动实现（那是 `sources/` 各 Driver）
- 不做 CRS 转换（GCJ02→WGS84 在驱动层完成，`app.utils.coord_transform`）
- 不持有业务数据

---

## 输入/输出契约

**输入**：`app.core.settings` 中的 provider 凭证、超时和限速设置；不读取 YAML source registry。

**输出**：`Connection` 实例（经 `ConnectionRegistry.require(name)` 获取）+ `RateLimiter` 单例。

**文件清单**：

| 文件 | 连接 | 要点 |
|---|---|---|
| `base.py` | `Connection` ABC + `ConnectionRegistry` | 凭证/限速/重试/session/健康；参考 QGIS QgsConnectionPool |
| `rate_limiter.py` | `RateLimiter` | 每服务全局单例（tianditu / amap），线程安全 |
| `tianditu.py` | `TiandituConnection` | 国家天地图 API（geocode / POI / 瓦片共享） |
| `amap.py` | `AmapConnection` | 高德 API（返回 GCJ02，转换在驱动层） |
| `gd_tianditu.py` | `GDTiandituConnection` | 广东省天地图专题服务（与 national 共享 'tianditu' 限速器） |

---

## 依赖方向

```
connections/ → app.core.settings（凭证）、app.infrastructure.logging
   ▲ 被 data/sources（驱动）与 data/catalog 消费
```

- 允许：`app.core.settings`、`app.utils`、标准库/第三方 HTTP 库
- 禁止：`agent` / `services` / `api` / `tools`；连接不依赖具体驱动

---

## 禁止行为

- 在连接里写读取/解析逻辑（连接只负责"能连上、受控地连"）
- 硬编码凭证（必须经 `settings` 环境变量）
- 为每个请求新建连接实例（共享实例 + 限速器才是设计意图）
- 绕过 `RateLimiter` 直接发请求（会触发提供商限流）
