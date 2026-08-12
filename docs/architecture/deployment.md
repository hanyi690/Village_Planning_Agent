# 当前运行与部署

> 本文只保留当前启动入口。生产部署参数、密钥和 provider 选择以
> `docker-compose.yml`、`.env.example` 和运行环境为准。

## 本地启动

```powershell
# backend
Set-Location backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend（另开终端）
Set-Location frontend
npm run dev
```

FastAPI lifespan 在启动期间初始化数据库、组合根、`PlanningRuntimeService` 和事件循环；
启动失败会把 readiness 标记为 failed。应用关闭时由 lifespan 释放 runtime、数据库和 KG
worker pool 资源。

## Docker

```powershell
Copy-Item .env.example .env
docker compose up -d
docker compose ps
docker compose logs -f
```

不要在文档中复制一份可能过期的端口、镜像或环境变量清单；以 compose 文件为准。

## 必要配置

- LLM provider 与对应 key；
- 数据库和 checkpoint 存储路径；
- RAG/embedding 配置（启用时）；
- 地图 provider key（使用瓦片代理时）；
- `ALLOWED_ORIGINS` 和日志目录。

密钥只放在本地 `.env` 或部署平台 secret 中，不提交到仓库。

## 健康检查

- `/health`：进程级存活信息；
- `/api/health`：数据库、checkpointer、LangGraph readiness；
- `/docs`、`/redoc`：当前 OpenAPI 参考。

部署验证先运行：

```powershell
python -m pytest backend/tests/contracts backend/tests/core -q
```

真实 provider、checkpoint 重启和地图交付属于独立验收，不因容器启动成功而自动通过。
