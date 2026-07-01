# Village Planning Agent - Docker Compose 部署设计

## 概述

将 Village Planning Agent 部署到远程服务器 (183.36.243.124)，使用 Docker Compose 一体化方案，IP:Port 直接访问，无需 HTTPS/Nginx。

## 架构

```
服务器 183.36.243.124 (Ubuntu 22.04, Docker 29.5.2, Compose v5.1.4)
├── ~/village-planning/Village_Planning_Agent/
│   ├── .env                          (生产环境配置)
│   ├── docker-compose.yml            (容器编排)
│   ├── backend/Dockerfile            (后端镜像)
│   ├── frontend/Dockerfile           (前端镜像)
│   └── data/
│       ├── RAG_doc/_cache/           (ChromaDB + 索引缓存)
│       │   ├── chroma_db_new/        (向量数据库, ~229MB)
│       │   ├── outline_index/        (树形索引 JSON)
│       │   └── hierarchy_chunks_cache.json
│       ├── database/                 (SQLite, 自动创建)
│       └── knowledge_base/           (空, 自动创建)
│
├── Container: village-planning-backend:8000
│   ├── FastAPI + Uvicorn
│   ├── LangGraph Agent Runtime
│   ├── ChromaDB (local persist)
│   ├── DashScope Embedding API (text-embedding-v4)
│   └── DashScope LLM (qwen3.5-plus)
│
└── Container: village-planning-frontend:3000
    └── Next.js standalone server
```

**数据流**:
浏览器 → http://183.36.243.124:3000 (前端) → /api/* rewrites → backend:8000 → LLM(DashScope) + ChromaDB

## 部署步骤

### Step 1: 服务器准备 (已完成)

```bash
ssh zhong@183.36.243.124
mkdir -p ~/village-planning
cd ~/village-planning
git clone https://github.com/hanyi690/Village_Planning_Agent.git
cd Village_Planning_Agent
```

### Step 2: 配置 .env

从 .env.example 复制并修改关键配置：

```bash
cp .env.example .env
```

**必须修改的配置项**:

| 配置项              | 值                                               | 原因                 |
| ------------------- | ------------------------------------------------ | -------------------- |
| NEXT_PUBLIC_API_URL | http://183.36.243.124:8000                       | 浏览器需要访问外部IP |
| ALLOWED_ORIGINS     | http://183.36.243.124:3000,http://localhost:3000 | CORS允许前端来源     |

**API密钥配置** (与本地相同，直接复制 .env):

| 配置项            | 说明                                              |
| ----------------- | ------------------------------------------------- |
| OPENAI_API_KEY    | DashScope API Key (qwen3.5-plus)                  |
| OPENAI_API_BASE   | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| DASHSCOPE_API_KEY | Embedding API Key (text-embedding-v4)             |
| TIANDITU_API_KEY  | 天地图 API Key                                    |
| AMAP_API_KEY      | 高德 API Key                                      |
| MINERU_TOKEN      | MinerU 文档解析 Token                             |

### Step 3: 拷贝 ChromaDB 数据

从本地开发机 scp 到服务器：

```bash
# 在本地执行
scp -r data/RAG_doc/_cache/ zhong@183.36.243.124:~/village-planning/Village_Planning_Agent/data/RAG_doc/_cache/
```

包含内容:

- chroma_db_new/ (~229MB, 向量数据库)
- outline_index/ (树形索引 JSON 缓存)
- hierarchy_chunks_cache.json (父块缓存)

**注意**: 需确保服务器上 `data/RAG_doc/_cache/` 目录结构完整，否则 RAG 检索将返回空结果。

### Step 4: 修改 docker-compose.yml

关键修改:

1. **前端构建参数**: `NEXT_PUBLIC_API_URL` 改为外部IP
2. **后端环境变量**: 补充所有 API Key 传递
3. **前端运行环境**: `NEXT_PUBLIC_API_URL` 同步修改

```yaml
frontend:
  build:
    args:
      - NEXT_PUBLIC_API_URL=http://183.36.243.124:8000
  environment:
    - NEXT_PUBLIC_API_URL=http://183.36.243.124:8000

backend:
  environment:
    # 补充缺失的环境变量
    - DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY}
    - MINERU_TOKEN=${MINERU_TOKEN}
    - TIANDITU_API_KEY=${TIANDITU_API_KEY}
    - AMAP_API_KEY=${AMAP_API_KEY}
    - ALIYUN_EMBEDDING_MODEL=${ALIYUN_EMBEDDING_MODEL:-text-embedding-v4}
    - EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-1024}
    - MULTIMODAL_ENABLED=${MULTIMODAL_ENABLED:-true}
    - OCR_MODEL_NAME=${OCR_MODEL_NAME:-qwen-vl-max}
```

### Step 5: 构建并启动

```bash
docker compose up -d --build
```

