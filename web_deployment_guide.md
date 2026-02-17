# 村庄规划智能体 - Web应用部署指南

## 项目概述

已完成Web应用系统的开发，包括：

### ✅ 后端 (FastAPI)
- `backend/main.py` - FastAPI应用入口
- `backend/schemas.py` - Pydantic数据模型
- `backend/api/planning.py` - 规划API (POST /start, GET /{id}, SSE流式)
- `backend/api/villages.py` - 村庄API (查询列表、详情、层级内容)
- `backend/services/planning_service.py` - 规划服务，集成src.agent.py
- `backend/services/file_service.py` - 文件服务
- `backend/requirements.txt` - Python依赖

### ✅ 前端 (Next.js 14)
- `frontend/package.json` - 项目配置和依赖
- `frontend/next.config.js` - Next.js配置
- `frontend/tsconfig.json` - TypeScript配置
- `frontend/src/app/layout.tsx` - 根布局（Bootstrap + 绿色主题）
- `frontend/src/app/page.tsx` - 村庄列表首页
- `frontend/src/app/villages/[name]/page.tsx` - 村庄详情页（三层tab）
- `frontend/src/app/villages/new/page.tsx` - 新建规划页（文件上传 + 进度）
- `frontend/src/components/BootstrapClient.tsx` - Bootstrap JS客户端
- `frontend/src/components/MarkdownRenderer.tsx` - Markdown渲染组件
- `frontend/src/components/LayerView.tsx` - 层级内容组件
- `frontend/src/components/FileUpload.tsx` - 文件上传组件
- `frontend/src/components/PlanningProgress.tsx` - 进度展示组件
- `frontend/src/lib/api.ts` - API客户端
- `frontend/src/styles/globals.css` - 绿色主题样式（竖屏优化）

---

## 快速启动

### 1. 启动后端服务

```bash
# 进入后端目录
cd backend

# 安装依赖（如果尚未安装项目依赖）
# pip install -r requirements.txt

# 启动FastAPI服务器
python main.py
# 或使用uvicorn
uvicorn main:app --reload --port 8080
```

后端将在 `http://localhost:8080` 启动

**API文档**: `http://localhost:8080/docs`

### 2. 启动前端应用

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端将在 `http://localhost:3000` 启动

---

## API端点说明

### 规划相关 API (`/api/planning`)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/planning/start` | 启动新的规划任务 |
| POST | `/api/planning/upload` | 通过文件上传启动规划任务 |
| GET | `/api/planning/{task_id}` | 获取任务状态 |
| GET | `/api/planning/{task_id}/stream` | SSE流式获取任务状态 |
| DELETE | `/api/planning/{task_id}` | 删除已完成/失败的任务 |
| GET | `/api/planning/` | 列出所有任务 |

### 村庄相关 API (`/api/villages`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/villages/` | 获取所有村庄列表 |
| GET | `/api/villages/{name}` | 获取村庄信息及会话详情 |
| GET | `/api/villages/{name}/sessions` | 列出村庄的所有会话 |
| GET | `/api/villages/{name}/layers/{layer}` | 获取层级内容 |
| GET | `/api/villages/{name}/final-report` | 获取最终综合报告 |
| GET | `/api/villages/{name}/layers/{layer}/files/{filename}` | 获取特定文件 |

---

## 功能测试清单

### 后端API测试

#### 1. 测试健康检查
```bash
curl http://localhost:8080/health
# 预期: {"status":"healthy"}
```

#### 2. 测试村庄列表
```bash
curl http://localhost:8080/api/villages/
# 预期: 返回村庄列表数组
```

#### 3. 测试启动规划任务
```bash
curl -X POST http://localhost:8080/api/planning/start \
  -F "project_name=测试村" \
  -F "village_data=这是一些测试数据" \
  -F "task_description=制定村庄总体规划方案"
# 预期: 返回 {"task_id": "...", "status": "pending", "message": "..."}
```

#### 4. 测试任务状态查询
```bash
# 替换YOUR_TASK_ID为实际的任务ID
curl http://localhost:8080/api/planning/YOUR_TASK_ID
# 预期: 返回任务状态信息
```

#### 5. 测试层级内容获取
```bash
# 替换VILLAGE_NAME为实际村庄名
curl http://localhost:8080/api/villages/VILLAGE_NAME/layers/layer_1_analysis
# 预期: 返回combined分析内容
```

### 前端功能测试

#### 1. 访问首页
- 打开 http://localhost:3000
- 验证村庄列表显示
- 验证"新建规划任务"按钮
- 验证绿色主题样式

#### 2. 新建规划任务
- 点击"新建规划任务"
- 填写村庄/项目名称
- 上传文件或直接输入数据
- 点击"开始AI规划"
- 验证进度页面显示
- 验证完成后跳转到详情页

#### 3. 查看村庄详情
- 从首页点击村庄卡片
- 验证三层tab切换（现状分析、规划思路、详细规划）
- 验证层级内容正确显示
- 验证Markdown渲染

