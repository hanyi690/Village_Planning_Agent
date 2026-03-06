# Frontend Dockerfile for Village Planning Agent
# Multi-stage build for optimized image size

# ============================================
# Stage 1: Dependencies
# ============================================
# 使用 Debian-slim 替代 Alpine，支持 Tailwind CSS v4 的原生绑定 (@tailwindcss/oxide)
FROM node:18-slim AS deps

WORKDIR /app

# Copy package files
COPY package.json package-lock.json* ./

# 使用阿里云 npm 镜像源加速（国内部署优化）
RUN npm config set registry https://registry.npmmirror.com

# Install dependencies (including devDependencies for build)
# 删除 Windows 平台的 package-lock.json，强制重新解析依赖
# 这样 npm 会下载适合 Linux 平台的原生模块 (@tailwindcss/oxide)
RUN rm -f package-lock.json && npm install

# ============================================
# Stage 2: Builder
# ============================================
FROM node:18-slim AS builder

WORKDIR /app

# 接收构建时参数（用于注入 NEXT_PUBLIC_* 环境变量）
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Set environment variables for build
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

# Build the application
RUN npm run build

# ============================================
# Stage 3: Production
# ============================================
FROM node:18-slim AS production

WORKDIR /app

# Set environment variables
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Create non-root user (Debian style)
RUN groupadd --system --gid 1001 nodejs
RUN useradd --system --uid 1001 --gid nodejs nextjs

# Copy built application
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Set ownership
RUN chown -R nextjs:nodejs /app

# Switch to non-root user
USER nextjs

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:3000 || exit 1

# Run the application
CMD ["node", "server.js"]
