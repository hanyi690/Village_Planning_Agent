# 前端架构（Frontend）

> 回答"前端状态怎么管、SSE 怎么连"。
> 技术栈：Next.js 14 + React 18 + Zustand 5 + MapLibre GL。

## 1. 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Next.js | 14.2+ | 应用框架（App Router） |
| React | 18.3+ | UI 库 |
| Zustand | 5.0+ | 全局状态管理 |
| Immer | 11+ | 不可变状态更新 |
| MapLibre GL | 5.22+ | 地图渲染（**非 Leaflet**） |
| react-map-gl | 8+ | React MapLibre 绑定 |
| Tailwind CSS | 4.2+ | 原子化 CSS |
| Bootstrap | 5.3+ | 组件库 |
| framer-motion | 12+ | 动画 |
| TypeScript | 5+ | 类型安全 |

## 2. 目录结构

```
frontend/
├── package.json
├── next.config.js
├── tsconfig.json
├── tailwind.config.ts
└── src/
    ├── app/                         # Next.js App Router
    │   ├── layout.tsx               # 根布局
    │   ├── page.tsx                 # 首页
    │   ├── globals.css              # 全局样式
    │   └── test-gis/                # GIS 测试页
    │       ├── page.tsx
    │       ├── types/
    │       └── components/
    ├── features/
    │   ├── planning/                # 规划功能模块（核心）
    │   │   ├── api/                 # API 客户端
    │   │   │   ├── client.ts        # fetch 封装
    │   │   │   ├── planning-api.ts  # 规划 API
    │   │   │   └── data-api.ts      # 数据 API
    │   │   ├── store/               # Zustand Store
    │   │   │   ├── planningStore.ts # 核心状态（planning state）
    │   │   │   └── planning-context.tsx
    │   │   ├── hooks/               # React Hooks
    │   │   │   ├── useSSE.ts        # SSE 连接管理
    │   │   │   ├── useStreaming.ts  # 流式文本
    │   │   │   ├── useStreamingRender.ts
    │   │   │   ├── useHandlers.ts
    │   │   │   ├── useApprovalActions.ts
    │   │   │   ├── useSessionRestore.ts
    │   │   │   ├── useSelectors.ts
    │   │   │   └── usePersistence.ts
    │   │   ├── components/          # React 组件
    │   │   │   ├── layout/          # 布局（Header, FocusArea, LayerNav, ProcessPanel, ReportViewer）
    │   │   │   ├── chat/            # 对话（MessageList, StreamingText, ToolStatusPanel, GisResultCard...）
    │   │   │   ├── gis/             # GIS（MapView, LegendPanel, LayerTogglePanel, TracePanel, ValidationPanel）
    │   │   │   ├── knowledge/       # 知识卡片
    │   │   │   ├── settings/        # 设置面板
    │   │   │   └── ui/              # 通用 UI（MarkdownRenderer, ImagePreview）
    │   │   ├── config/              # 配置（dimensions, phases, planning）
    │   │   ├── constants/           # 常量
    │   │   ├── types/               # TypeScript 类型（events, messages, guards）
    │   │   └── utils/               # 工具函数
    │   └── gis-test/                # GIS 测试功能模块
    ├── styles/                      # 全局 CSS（layer-report.css）
    ├── types/                       # 全局类型（message/）
    └── __tests__/                   # 测试
        ├── hooks/
        ├── lib/
        └── api/
```

## 3. 状态管理（Zustand 5 + Immer）

核心 Store：`features/planning/store/planningStore.ts`

- **单一 Store**：规划全状态集中管理（phase、reports、completedDimensions、isPaused、messages...）
- **Immer 中间件**：简化不可变更新
- **派生状态**：`currentLayer`、`completedLayers`、`isPaused`、`pendingReviewLayer` 均由 Checkpoint 状态派生
- **SSOT 对齐**：前端状态是后端 Checkpoint 的投影，SSE 事件驱动更新

## 4. SSE 连接管理

通过 Hooks 管理生命周期：