首次构建耗时约 10-15 分钟 (后端需安装 Python 依赖 + GDAL，前端需 npm install + build)。

### Step 6: 验证部署

```bash
# 后端健康检查
curl http://183.36.243.124:8000/health
# 预期: {"status":"healthy","service":"village-planning-backend","version":"1.0.0"}

# 前端页面检查
curl -s http://183.36.243.124:3000 | head -5

# RAG 知识库检查
curl http://183.36.243.124:8000/api/knowledge/stats

# Docker 容器状态
docker compose ps
docker compose logs --tail=50 backend
```

## RAG 配置详解

### 当前架构

- **Embedding**: 阿里云 DashScope API (`text-embedding-v4`, 1024维)
  - 无需本地模型，内存占用极低
  - 速率限制: 25 rps, 10 并发 (已在代码中配置)
- **向量存储**: ChromaDB (本地持久化, `data/RAG_doc/_cache/chroma_db_new/`)
  - Small-to-Big 检索架构 (子块检索，父块返回上下文)
  - 层级感知 (树形索引 outline_index)
- **文档解析**: MinerU (云API) → Docling (本地fallback) → MarkItDown (快速fallback)
- **查询生成**: LLM Flash (qwen-flash) 动态生成检索查询

### 部署后 RAG 工作流

1. 用户发起规划请求 → Agent 调用 `RagService.get_context()`
2. `RagService` 使用 Flash LLM 生成查询 → ChromaDB 检索
3. ChromaDB 使用 DashScope API 生成查询向量 → 返回相似文档
4. 文档上下文注入 Agent Prompt → LLM 生成规划报告

### RAG 知识库管理

- **查看**: `GET /api/knowledge/stats` - 返回文档数量和切片统计
- **上传**: `POST /api/knowledge/upload` - 上传新文档，自动解析+切片+入库
- **删除**: `DELETE /api/knowledge/documents/{source}` - 删除指定文档

### 无需额外 RAG 配置

只要 `.env` 中 `DASHSCOPE_API_KEY` 正确且 ChromaDB 数据已拷贝，RAG 即可工作。

## NEXT_PUBLIC_API_URL 关键说明

Next.js 的 `NEXT_PUBLIC_*` 环境变量在**构建时**烧入前端 JavaScript，运行时无法修改。

当前问题: docker-compose.yml 中 `NEXT_PUBLIC_API_URL=http://backend:8000` 使用 Docker 内部域名，浏览器无法解析。

解决方案:

1. 构建时传入外部IP: `NEXT_PUBLIC_API_URL=http://183.36.243.124:8000`
2. 前端 `next.config.js` 的 rewrites 配置了 `/api/*` → backend 作为内部代理备用

**如果服务器IP变更**: 需要重新构建前端镜像 (`docker compose up -d --build frontend`)。

## 数据持久化

docker-compose.yml 已配置 volumes:

| 宿主机路径 | 容器路径     | 内容                               |
| ---------- | ------------ | ---------------------------------- |
| ./data     | /app/data    | ChromaDB + SQLite + knowledge_base |
| ./logs     | /app/logs    | 应用日志                           |
| ./results  | /app/results | 规划结果输出                       |

容器重启/重建不会丢失数据。`docker compose down` 不会删除 volumes 映射的宿主机目录。

## 日常运维

```bash
# 查看日志
docker compose logs -f backend
docker compose logs -f frontend

# 重启服务
docker compose restart

# 更新代码后重新构建
git pull
docker compose up -d --build

# 停止服务
docker compose down

# 清理旧镜像
docker image prune -f

# 查看资源占用
docker stats
```

## 故障排查

| 问题             | 检查方法                                         | 解决方案                              |
| ---------------- | ------------------------------------------------ | ------------------------------------- |
| 后端启动失败     | `docker compose logs backend`                  | 检查 .env 配置、端口占用              |
| 前端无法连接后端 | 浏览器 F12 Network                               | 检查 NEXT_PUBLIC_API_URL 是否为外部IP |
| RAG 返回空结果   | `curl /api/knowledge/stats`                    | 检查 ChromaDB 数据是否完整            |
| Embedding 报错   | `docker compose logs backend \| grep Embedding` | 检查 DASHSCOPE_API_KEY                |
| LLM 超时         | `docker compose logs backend \| grep timeout`   | 检查网络连接到 DashScope              |
| CORS 错误        | 浏览器 F12 Console                               | 检查 ALLOWED_ORIGINS 配置             |

## 服务器资源需求

| 资源 | 最低要求               | 推荐配置     |
| ---- | ---------------------- | ------------ |
| CPU  | 2 核                   | 4 核         |
| 内存 | 4 GB                   | 8 GB         |
| 磁盘 | 10 GB (代码+镜像+数据) | 20 GB        |
| 网络 | 需访问 DashScope API   | 稳定外网连接 |

当前服务器: 412GB 磁盘 (131GB 已用, 261GB 可用)，资源充足。