#### 4. 移动端/竖屏测试
- 使用Chrome DevTools模拟移动设备（F12 -> Toggle device toolbar）
- 测试iPhone SE, iPhone 12 Pro等设备
- 验证响应式布局
- 验证触摸友好的按钮（最小44px）
- 验证流程指示器垂直堆叠

---

## 样式验证

### 绿色主题
- 主色调: `#2e7d32` (primary-green)
- 次色调: `#388e3c` (secondary-green)
- 浅色调: `#8bc34a` (light-green)
- 背景色: `#e8f5e9` (background-green)
- 深色调: `#1b5e20` (dark-green)

### 响应式断点
- 移动端: < 576px
- 平板: 576px - 768px
- 桌面: 768px - 992px
- 大屏: > 992px

### 竖屏优化特性
- 流程指示器：垂直堆叠（竖屏）/ 水平排列（横屏）
- 按钮：最小44px高度（iOS推荐）
- Tab导航：适应窄屏的小字号
- 卡片内容：可滚动查看

---

## 生产部署

### 后端部署

```bash
# 使用gunicorn部署
cd backend
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8080
```

### 前端部署

```bash
# 构建生产版本
cd frontend
npm run build

# 启动生产服务器
npm start
# 或使用其他Node.js服务器如pm2
pm2 start npm --name "village-planning-frontend" -- start
```

### 环境变量配置

创建 `frontend/.env.local`:
```bash
NEXT_PUBLIC_API_URL=http://your-backend-url:8080
```

---

## 故障排查

### 后端问题

**问题**: 无法连接到API
- 检查后端是否启动: `curl http://localhost:8080/health`
- 检查端口占用: `netstat -ano | findstr :8080`
- 查看后端日志输出

**问题**: 规划任务失败
- 检查 `src/agent.py` 的依赖是否安装
- 检查环境变量配置（API密钥等）
- 查看后端日志中的详细错误信息

### 前端问题

**问题**: 页面空白或样式错误
- 清除浏览器缓存
- 检查开发者控制台错误（F12）
- 重新安装依赖: `rm -rf node_modules package-lock.json && npm install`

**问题**: 无法连接到后端
- 检查 `NEXT_PUBLIC_API_URL` 环境变量
- 检查CORS配置
- 验证后端API是否可访问

---

## 项目结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI后端
│   ├── main.py                # 应用入口
│   ├── schemas.py             # Pydantic模型
│   ├── requirements.txt       # Python依赖
│   ├── api/                   # API路由
│   │   ├── planning.py        # 规划API
│   │   └── villages.py        # 村庄API
│   └── services/              # 业务逻辑
│       ├── planning_service.py
│       └── file_service.py
│
├── frontend/                   # Next.js前端
│   ├── package.json           # 项目配置
│   ├── next.config.js         # Next.js配置
│   ├── tsconfig.json          # TypeScript配置
│   └── src/
│       ├── app/               # 页面（App Router）
│       │   ├── layout.tsx     # 根布局
│       │   ├── page.tsx       # 首页
│       │   └── villages/      # 村庄相关页面
│       │       ├── [name]/    # 村庄详情
│       │       └── new/       # 新建规划
│       ├── components/        # React组件
│       │   ├── BootstrapClient.tsx
│       │   ├── MarkdownRenderer.tsx
│       │   ├── LayerView.tsx
│       │   ├── FileUpload.tsx
│       │   └── PlanningProgress.tsx
│       ├── lib/               # 工具函数
│       │   └── api.ts         # API客户端
│       └── styles/            # 样式文件
│           └── globals.css    # 全局样式
│
├── src/                        # 原有Python代码
│   └── agent.py              # 主要规划函数
│
└── results/                    # 规划结果存储目录
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI + uvicorn |
| 异步任务 | BackgroundTasks |
| 前端框架 | Next.js 14 (App Router) |
| UI样式 | Bootstrap 5.3 + 绿色主题 |
| Markdown渲染 | react-markdown + remark-gfm |
| 实时通信 | SSE (EventSource) |
| 文件存储 | results/ 目录 |
| 类型检查 | TypeScript (前端) + Pydantic (后端) |

---

## 下一步建议

1. **安全性增强**:
   - 添加用户认证
   - 限制文件上传大小
   - 添加API速率限制
   - 使用HTTPS

2. **性能优化**:
   - 添加Redis缓存
   - 使用Celery处理长时间任务
   - 前端添加数据预加载
   - 实现虚拟滚动（大列表）

3. **功能扩展**:
   - 添加任务历史记录
   - 支持多文件批量上传
   - 添加规划结果导出（PDF/Word）
   - 实现规划结果可视化图表

4. **用户体验**:
   - 添加深色模式切换
   - 实现离线缓存（PWA）
   - 添加进度预估时间
   - 支持规划模板

---

## 联系方式

如有问题或建议，请联系项目维护者。
