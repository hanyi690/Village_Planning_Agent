# gis-test feature

`gis-test/` 是开发期 GIS 能力验证客户端，不是正式规划业务入口。它调用 `/api/gis-test/*`，展示服务状态、标准图层、工具结果和管线追踪，供前后端联调与 Playwright 验收使用。

正式 GIS 业务仍通过 `features/planning` 的会话 API 与后端 `app/spatial/`、`app/domain/delivery/` 的交付产物完成。该 feature 不应复制空间算法、修改规划状态或在生产环境暴露测试控制器。

验证入口：`frontend/src/app/test-gis/page.tsx`、`frontend/e2e/gis-frontend.spec.ts`、`frontend/e2e/gis-integration.spec.ts`。
