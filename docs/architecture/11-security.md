# 安全架构

> **更新日期**: 2026-05-08
> **版本**: v2.0 (重组后架构)

本文档说明API Key管理策略和数据安全措施。

## API Key管理

### Key类型

| Key | 用途 | 存储方式 |
|-----|------|----------|
| OPENAI_API_KEY | LLM调用 | .env文件 |
| TIANDITU_API_KEY | 天地图WFS | .env文件 |
| AMAP_API_KEY | 高德API | .env文件 |
| DASHSCOPE_API_KEY | 阿里云Embedding | .env文件 |

### 安全措施

- `.env`文件不提交到Git
- 生产环境通过环境变量注入
- Key不在代码中硬编码

## 数据安全

- SQLite数据库启用WAL模式
- Checkpoint数据存储在本地
- 不存储用户敏感信息

---

## 相关文档

- [10-deployment](./10-deployment.md) - 环境变量配置