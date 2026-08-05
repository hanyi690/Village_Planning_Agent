# Utils — 跨层纯工具

> **定位**：供 `modules/` / `services/` / `tools/` 共用的**纯工具**集合——文档加载、文件类型检测、坐标/CRS/面积、GeoJSON、日志、重试、限速、SSE 事件。**不承载领域逻辑**。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：无状态 / 低状态的基础设施工具，按用途分簇（见下表）。任何层都可安全 import（`app.utils` 不依赖业务层）。

**不负责**：
- 不实现规划算法 / 领域逻辑（那是 `modules/`）
- 不访问数据库 / 不做业务编排
- 不反向 import `modules` / `services` / `agent`（保持最底层）

---

## 输入/输出契约

**文档与文件处理**：

| 文件 | 能力 |
|---|---|
| `document_loader.py` | 统一文档加载器（doc/docx/pdf/pptx/xlsx/epub/html/txt/md；MarkItDown 主 + 格式回退链）；`FileTypeDetector` / `MarkItDownLoader` / `MarkdownCleaner` |
| `mineru_loader.py` / `docling_loader.py` / `pdf_fallback.py` | MinerU / Docling 加载器；PDF 回退解析（PyPDF2 / pdfplumber） |

**空间/GIS**：

| 文件 | 能力 |
|---|---|
| `geo_utils.py` | 距离（haversine）/ 面积 / `safe_unary_union` |
| `geojson_utils.py` | GeoJSON ↔ GeoDataFrame 转换 / 地块索引 |
| `crs_engine.py` | CGCS2000 Gauss-Kruger 3° 带投影（替代 EPSG:3857，中国纬度误差 <0.03%） |
| `area_engine.py` | 统一面积计算（公顷/平方公里，CGCS2000） |
| `coord_transform.py` / `coord_utils.py` | GCJ02 ↔ WGS84 ↔ CGCS2000 坐标转换 |

**其余基础设施**：

| 文件 | 能力 |
|---|---|
| `logger.py` | 结构化日志（session_id 关联 + 文件持久化） |
| `retry.py` | 异步指数退避 + 抖动重试（RateLimitError / 500） |
| `rate_limiter.py` | LLM / Embedding 异步限速（token bucket + asyncio.Semaphore） |
| `event_factory.py` / `sse_publisher.py` / `sse_events.py` | SSE 事件结构 / 发布 / 事件类型 |
| `location_parser.py` | 省/市/县/镇/村地址层级解析 |
| `code_lookup.py` | 同系统 code↔name 确定性 1:1 查询 |
| `parse_reporter.py` / `stats_collector.py` | 解析报告 / 维度生成统计收集 |

**入口**：`utils/__init__.py` 汇总导出常用符号（文档加载、PDF 回退、geo/crs/area/coord 全套、`build_parcel_index` 等）。

---

## 依赖方向

```
utils/ → 标准库、pydantic、LangChain（InMemoryRateLimiter）、第三方（geopandas/shapely/MarkItDown 等，惰性或可选）
   ▲ 被 modules/、services/、tools/、agent/ 广泛消费
```

- 允许：标准库 / 第三方库（均为基础设施）
- 禁止：import `modules` / `services` / `agent` / `api` / `tools`（utils 必须是最底层）

---

## 禁止行为

- 在 utils 内写领域逻辑（发现即架构异味——工具应保持通用、可复用）
- 依赖业务层模块（会让依赖方向倒转）
- 引入重型框架依赖使 utils 无法被轻量消费（第三方库保持惰性/可选）
- 重复实现 utils 已有能力（如内联坐标转换、内联面积计算）
