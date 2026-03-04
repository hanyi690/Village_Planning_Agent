# RAG 知识库构建 Dockerfile
# 用于在容器中构建和部署知识库
# 多阶段构建优化镜像大小

# ============================================
# Stage 1: Builder
# ============================================
FROM python:3.11-slim AS builder

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

# 使用阿里云 PyPI 镜像源加速
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================
# Stage 2: Production
# ============================================
FROM python:3.11-slim AS production

WORKDIR /app

# 使用阿里云 Debian 镜像源加速
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list

# Install runtime dependencies only
# LibreOffice 用于 .doc 文件转换（Docker/Linux 环境替代 Windows COM）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libreoffice-writer \
    libreoffice-core \
    libreoffice-common \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY src/ ./src/
COPY requirements.txt .

# Create non-root user and necessary directories
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/knowledge_base/chroma_db /app/data && \
    chown -R appuser:appuser /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ENVIRONMENT=production
ENV EMBEDDING_DEVICE=cpu
ENV VECTOR_DB_TYPE=chroma
# HuggingFace Configuration (use mirror for faster download in China)
ENV HF_ENDPOINT=https://hf-mirror.com
ENV EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5

# Switch to non-root user
USER appuser

# Expose port (for web interface if needed)
EXPOSE 8000

# Default command: build knowledge base
CMD ["python", "-m", "src.rag.build"]
