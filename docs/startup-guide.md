# 村庄规划系统 - 服务管理指南

## 快速启动

### Windows 用户

```bash
# 双击运行或命令行执行
start-services.bat
```

### Linux/Mac 用户

```bash
chmod +x start-services.sh stop-services.sh
./start-services.sh
```

## 服务状态

### 当前运行状态

- **前端**: http://localhost:3000
- **后端**: http://localhost:8000
- **API文档**: http://localhost:8000/docs

### 端口说明

- **后端**: 8000 (uvicorn)
- **前端**: 3000 (Next.js)

## 日志管理

### 日志文件位置

```
logs/
├── backend.log      # 后端服务日志
├── frontend.log     # 前端服务日志
├── backend.pid      # 后端进程ID
└── frontend.pid     # 前端进程ID
```

### 查看日志

```bash
# 实时监控后端日志
tail -f logs/backend.log

# 实时监控前端日志
tail -f logs/frontend.log

# 查看后端最近日志
tail -n 50 logs/backend.log

# 查看前端最近日志
tail -n 50 logs/frontend.log
```

### 日志自动清理

每次启动服务时，`start-services.bat/sh` 会自动清空日志文件，确保日志不会无限增长。

## 停止服务

### Windows 用户

```bash
stop-services.bat
```

### Linux/Mac 用户

```bash
./stop-services.sh
```

### 手动停止

```bash
# 读取PID文件并停止
kill $(cat logs/backend.pid)
kill $(cat logs/frontend.pid)

# 或者直接查找进程
# Windows:
taskkill /F /IM python.exe
taskkill /F /IM node.exe

# Linux/Mac:
pkill -f "uvicorn"
pkill -f "next dev"
```

## 测试修复

### 1. 访问前端

打开浏览器访问: http://localhost:3001

### 2. 测试规划流程

1. 输入村庄名称和任务描述
2. 上传村庄数据文件（可选）
3. 点击"开始规划"
4. 观察浏览器控制台日志

### 3. 预期行为

✅ **正确的日志模式**:

```
[TaskController] 检测到暂停状态 Layer 1 (pause_after_step=true, status=paused)
[ChatPanel] Task paused at Layer 1
[ChatPanel] Updated existing layer_completed message with review state
[ChatPanel] ✅ 已批准，继续执行下一层...
```

❌ **不应该出现的日志**:

```
[useTaskSSE] Received layer_completed event
[useTaskSSE] Received pause event
[TaskController] 暂停已解除，恢复执行 Layer 1 (多次出现)
Warning: Encountered two children with the same key
```

### 4. 网络请求检查

打开浏览器开发者工具 → Network 标签:

**应该看到**:

- `GET /api/planning/status/{id}` - 每2秒轮询
- `POST /api/planning/review/{id}/approve` - 用户批准时
- `GET /api/planning/stream/{id}` - SSE连接

**SSE事件应该只有**:

- `text_delta` (流式文本)
- `error` (错误)

**不应该看到**:

- `layer_completed` 事件通过SSE
- `pause` 事件通过SSE

## 常见问题

### Q: 前端无法连接后端

**A**: 检查后端是否正常启动:

```bash
curl http://localhost:8000/api/planning/health
```

### Q: 端口被占用

**A**: 修改启动脚本中的端口号，或停止占用端口的进程:

```bash
# Windows
netstat -ano | findstr ":8000"
taskkill /F /PID <进程ID>

# Linux/Mac
lsof -ti:8000 | xargs kill -9
```

### Q: 日志文件太大

**A**: 启动脚本会自动清空日志，或手动清空:

```bash
> logs/backend.log
> logs/frontend.log
```

### Q: 服务没有响应

**A**:

1. 查看日志文件确认错误信息
2. 重启服务
3. 检查端口是否被占用
4. 确认Python和Node.js环境正常

## 开发工具推荐

### 监控SSE事件

浏览器开发者工具 → Network → 选择 `/api/planning/stream/{id}` → EventStream 标签

### 查看REST轮询

浏览器开发者工具 → Network → 筛选 XHR/Fetch → 观察 `/api/planning/status/{id}` 请求

### React DevTools

安装React DevTools浏览器扩展，查看组件状态和props

## 进阶使用

### 单独启动后端

```bash
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 单独启动前端

```bash
cd frontend
npm run dev
```

### 使用不同的端口

修改启动脚本中的端口号：

- 后端: `--port 8000` → `--port 9000`
- 前端: Next.js会自动选择可用端口

## 相关文档

- [修复总结](docs/pause-message-fix-summary.md) - 详细的技术修复说明
- [验证清单](docs/verification-checklist.md) - 自动化验证脚本
