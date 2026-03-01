# Backend Dockerfile for Village Planning Agent
# Multi-stage build for optimized image size

# ============================================
# Stage 1: Builder
# ============================================
FROM python:3.11-slim as builder

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

# Copy requirements files
COPY requirements.txt .
COPY backend/requirements.txt ./backend/

# 使用阿里云 PyPI 镜像源加速（国内部署优化）
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
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

# HuggingFace Configuration
# Use /app/models for model storage (persistent via volume mount)
ENV HF_HOME=/app/models
ENV HF_ENDPOINT=https://hf-mirror.com
ENV EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
ENV EMBEDDING_DEVICE=cpu

# Pre-download Embedding model during build
# Use HF_HOME to store in /app/models (not in user home)
# Switch to appuser for download to ensure correct permissions
USER appuser
RUN python -c "\nimport os; \nos.environ['HF_HOME'] = '/app/models'; \nos.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'; \nfrom sentence_transformers import SentenceTransformer; \nprint('Downloading Embedding model...'); \nSentenceTransformer('BAAI/bge-small-zh-v1.5'); \nprint('Model downloaded successfully')"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]