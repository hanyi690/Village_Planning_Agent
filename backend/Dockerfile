# Backend Dockerfile for Village Planning Agent
# Multi-stage build for optimized image size
#
# 构建选项:
#   docker build -t village-planning-backend .  # 默认精简版 (~1-2GB)
#   docker build --build-arg EMBEDDING_PROVIDER=local -t village-planning-backend .  # 完整版 (~4-5GB)

# ============================================
# Stage 1: Builder
# ============================================
FROM python:3.11-slim as builder

# 构建参数: 选择 embedding 模式
# - server: 精简版，使用阿里云 API（默认，镜像 ~1-2GB）
# - local: 完整版，支持本地模型（镜像 ~4-5GB）
ARG EMBEDDING_PROVIDER=server

WORKDIR /app

# 使用阿里云 Debian 镜像源加速（国内部署优化）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy all requirements files
COPY requirements.txt .
COPY requirements-server.txt .
COPY backend/requirements.txt ./backend/

# 使用阿里云 PyPI 镜像源加速（国内部署优化）
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

# Install Python dependencies based on EMBEDDING_PROVIDER
RUN pip install --no-cache-dir --upgrade pip && \
    if [ "$EMBEDDING_PROVIDER" = "local" ]; then \
        echo "Installing FULL requirements (local embedding support)..." && \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        echo "Installing SERVER requirements (aliyun embedding, no local models)..." && \
        pip install --no-cache-dir -r requirements-server.txt; \
    fi && \
    pip install --no-cache-dir -r backend/requirements.txt

# ============================================
# Stage 2: Production
# ============================================
FROM python:3.11-slim as production

WORKDIR /app

# 使用阿里云 Debian 镜像源加速（国内部署优化）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY backend/ ./backend/
COPY src/ ./src/
COPY requirements.txt .

# Create non-root user and directories
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/data /app/logs /app/results /app/knowledge_base /app/models && \
    chown -R appuser:appuser /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ENVIRONMENT=production
ENV USE_ASYNC_DATABASE=true

# Embedding Configuration (set via environment variables in docker-compose.yml)
# EMBEDDING_PROVIDER=local: uses HuggingFace local model (requires ~1-2GB RAM)
# EMBEDDING_PROVIDER=aliyun: uses Aliyun DashScope API (minimal RAM, recommended for low-memory servers)
# 
# For local embedding, set these in docker-compose.yml:
#   HF_HOME=/app/models
#   HF_ENDPOINT=https://hf-mirror.com
#   EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
#   EMBEDDING_DEVICE=cpu
#
# For aliyun embedding, set these in docker-compose.yml:
#   EMBEDDING_PROVIDER=aliyun
#   DASHSCOPE_API_KEY=your_api_key
#   ALIYUN_EMBEDDING_MODEL=text-embedding-v4

# Model will be loaded at runtime from mounted volume or downloaded on first run
# Pre-downloading during build causes large image size and build failures
# Use: docker-compose with ./models:/app/models volume mount
# Or: set HF_HOME to local path and download before deployment

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