| Hook | 文件 | 职责 |
|------|------|------|
| `useSSE` | `hooks/useSSE.ts` | EventSource 连接、事件分发、断线重连 |
| `useStreaming` | `hooks/useStreaming.ts` | Token 级增量文本缓冲 |
| `useStreamingRender` | `hooks/utils/useStreamingRender.ts` | 流式渲染调度（节流） |
| `useSessionRestore` | `hooks/useSessionRestore.ts` | 会话恢复（`/sync` 增量同步） |
| `useHandlers` | `hooks/useHandlers.ts` | SSE 事件 → Store 更新映射 |
| `useApprovalActions` | `hooks/useApprovalActions.ts` | 审批操作（approve / reject） |
| `useSelectors` | `hooks/useSelectors.ts` | 派生状态选择器 |

**连接流程**：

```
POST /api/sessions  ──►  session_id
                            │
                            ▼
                     useSSE(session_id)
                            │ EventSource
                            ▼
                 GET /api/sessions/{id}/stream
                            │
                    SSE events (single channel)
                            │
                            ▼
                     useHandlers -> planningStore
```

**SSE 事件清单**（`api/types.ts` 的 `SSEEventType` + `planning-api.ts` 的注册列表，二者必须同步）：

| 类别 | 事件 |
| ---- | ---- |
| 维度 | `dimension_start`、`dimension_delta`、`dimension_complete` |
| 层级 | `layer_started`、`layer_completed` |
| 工具 | `tool_call`、`tool_progress`、`tool_result` |
| AI 响应 | `ai_response_delta`、`ai_response_complete` |
| GIS / RAG | `gis_result`、`gis_layer_update`、`rag_result` |
| 级联 | `cascade_impact`、`cascade_complete` |
| 设置 / HITL | `rag_config_updated`、`step_mode_updated`、`human_review_paused` |

`human_review_paused` 已同时加入 `SSEEventType` 联合类型与 `planning-api.ts` 的 `addEventListener` 注册列表，前端可直接渲染 HITL 暂停状态。

**连接生命周期修复**：

- `useSSE`（`hooks/useSSE.ts`）曾对 `pause` / `completed` 注册重复监听，导致暂停后状态错乱 -- 已移除重复监听，`completed` 事件统一在单一 handler 中 `close()` EventSource 并设置 `shouldSuppressReconnect`。
- 重连定时器 `reconnectTimerRef` 现在在组件卸载（unmount cleanup）和 sessionId 变更两条路径上都 `clearTimeout` + 置空，修复了重连定时器泄漏。
- 批处理 timeout `batchTimeoutRef` 同样在 unmount 时清理。

## 5. 地图（MapLibre GL）

- **库**：`maplibre-gl` + `react-map-gl`（非 Leaflet）
- **底图**：天地图瓦片，经后端代理 `/api/tiles/tianditu/{layer_proj}/{z}/{y}/{x}`
- **组件**：`components/gis/MapView.tsx`
- **图层控制**：`LayerTogglePanel`、`LegendPanel`
- **GIS 结果**：DELIVER/Render 产出的图层数据经 SSE `gis_layer_update` 事件推送，前端渲染。`layout_configs` 仍是迁移期兼容字段。

## 6. 脚本命令

| 命令 | 说明 |
|------|------|
| `npm run dev` | 开发服务器（端口 3000） |
| `npm run build` | 生产构建 |
| `npm run lint` | ESLint 检查 |
| `npm run type-check` | TypeScript 类型检查（`tsc --noEmit`） |
| `npm test` | Jest 单元测试 |
| `npm run test:watch` | Jest watch 模式 |
| `npm run test:coverage` | Jest 覆盖率 |
| `npm run test:e2e` | Playwright E2E 测试 |
| `npm run test:e2e:ui` | Playwright UI 模式 |
| `npm run test:e2e:headed` | Playwright 有头模式 |

## 7. 开发服务器

```bash
cd frontend
npm install
npm run dev
# 访问 http://localhost:3000
```

默认端口 **3000**。后端 API 默认 `http://localhost:8000`，通过 `NEXT_PUBLIC_API_URL` 环境变量配置。

## 8. 相关文件

| 文件 | 说明 |
|------|------|
| `frontend/package.json` | 依赖与脚本 |
| `frontend/src/app/layout.tsx` | 根布局 |
| `frontend/src/features/planning/store/planningStore.ts` | 核心状态 |
| `frontend/src/features/planning/hooks/useSSE.ts` | SSE 连接 |
| `frontend/src/features/planning/api/client.ts` | API 客户端 |
| `frontend/src/features/planning/components/gis/MapView.tsx` | 地图组件 |
