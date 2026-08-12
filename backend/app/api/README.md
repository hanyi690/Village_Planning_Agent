# API transport

正式 transport 只有 `v1/`：

- `v1/routes.py`：state、SSE、human review、delivery、map layers、显式 artifact 读取；
- `v1/session_create.py`：创建会话命令；
- `v1/contracts.py`：前端公开 projection contract；
- `../data/ingestion/upload.py`：文件摄取和 GIS 质量审计。

路由不实例化图、Artifact Store 或 ReportStore，不扫描目录寻找最新文件。历史 `/api/sessions/*`
路由已经删除；新增 API 必须先更新蓝图和前端开发指南，再只增加 v1 contract。
