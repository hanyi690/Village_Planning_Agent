# 村庄规划系统 - 服务管理指南

## 环境配置

### 1. 复制配置文件

```bash
cp .env.example .env
```

### 2. 配置 LLM API

在 `.env` 文件中配置 LLM 服务：

```env
# DeepSeek (推荐)
OPENAI_API_KEY=your_deepseek_api_key
OPENAI_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# 或使用智谱 AI
# ZHIPUAI_API_KEY=your_zhipuai_api_key
# LLM_MODEL=glm-4-flash
```

### 3. 配置 Embedding 模型

支持两种 Embedding 方案：

#### 方案一：本地模型（默认）

```env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
EMBEDDING_DEVICE=cpu
HF_ENDPOINT=https://hf-mirror.com
```

#### 方案二：阿里云 Embedding API

```env
EMBEDDING_PROVIDER=aliyun
DASHSCOPE_API_KEY=your_dashscope_api_key
ALIYUN_EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024
```

| 配置项                     | 说明                                 |
| -------------------------- | ------------------------------------ |
| `EMBEDDING_PROVIDER`     | `local` 或 `aliyun`              |
| `DASHSCOPE_API_KEY`      | 阿里云百炼 API Key                   |
| `ALIYUN_EMBEDDING_MODEL` | 模型名称，推荐 `text-embedding-v4` |
| `EMBEDDING_DIMENSIONS`   | 向量维度，默认 1024                  |

> **注意**：切换 Embedding 方案后需要重建知识库，因为向量维度不同。

### 4. 知识库构建

```bash
# 首次使用或切换 Embedding 方案后执行
python src/rag/build.py
```

**知识库分类**：

知识库支持两类文档：

| 目录 | 类型 | 说明 |
|------|------|------|
| `data/policies/` | 政策文档 | 国家/地方政策、规划标准、法规文件 |
| `data/cases/` | 案例文档 | 规划案例、参考范例、实践总结 |

构建过程会：

1. 加载 `data/policies/` 下的政策文档
2. 加载 `data/cases/` 下的案例文档（如有）
3. 自动识别目录名作为文档类别 (category)
4. 切分文档并生成向量
5. 存储到 `knowledge_base/chroma_db/`

**支持的文档格式**：
- `.txt` - 纯文本
- `.md` - Markdown
- `.pdf` - PDF 文档
- `.docx`, `.doc` - Word 文档
- `.pptx`, `.ppt` - PowerPoint 演示文稿

**知识库工具**：

| 工具 | 功能 | 状态 |
|------|------|------|
| `list_available_documents` | 列出知识库文档 | ✅ 完成 |
| `document_overview_tool` | 获取文档概览 | ✅ 完成 |
| `chapter_content_tool` | 获取章节内容（三级详情） | ✅ 完成 |
| `knowledge_search_tool` | 知识检索（三种上下文模式） | ✅ 完成 |
| `key_points_search_tool` | 搜索关键要点 | ✅ 完成 |
| `full_document_tool` | 获取完整文档内容 | ✅ 完成 |

### 5. RAG 缓存配置

```env
# 查询缓存 TTL（秒），0 表示禁用缓存
QUERY_CACHE_TTL=3600
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `QUERY_CACHE_TTL` | 0 (禁用) | 查询结果缓存时间，单位秒 |

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
# Windows 用户 (PowerShell)
Get-Content logs\backend.log -Tail 50    # 查看后端最近日志
Get-Content logs\frontend.log -Tail 50   # 查看前端最近日志
Get-Content logs\backend.log -Wait       # 实时监控后端日志

# Linux/Mac 用户
tail -f logs/backend.log                 # 实时监控后端日志
tail -f logs/frontend.log                # 实时监控前端日志
tail -n 50 logs/backend.log              # 查看后端最近日志
tail -n 50 logs/frontend.log             # 查看前端最近日志
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
# Windows (PowerShell)
# 读取PID文件并停止
Stop-Process -Id (Get-Content logs\backend.pid) -ErrorAction SilentlyContinue
Stop-Process -Id (Get-Content logs\frontend.pid) -ErrorAction SilentlyContinue

# 或者直接查找进程
taskkill /F /IM python.exe
taskkill /F /IM node.exe

# Linux/Mac
# 读取PID文件并停止
kill $(cat logs/backend.pid)
kill $(cat logs/frontend.pid)

# 或者直接查找进程
pkill -f "uvicorn"
pkill -f "next dev"
```

## 测试修复

### 1. 访问前端

打开浏览器访问: http://localhost:3000

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
# Windows (PowerShell)
netstat -ano | findstr ":8000"           # 查找占用端口的进程
taskkill /F /PID <进程ID>                # 停止进程

# Linux/Mac
lsof -ti:8000 | xargs kill -9            # 停止占用 8000 端口的进程
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

### Q: Embedding 模型加载失败

**A**: 检查以下几点：

1. **本地模型**：确保网络可访问 HuggingFace 镜像

   ```bash
   # 测试镜像连接
   curl https://hf-mirror.com
   ```
2. **阿里云 API**：确保 `DASHSCOPE_API_KEY` 已正确配置

   ```bash
   # 验证配置
   python -c "from src.rag.config import DASHSCOPE_API_KEY; print(DASHSCOPE_API_KEY)"
   ```

### Q: 知识库查询无结果

**A**: 可能原因：

1. 知识库未构建：运行 `python src/rag/build.py`
2. 切换了 Embedding 方案但未重建：删除 `knowledge_base/chroma_db/` 后重新构建
3. 文档格式不支持：检查 `data/policies/` 目录下的文件格式

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
