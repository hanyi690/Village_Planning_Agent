# 部署架构

> **更新日期**: 2026-05-08
> **版本**: v2.0 (重组后架构)

本文档详细说明Docker Compose配置和环境变量。

## 目录

- [Docker Compose配置](#docker-compose配置)
- [环境变量](#环境变量)
- [网络架构](#网络架构)
- [健康检查](#健康检查)

---

## Docker Compose配置

### 服务架构

```yaml
# docker-compose.yml
services:
  backend:
    image: village-planning-backend:latest
    ports: ["8000:8000"]
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]

  frontend:
    image: village-planning-frontend:latest
    ports: ["3000:3000"]
    depends_on:
      backend: {condition: service_healthy}
```

---

## 环境变量

### Backend环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| ENVIRONMENT | 运行环境 | production |
| LLM_MODEL | LLM模型 | qwen3.5-plus |
| LLM_PROVIDER | LLM提供商 | openai |
| LLM_MAX_CONCURRENT | 并发数 | 4 |
| TIANDITU_API_KEY | 天地图Key | - |
| AMAP_API_KEY | 高德Key | - |
| DASHSCOPE_API_KEY | 阿里云Embedding Key | - |

### Frontend环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| NODE_ENV | Node环境 | production |
| NEXT_PUBLIC_API_URL | API地址 | http://localhost:8000 |

---

## 网络架构

```yaml
networks:
  village-planning-network:
    driver: bridge
```

```
Frontend (3000) -> Backend (8000) -> SQLite/ChromaDB
```

---

## 健康检查

### Backend

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

### Frontend

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:3000"]
  depends_on:
    backend: {condition: service_healthy}
```

---

## 资源限制

| 服务 | CPU限制 | 内存限制 |
|------|---------|----------|
| backend | 2核 | 2GB |
| frontend | 1核 | 1GB |

---

## 关键文件路径

| 文件 | 说明 |
|------|------|
| `docker-compose.yml` | 开发环境配置 |
| `docker-compose.prod.yml` | 生产环境配置 |
| `.env` | 环境变量文件 |

---

## 相关文档

- [04-backend-api](./04-backend-api.md) - Backend API
- [11-security](./11-security.md) - API Key管理