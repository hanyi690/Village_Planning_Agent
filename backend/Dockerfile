# Backend Dockerfile for Village Planning Agent
# Multi-stage build for optimized image size
#
# 构建命令:
#   docker build -t village-planning-backend .

# ============================================
# Stage 1: Builder
# ============================================
FROM python:3.11-slim as builder

WORKDIR /app

# 使用阿里云 Debian 镜像源加速（国内部署优化）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list

# Install build dependencies (including GDAL for geopandas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgdal-dev \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements file
COPY requirements.txt .

# 使用阿里云 PyPI 镜像源加速（国内部署优化）
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================
# Stage 2: Production
# ============================================
FROM python:3.11-slim as production

WORKDIR /app

# 使用阿里云 Debian 镜像源加速（国内部署优化）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list

# Install runtime dependencies (GDAL runtime, LibreOffice for .doc conversion, Pandoc for MD→DOCX, Tesseract for OCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gdal-bin \
    libreoffice-writer \
    libreoffice-core \
    libreoffice-common \
    pandoc \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set Tesseract data path for Docling OCR
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code (unified backend/app structure)
COPY backend/app/ ./app/

# Create non-root user and directories
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/data /app/logs /app/results && \
    chown -R appuser:appuser /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ENVIRONMENT=production
ENV USE_ASYNC_DATABASE=true

# Embedding Configuration: 使用阿里云 DashScope API
# 通过 docker-compose.yml 或 .env 设置:
#   EMBEDDING_PROVIDER=aliyun
#   DASHSCOPE_API_KEY=your_api_key
#   ALIYUN_EMBEDDING_MODEL=text-embedding-v4

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application (unified backend/app structure)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
