# 配置与部署指南

本文档详细说明 Village Planning Agent 的配置和部署方式。

> **更新日期**: 2026-05-21
> **版本**: v1.0

## 目录

- [环境变量配置](#环境变量配置)
- [本地开发启动](#本地开发启动)
- [Docker 部署](#docker-部署)
- [生产环境部署](#生产环境部署)
- [常见问题](#常见问题)

---

## 环境变量配置

### 配置文件说明

| 文件 | 用途 | 位置 |
|------|------|------|
| `.env` | 后端环境变量（Docker 部署） | 项目根目录 |
| `.env.example` | 环境变量模板 | 项目根目录 |
| `frontend/.env.local` | 前端环境变量 | frontend 目录 |
| `frontend/.env.example` | 前端环境变量模板 | frontend 目录 |

### 快速配置

```bash
# 1. 复制环境变量模板
cp .env.example .env
cp frontend/.env.example frontend/.env.local

# 2. 编辑配置文件
# 填入你的 API Key
```

---

## 核心配置项

### LLM 配置

系统支持多种 LLM 提供商：

#### DeepSeek（推荐）

```env
LLM_PROVIDER=deepseek
OPENAI_API_KEY=your_deepseek_api_key_here
OPENAI_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_TOKENS=8192
```

#### OpenAI

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
# OPENAI_API_BASE 留空使用官方 API
LLM_MODEL=gpt-4o
MAX_TOKENS=8192
```

#### 智谱 AI（GLM）

```env
LLM_PROVIDER=zhipuai
ZHIPUAI_API_KEY=your_zhipuai_api_key_here
LLM_MODEL=glm-4-flash
MAX_TOKENS=8192
```

#### 阿里云 DashScope（通义千问）

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_dashscope_api_key
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.5-plus
MAX_TOKENS=65536
```

### Embedding 配置

系统支持两种 Embedding 方案：

#### 阿里云 DashScope（推荐，低内存）

```env
EMBEDDING_PROVIDER=aliyun
DASHSCOPE_API_KEY=your_dashscope_api_key
ALIYUN_EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024
```

**优势**：
- 无需本地模型，内存占用极低
- 适合低配服务器（2GB 内存即可）
- 镜像大小 ~1-2GB

#### 本地模型（高内存）

```env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
EMBEDDING_DEVICE=cpu
HF_ENDPOINT=https://hf-mirror.com
```

**注意**：
- 需要下载模型（~500MB）
- 内存占用 ~1-2GB
- 镜像大小 ~4-5GB

### GIS 配置

```env
# 天地图 API Key（服务端密钥）
TIANDITU_API_KEY=your_tianditu_api_key

# 高德地图 API Key
AMAP_API_KEY=your_amap_api_key
```

**获取方式**：
- 天地图：https://console.tianditu.gov.cn/
- 高德地图：https://console.amap.com/

### 前端配置

```env
# 后端 API 地址（浏览器可访问）
NEXT_PUBLIC_API_URL=http://localhost:8000

# 地图瓦片源
NEXT_PUBLIC_TILE_SOURCE=tianditu
```

---

## 本地开发启动

### 前置要求

- Python 3.11+
- Node.js 20+
- SQLite 3

### 步骤 1：安装依赖

```bash
# 后端依赖
pip install -r requirements-server.txt  # 精简版（推荐）
# 或
pip install -r requirements.txt         # 完整版（含本地模型）

# 前端依赖
cd frontend
npm install
```

### 步骤 2：配置环境变量

```bash
# 复制模板
cp .env.example .env
cp frontend/.env.example frontend/.env.local

# 编辑 .env 填入 API Key
```

### 步骤 3：启动服务

#### 方式一：使用启动脚本（Windows）

```bash
# 启动服务
start-services.bat

# 停止服务
stop-services.bat
```

#### 方式二：手动启动

```bash
# 终端 1：启动后端
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 终端 2：启动前端
cd frontend
npm run dev
```

### 访问地址

- 前端：http://localhost:3000
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs

---

## Docker 部署

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+

### 步骤 1：配置环境变量

```bash
# 复制模板
cp .env.example .env

# 编辑配置
vim .env
```

**关键配置**：

```env
# LLM 配置
LLM_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.5-plus

# Embedding 配置（推荐阿里云）
EMBEDDING_PROVIDER=aliyun
DASHSCOPE_API_KEY=your_dashscope_key

# 前端配置（重要！）
NEXT_PUBLIC_API_URL=http://YOUR_SERVER_IP:8000
ALLOWED_ORIGINS=http://YOUR_SERVER_IP:3000

# GIS 配置
TIANDITU_API_KEY=your_tianditu_key
AMAP_API_KEY=your_amap_key
```

### 步骤 2：构建并启动

```bash
# 构建镜像（首次或代码更新后）
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 步骤 3：验证部署

```bash
# 检查服务状态
docker-compose ps

# 健康检查
curl http://localhost:8000/api/health
```

### 镜像说明

| 镜像 | 大小 | 说明 |
|------|------|------|
| `village-planning-backend` | ~1-2GB | 精简版（阿里云 Embedding） |
| `village-planning-backend` | ~4-5GB | 完整版（本地模型） |
| `village-planning-frontend` | ~200MB | Next.js 生产镜像 |

### 构建选项

```bash
# 精简版（默认，推荐）
docker-compose build

# 完整版（含本地 Embedding 模型）
docker-compose build --build-arg EMBEDDING_PROVIDER=local
```

---

## 生产环境部署

### 架构建议

```
┌─────────────────────────────────────────────────────┐
│                    Nginx 反向代理                    │
│              (HTTPS + 静态资源缓存)                  │
└─────────────────────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
┌─────────────────┐             ┌─────────────────┐
│  Frontend       │             │  Backend        │
│  (Next.js)      │             │  (FastAPI)      │
│  Port: 3000     │             │  Port: 8000     │
└─────────────────┘             └─────────────────┘
         │                               │
         └───────────────┬───────────────┘
                         ▼
                ┌─────────────────┐
                │  Data Volume    │
                │  (SQLite + 文件) │
                └─────────────────┘
```

### Nginx 配置示例

```nginx
# /etc/nginx/sites-available/village-planning
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # 前端
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 支持
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }

    # SSE 流
    location /api/sessions/ {
        proxy_pass http://127.0.0.1:8000/api/sessions/;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }
}
```

### 生产环境变量

```env
# .env
ENVIRONMENT=production
USE_ASYNC_DATABASE=true

# LLM 配置
LLM_PROVIDER=openai
OPENAI_API_KEY=your_production_key
LLM_MODEL=qwen3.5-plus
MAX_TOKENS=65536

# 并发控制
LLM_MAX_CONCURRENT=50

# CORS（重要！）
ALLOWED_ORIGINS=https://yourdomain.com

# 前端 API 地址
NEXT_PUBLIC_API_URL=https://yourdomain.com
```

### 数据持久化

```yaml
# docker-compose.prod.yml
services:
  backend:
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./results:/app/results

  frontend:
    environment:
      - NEXT_PUBLIC_API_URL=https://yourdomain.com
```

---

## 配置项完整参考

### 后端配置项

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `LLM_PROVIDER` | ✅ | `deepseek` | LLM 提供商 |
| `OPENAI_API_KEY` | ✅ | - | OpenAI/DeepSeek API Key |
| `OPENAI_API_BASE` | - | - | API 基础 URL |
| `LLM_MODEL` | - | `qwen3.5-plus` | 模型名称 |
| `MAX_TOKENS` | - | `8192` | 最大 Token 数 |
| `LLM_MAX_CONCURRENT` | - | `50` | 最大并发请求数 |
| `EMBEDDING_PROVIDER` | - | `local` | Embedding 提供商 |
| `DASHSCOPE_API_KEY` | ✅* | - | 阿里云 API Key |
| `TIANDITU_API_KEY` | - | - | 天地图 API Key |
| `AMAP_API_KEY` | - | - | 高德地图 API Key |
| `ALLOWED_ORIGINS` | - | `http://localhost:3000` | CORS 允许源 |

### 前端配置项

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `NEXT_PUBLIC_API_URL` | ✅ | `http://localhost:8000` | 后端 API 地址 |
| `NEXT_PUBLIC_TILE_SOURCE` | - | `tianditu` | 地图瓦片源 |

---

## 常见问题

### 1. 前端无法连接后端

**症状**：前端页面加载，但 API 请求失败

**解决方案**：
1. 检查 `NEXT_PUBLIC_API_URL` 是否正确
2. 确保地址是浏览器可访问的（不是 Docker 内部网络）
3. 检查 `ALLOWED_ORIGINS` 是否包含前端地址

### 2. LLM 请求超时

**症状**：维度分析卡住，日志显示超时

**解决方案**：
1. 增加 `LLM_STREAM_TIMEOUT`（默认 300 秒）
2. 降低 `LLM_MAX_CONCURRENT`（避免限流）
3. 检查 API Key 是否有效

### 3. Embedding 模型加载失败

**症状**：启动时报错 "Model not found"

**解决方案**：
1. 使用阿里云 Embedding：`EMBEDDING_PROVIDER=aliyun`
2. 或预下载模型：
   ```bash
   export HF_ENDPOINT=https://hf-mirror.com
   python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"
   ```

### 4. Docker 容器健康检查失败

**症状**：容器不断重启

**解决方案**：
1. 查看日志：`docker-compose logs backend`
2. 检查端口冲突：`netstat -tlnp | grep 8000`
3. 检查数据目录权限

### 5. SSE 连接断开

**症状**：规划进度不更新

**解决方案**：
1. 检查 Nginx 配置是否禁用缓冲
2. 增加 `proxy_read_timeout`
3. 前端实现断线重连（已内置）

---

## 相关文档

- [01-system-overview](./01-system-overview.md) - 系统架构
- [04-backend-api](./04-backend-api.md) - API 文档
- [05-frontend-state](./05-frontend-state.md) - 前端架构