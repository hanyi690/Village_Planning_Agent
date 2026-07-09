# Fix Notes — merge-gis-message-test

本压缩包是在原 `Village_Planning_Agent-merge-gis-message-test.zip` 基础上修复并清理后的版本。

## 已修改的核心问题

### 1. 修复前端 SSE 事件丢失

后端已经发送 `dimension_error` 和 `rag_query`，但前端没有注册监听，导致页面可能一直停在“分析中/待分析”，消息栏也不能正确展示 RAG 查询过程。

修改文件：

- `frontend/src/features/planning/api/types.ts`
- `frontend/src/features/planning/api/planning-api.ts`

修改内容：

- 将 `dimension_error` 加入 `PlanningSSEEventType`
- 将 `rag_query` 加入 `PlanningSSEEventType`
- 将二者加入 `EventSource.addEventListener` 注册列表
- 从 `DeprecatedSSEEventType` 中移除已经被后端实现的事件

### 2. 修复 GIS 模块缺失导入

原分支中有多处引用不存在的模块，例如：

- `app.tools.gis.data_manager`
- `app.tools.core.boundary_fallback`
- `app.config.boundary_fallback`
- `app.services.jintian_test_data_service`
- `app.services.modules.gis.accessibility_core`
- `app.services.modules.gis.spatial_analysis`
- `app.services.modules.gis.gis_core`

本版本补充了兼容实现，并修正了 `gis_context.py`、`validators.py`、`isochrone.py` 的导入路径。

新增/修改文件：

- `backend/app/tools/gis/data_manager.py`
- `backend/app/tools/core/__init__.py`
- `backend/app/tools/core/boundary_fallback.py`
- `backend/app/config/boundary_fallback.py`
- `backend/app/services/jintian_test_data_service.py`
- `backend/app/services/modules/gis/accessibility_core.py`
- `backend/app/services/modules/gis/spatial_analysis.py`
- `backend/app/services/modules/gis/gis_core.py`
- `backend/app/core/accessibility_core.py`
- `backend/app/core/spatial_analysis.py`
- `backend/app/core/gis_core.py`
- `backend/app/agent/gis_context.py`
- `backend/app/services/modules/gis/validators.py`
- `backend/app/services/modules/gis/isochrone.py`

### 3. 清理无关/缓存文件

已从压缩包移除：

- `__pycache__/`
- `*.pyc`
- `.vscode/`
- `.claude/`
- `frontend/.next.bak/`
- `frontend/tsconfig.tsbuildinfo`
- `frontend/.env.local`
- `backend/village_planning.db`
- `Village_Planning_Agent.tar.gz`

保留了 `frontend/.env.example`，本地启动时如果需要可复制为 `.env.local`。

## 建议启动方式

本地 PowerShell 推荐使用两个终端。

### 后端

```powershell
cd "你的项目路径\backend"
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

```powershell
cd "你的项目路径\frontend"
npm install
npm run dev
```

默认访问：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`

如果前端提示连不上后端，检查 `frontend/.env.local` 中是否为：

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_TILE_SOURCE=tianditu
```

## 验证情况

已执行 Python 语法编译检查：

```bash
PYTHONPATH=backend python -m compileall -q backend/app
```

结果：通过，无 Python 语法错误。

注意：我没有在当前环境完整安装 Node/Python 依赖，也没有实际连接你的 API Key 运行完整报告生成流程。因此这个版本是“代码层面修复后的可测试版本”，不是保证所有业务流程都一定一次跑通的最终生产版。

## 2026-07-09 追加修复：右侧消息栏无法发送 / 无 AI 回复

### 问题原因

1. `ChatInput.tsx` 的输入框在窄侧栏中没有设置 `min-w-0` 和 `shrink-0`，导致发送按钮可能被输入框挤到面板外，看起来像“发不出去”。
2. `ProcessPanel.tsx` 的 `handleSendMessage` 只调用了后端接口，没有把用户消息写入前端 `messages` 状态，所以发送后右侧消息列表不会立刻显示用户气泡。
3. 后端 `/api/sessions/{session_id}/feedback` 虽然接收了 `message` 字段，但原来只把消息注入规划图，没有返回聊天回复，也没有发送 `ai_response_complete`，所以前端不会出现 AI 回复。

### 修改内容

- `frontend/src/features/planning/components/ChatInput.tsx`
  - 给输入区域增加 `min-w-0`
  - 给上传按钮、发送按钮、预设按钮增加 `shrink-0`
  - 避免发送按钮在右侧面板中被挤出屏幕

- `frontend/src/features/planning/components/layout/ProcessPanel.tsx`
  - 发送时先本地加入用户消息
  - 接口成功后加入 AI 回复
  - 接口失败时在消息栏显示错误，而不是只在浏览器控制台报错

- `frontend/src/features/planning/api/planning-api.ts`
  - `sendChatMessage` 返回类型增加 `reply?: string`

- `backend/app/api/session_routes.py`
  - 为 `request.message` 增加 `_generate_chat_reply()`
  - 优先调用现有 LLM 生成右侧消息栏回复
  - 如果 API Key 缺失或 LLM 调用失败，使用本地 fallback 回复，避免消息栏完全无响应

### 使用提醒

修改后必须同时重启前端和后端：

```powershell
# 后端窗口 Ctrl+C 后重启
cd "项目路径\backend"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端窗口 Ctrl+C 后重启
cd "项目路径\frontend"
npm run dev
```
