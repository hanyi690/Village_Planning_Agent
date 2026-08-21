# Next.js app routes

`src/app/` 是 Next.js App Router 入口。`layout.tsx` 提供全局样式和页面壳，`page.tsx` 装配主规划工作台。GIS 验证通过规划工作台的真实 DataCatalog、空间链路和 DELIVER 结果完成，不再维护独立测试页。

页面只负责组合 feature；会话请求、SSE 订阅和业务状态更新分别归属 `features/planning/api`、`features/planning/hooks` 和 `features/planning/store`。新增页面需要说明是否允许生产访问、依赖的 API 端点和恢复策略。
