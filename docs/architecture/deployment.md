# 部署指南 (Deployment Guide)

> Village Planning Agent 系统配置与部署指南。
> 所有事实均从代码验证（`docker-compose.yml`、`.env.example`、`backend/app/core/settings.py`、`backend/app/main.py`、`start-services.bat`）。

---

## 1. 技术栈

| 组件 | 技术 | 版本要求 |
|---|---|---|
| 后端 | Python + FastAPI | Python 3.13+ |
| 前端 | Next.js + React | Node.js 18+，Next.js 14 |
| 数据库 | SQLite + WAL 模式 | 内置，无需独立部署 |
| 向量库 | ChromaDB | 内置持久化 |
| LLM | qwen-plus 系列（DashScope） | OpenAI 兼容接口 |
| Embedding | 阿里云 DashScope text-embedding-v4 | API 调用 |

---

## 2. 环境变量配置

### 2.1 核心配置表

复制 `.env.example` 为 `.env`，按下表填写。

#### LLM 配置

| 变量 | 说明 | 示例/默认值 |
|---|---|---|
| `LLM_PROVIDER` | LLM 提供商 | `deepseek` / `openai` / `zhipuai` |
| `OPENAI_API_KEY` | API 密钥（兼容 DeepSeek/DashScope） | 你的密钥 |
| `OPENAI_API_BASE` | API 基础 URL | `https://dashscope.aliyuncs.com/compatible-mode/v1`（DashScope） |
| `LLM_MODEL` | 模型名称 | qwen-plus 系列 |
| `MAX_TOKENS` | 最大 token 数 | `8192`（默认）/ `65536`（Docker 默认） |
| `LLM_MAX_CONCURRENT` | LLM 最大并发请求 | `50`（DashScope 限制 500 RPS / 30000 RPM） |
| `LLM_STREAM_TIMEOUT` | 流式超时（秒） | `300` |
| `LLM_REQUEST_TIMEOUT` | 请求超时（秒） | `180` |

**支持的 LLM 提供商**：
- **DashScope（qwen-plus 系列）**：`OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1`（推荐）
- **DeepSeek**：`OPENAI_API_BASE=https://api.deepseek.com/v1`，`LLM_MODEL=deepseek-chat`
- **OpenAI**：`OPENAI_API_BASE` 留空，`LLM_MODEL=gpt-4o`
- **ZhipuAI（GLM）**：`LLM_PROVIDER=zhipuai`，`ZHIPUAI_API_KEY=你的密钥`，`LLM_MODEL=glm-4-flash`

#### Embedding 配置

| 变量 | 说明 | 示例/默认值 |
|---|---|---|
| `EMBEDDING_PROVIDER` | Embedding 提供商 | `aliyun`（推荐，API 调用，内存低） / `local`（HuggingFace） |
| `DASHSCOPE_API_KEY` | DashScope API 密钥 | 你的密钥 |
| `ALIYUN_EMBEDDING_MODEL` | 阿里云 Embedding 模型 | `text-embedding-v4` |
| `EMBEDDING_DIMENSIONS` | 向量维度 | `1024`（v4 支持 2048/1536/1024/768/512/256/128/64） |
| `EMBEDDING_MAX_CONCURRENT` | Embedding 最大并发 | `10` |
| `EMBEDDING_RATE_LIMIT_RPS` | Embedding 速率限制 | `25` |

#### 多模态（视觉）配置

| 变量 | 说明 | 默认值 |
|---|---|---|
| `MULTIMODAL_ENABLED` | 启用图像分析 | `true` |
| `MULTIMODAL_MODEL` | 多模态模型 | qwen-plus 系列（含视觉能力） |
| `OCR_MODEL_NAME` | OCR/视觉模型 | `qwen-vl-max` |
| `IMAGE_DETAIL_LEVEL` | 图像细节级别 | `auto` |
| `MAX_IMAGE_SIZE_MULTIMODAL` | 最大图像大小（字节） | `10000000` |

#### GIS 服务配置

| 变量 | 说明 | 默认值 |
|---|---|---|
| `TIANDITU_API_KEY` | 天地图 API 密钥（服务端） | 必填 |
| `TIANDITU_RATE_LIMIT` | 天地图速率限制（QPS） | `5.0` |
| `AMAP_API_KEY` | 高德地图 API 密钥 | 可选 |
| `AMAP_RATE_LIMIT` | 高德速率限制（QPS） | `30.0` |
| `GD_TIANDITU_TOKEN` | 广东省天地图 Token | 可选 |
| `GIS_TILE_SOURCE` | 地图瓦片源 | `tianditu` |

