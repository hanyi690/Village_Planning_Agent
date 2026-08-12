# Village Planning Agent frontend

Next.js 14 + React 18 前端工作台。它消费 FastAPI 的会话 API、SSE 事件和 GIS 图层契约，负责展示规划过程、报告、人工审核和空间成果；后端仍是状态与事实的权威来源。

## 运行

```powershell
npm install
npm run dev
npm run type-check
npm run lint
npm run test:e2e
```

通过 `frontend/.env.local` 设置 `NEXT_PUBLIC_API_URL`。Next.js rewrite 将浏览器的 `/api/*` 请求转发到后端；生产镜像使用 standalone output 和非 root 用户运行。

## 入口与特性

- `src/app/page.tsx`：主规划工作台。
- `src/app/test-gis/page.tsx`：开发环境 GIS 集成测试页，生产环境显示不可访问提示。
- `src/features/planning/`：会话、报告、SSE、人工审核、地图和 Zustand 状态。
- `src/features/gis-test/`：GIS 测试 API 客户端。
- `e2e/`：规划流程、日志、GIS 图层、导出和生成链路测试。

前端状态是可丢弃的 UI 投影；断线重连必须使用后端 `sync`/status 接口恢复，不能把浏览器内存当作 SSOT。

### v1 交付结论消费

- 人工审核走 `POST /human-review`（`event_id` 乐观锁），历史 checkpoint 分叉走
  `POST /resume`（`mode: checkpoint`）。
- `useDeliverySync` 在 `delivery_ready`/终态/`resync_required` 时拉取 `/delivery` 与
  `/map-layers`，`partial`/`diagnostic_only`/`statutory_complete=false` 由
  `DeliveryStatusBanner` 显著展示，不显示为法定完整成果。
- 地图以 `/map-layers` 的 `DeliverySpatialSnapshot` 投影为准（`normalizeV1MapLayers`
  做 v1 词汇 → 内部渲染词汇映射），`snapshot_checksum` 变化时整体替换图层。
