# DashScope / 阿里云百炼配置说明

本版本已配置为使用阿里云百炼 OpenAI 兼容接口：

- `LLM_PROVIDER=openai`
- `OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1`
- `LLM_MODEL=qwen3.5-plus`
- `DASHSCOPE_API_KEY` 与 `OPENAI_API_KEY` 使用同一个百炼 API Key
- `LLM_ENABLE_THINKING=false`：默认关闭 Qwen thinking mode，避免右侧消息栏出现 `content=''`、`token_usage`、`response_metadata` 等元数据内容。

## 安全提醒

根目录 `.env` 包含真实 API Key。不要上传到 GitHub，不要发给别人。`.gitignore` 已经忽略 `.env`，但手动打包或复制时仍需要注意。

## 启动

后端：

```powershell
cd "项目根目录"
.\.venv\Scripts\activate
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd "项目根目录\frontend"
npm run dev
```

## 关于虚拟环境

如果新压缩包和旧项目使用同一份 `requirements.txt`，原则上可以复用旧的 `.venv`。但是最稳的方法是：每个完整解压的新项目目录使用自己的 `.venv`。这样不会因为不同版本依赖混在一起导致奇怪错误。