#### 数据库与日志

| 变量 | 说明 | 默认值 |
|---|---|---|
| `USE_ASYNC_DATABASE` | 异步数据库 | `true` |
| `ENVIRONMENT` | 环境 | `production` / `development` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `LOG_RETENTION_DAYS` | 日志保留天数（自动清理） | `30` |
| `LOG_FILE_MAX_BYTES` | 单日志文件最大字节 | `10485760`（10MB） |

#### CORS 配置

| 变量 | 说明 | 默认值 |
|---|---|---|
| `ALLOWED_ORIGINS` | CORS 允许来源（逗号分隔） | `http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:8000` |

> **生产部署**：务必将 `ALLOWED_ORIGINS` 改为你的公网前端地址。

#### 前端配置

| 变量 | 说明 | 示例 |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | 后端 API URL（浏览器可访问） | 本地：`http://localhost:8000`；生产：`http://YOUR_SERVER_IP:8000` |

> **重要**：`NEXT_PUBLIC_API_URL` 必须从浏览器可访问，不是 Docker 内部网络地址。

### 2.2 Docker 专用端口变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `BACKEND_PORT` | 后端宿主端口 | `8003` |
| `FRONTEND_PORT` | 前端宿主端口 | `3003` |

---

## 3. 本地开发启动

### 3.1 前置准备

```bash
# 后端依赖
cd backend
pip install -r requirements.txt

# 前端依赖
cd frontend
npm install
```

### 3.2 启动命令

**方式一：分别启动**

```bash
# 后端（端口 8000）
python backend/main.py

# 前端（端口 3000）
cd frontend && npm run dev
```

访问 http://localhost:3000

**方式二：Windows 一键启动**

```batch
start-services.bat
```

该脚本在独立窗口启动后端（`uvicorn app.main:app --host 0.0.0.0 --port 8000`）和前端（`npm run dev`），并创建 `logs/` 目录。

**停止服务（Windows）**：

```batch
stop-services.bat
```

该脚本按端口（8000/3000/3001）杀死进程树，清理孤立的 uvicorn/python 进程，并验证端口已释放。

### 3.3 日志

后端使用 `TimedRotatingFileHandler` 按日轮转：

| 日志文件 | 内容 | 轮转 |
|---|---|---|
| `logs/planning.log` | 全量日志 | 每日午夜，保留 `LOG_RETENTION_DAYS` 天 |
| `logs/planning.error.log` | 仅 ERROR 及以上 | 每日午夜，保留 `LOG_RETENTION_DAYS` 天 |
| 控制台 | 实时输出 | — |

启动时自动清理超过 `LOG_RETENTION_DAYS` 的旧日志文件。

---

## 4. Docker 部署

### 4.1 配置

1. 复制环境文件：
   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env`，填写：
   - `OPENAI_API_KEY` / `DASHSCOPE_API_KEY`（LLM + Embedding）
   - `TIANDITU_API_KEY`（GIS 服务）
   - `NEXT_PUBLIC_API_URL`（后端公网地址）
   - `ALLOWED_ORIGINS`（前端公网地址）

### 4.2 启动

```bash
docker-compose up -d
```

### 4.3 服务映射

| 服务 | 容器端口 | 宿主端口（默认） | 健康检查 |
|---|---|---|---|
| backend | 8000 | `BACKEND_PORT`（默认 8003） | `curl -f http://localhost:8000/api/health` |
| frontend | 3000 | `FRONTEND_PORT`（默认 3003） | `curl -f http://localhost:3000` |

frontend 依赖 backend 健康检查通过后启动。

### 4.4 数据卷

| 宿主路径 | 容器路径 | 用途 |
|---|---|---|
| `./data` | `/app/data` | GIS 数据、知识库、数据库 |
| `./logs` | `/app/logs` | 日志文件 |
| `./results` | `/app/results` | 规划输出结果 |

### 4.5 Docker 环境变量

Docker Compose 额外注入以下环境变量到 backend 容器：

- `PROJECT_ROOT=/app`
- `ENVIRONMENT=production`
- `USE_ASYNC_DATABASE=true`
- `MULTIMODAL_ENABLED=true`
- `GRAPH_MAX_CONCURRENCY=50`
- `MINERU_TOKEN`（文档解析）

### 4.6 生产部署（HTTPS）

使用 Nginx 反向代理实现 HTTPS：

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 5. 数据库

