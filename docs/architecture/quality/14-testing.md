> [!WARNING] **DEPRECATED — 历史参考**
> 测试结构以实际代码为准。当前测试以 [README.md](../README.md) 为准。

# 测试架构

> **更新日期**: 2026-06-05
> **版本**: v3.0

本文档说明测试结构和工具链。

## 测试结构

```
frontend/src/__tests__/       # 前端测试
├── api/
│   └── client.test.ts        # API 客户端测试
├── hooks/
│   ├── useStreamingRender.test.ts  # 流式渲染 Hook 测试
│   └── useStreamingText.test.ts    # 流式文本 Hook 测试
├── lib/utils/
│   └── message-helpers.test.ts     # 消息辅助函数测试
└── types/
    └── message-guards.test.ts      # 类型守卫测试
```

## 测试工具

| 层面 | 工具 | 配置文件 |
|------|------|----------|
| 前端单元测试 | Vitest | `frontend/vitest.config.ts` |
| 前端组件测试 | React Testing Library | - |
| E2E 测试 | Playwright | - |
| 后端测试 | pytest | `backend/pytest.ini` |

## 运行测试

```bash
# 前端测试
cd frontend && npx vitest run

# 后端测试
cd backend && pytest

# E2E 测试
npx playwright test
```

## 测试重点

| 模块 | 测试重点 |
|------|----------|
| SSE Hook | 事件处理、批处理、重连逻辑 |
| Streaming | 流式文本渲染、delta 合并 |
| 类型守卫 | 消息类型判断 |
| API Client | 请求封装、错误处理 |

---

## 相关文档

- [05-frontend-state](./05-frontend-state.md) - 状态管理
- [04-backend-api](./04-backend-api.md) - API 端点