- **引擎**：SQLite，启用 **WAL 模式**（Write-Ahead Logging）以提高并发写入安全性
- **配置**：`USE_ASYNC_DATABASE=true` 启用异步数据库操作
- **位置**：`data/database/` 目录
- **Checkpointer**：LangGraph 检查点同样启用 WAL 模式
- **无需独立部署**：SQLite 内置于 Python，无需额外数据库服务

---

## 6. RAG 知识库构建

### 6.1 源文档

源文档目录：`data/policies/`

支持的文档格式：`.md`、`.txt`、`.pdf`、`.pptx`、`.ppt`、`.docx`、`.doc`

### 6.2 构建知识库

首次全量构建：

```bash
python src/rag/scripts/build_kb_auto.py
```

### 6.3 知识库管理（增量）

```bash
# 列出文档
python -m src.rag.scripts.kb_cli list

# 添加文档
python -m src.rag.scripts.kb_cli add <文件路径>

# 删除文档
python -m src.rag.scripts.kb_cli delete <文件名>

# 同步源目录
python -m src.rag.scripts.kb_cli sync
```

### 6.4 RAG 服务管理 CLI

后端 RAG 模块提供管理 CLI（`backend/app/modules/rag/cli.py`）：

```bash
# 知识库统计
python -m app.modules.rag.cli status

# 删除文档（ChromaDB + 所有缓存）
python -m app.modules.rag.cli delete <source_name>

# 重新导入（删除旧数据 + 标准管道重导）
python -m app.modules.rag.cli reload <file_path>

# 一致性校验（hash/metadata/chunks）
python -m app.modules.rag.cli verify <source_name>
```

### 6.5 文档解析器

| 解析器 | 质量 | 说明 |
|---|---|---|
| `mineru`（默认） | 最佳 | 云端 API，需 `MINERU_TOKEN` |
| `docling` | 中 | 本地，可选 CUDA 加速 |
| `markitdown` | 快 | 快速解析 |

通过 `DOCUMENT_PARSER` 环境变量选择。

### 6.6 向量存储

- **类型**：ChromaDB（默认）/ FAISS / Qdrant
- **持久化目录**：`data/RAG_doc/_cache/chroma_db_new`
- **集合名**：`rural_planning`（`CHROMA_COLLECTION_NAME`）
- **Embedding**：阿里云 `text-embedding-v4`，维度 1024

---

## 7. 项目目录结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── main.py             # 应用入口
│   │   ├── core/settings.py    # 配置（所有环境变量读取）
│   │   ├── modules/            # 五层架构模块
│   │   ├── agent/              # LangGraph Agent
│   │   └── ...
│   └── Dockerfile
├── frontend/                   # Next.js 前端
│   ├── package.json
│   └── Dockerfile
├── data/
│   ├── policies/               # RAG 源文档
│   ├── gis/                    # GIS 数据
│   ├── RAG_doc/_cache/         # 向量库缓存
│   └── database/               # SQLite 数据库
├── logs/                       # 日志（自动创建）
├── docker-compose.yml
├── .env.example
├── start-services.bat          # Windows 启动脚本
└── stop-services.bat           # Windows 停止脚本
```

---

## 8. 快速验证

启动后检查：

| 检查项 | 命令/URL | 预期 |
|---|---|---|
| 后端健康 | `curl http://localhost:8000/api/health` | 200 OK |
| 前端 | http://localhost:3000 | 页面加载 |
| 日志 | `logs/planning.log` | 有启动日志 |
| 错误日志 | `logs/planning.error.log` | 无 ERROR |

---

## 9. 常见问题

### 9.1 LLM 429/503 错误

DashScope 并发限制。降低 `LLM_MAX_CONCURRENT`（建议 3-4 保持稳定），或开启冷启动预热（`LLM_WARMUP_SECONDS`）。

### 9.2 Embedding API 超时

`text-embedding-v4` 限制约 30 QPS。已内置批处理（BATCH_SIZE=10）和速率限制（`EMBEDDING_RATE_LIMIT_RPS=25`）。输入长度限制 8192 tokens（约 7500 中文字符）。

### 9.3 端口占用

`stop-services.bat` 按端口杀死进程。手动检查：
```bash
netstat -ano | findstr ":8000 :3000 :3001"
```

### 9.4 天地图 API 无法访问

- 确认 `TIANDITU_API_KEY` 已配置
- 天地图需在控制台配置 IP 白名单
- 广东省专题服务可配置 `GD_TIANDITU_TOKEN`
