#!/bin/bash
# 村庄规划系统停止脚本

set -e

echo "==================================="
echo "  村庄规划系统 - 服务停止"
echo "==================================="
echo ""

STOPPED=0

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. 停止后端
echo "🛑 检查后端服务..."
if [ -f logs/backend.pid ]; then
  BACKEND_PID=$(cat logs/backend.pid)
  echo "  检查 PID 文件: $BACKEND_PID"

  if tasklist //FI "PID eq $BACKEND_PID" 2>&1 | grep -q $BACKEND_PID; then
    echo -e "  ${GREEN}停止后端服务${NC} (PID: $BACKEND_PID)..."
    taskkill //F //PID $BACKEND_PID > /dev/null 2>&1 || true
    sleep 1
    echo -e "  ${GREEN}✓${NC} 后端已停止"
    STOPPED=1
  else
    echo -e "  ${YELLOW}⚠${NC}  后端进程未运行 (PID: $BACKEND_PID)"
  fi

  rm -f logs/backend.pid
else
  echo -e "  ${YELLOW}⚠${NC}  后端PID文件不存在"
fi
echo ""

# 2. 停止前端
echo "🛑 检查前端服务..."
if [ -f logs/frontend.pid ]; then
  FRONTEND_PID=$(cat logs/frontend.pid)
  echo "  检查 PID 文件: $FRONTEND_PID"

  if tasklist //FI "PID eq $FRONTEND_PID" 2>&1 | grep -q $FRONTEND_PID; then
    echo -e "  ${GREEN}停止前端服务${NC} (PID: $FRONTEND_PID)..."
    taskkill //F //PID $FRONTEND_PID > /dev/null 2>&1 || true
    sleep 1
    echo -e "  ${GREEN}✓${NC} 前端已停止"
    STOPPED=1
  else
    echo -e "  ${YELLOW}⚠${NC}  前端进程未运行 (PID: $FRONTEND_PID)"
  fi

  rm -f logs/frontend.pid
else
  echo -e "  ${YELLOW}⚠${NC}  前端PID文件不存在"
fi
echo ""

# 3. 清理可能残留的进程
echo "🧹 检查残留进程..."
FOUND=0

# 检查后端端口 8000
BACKEND_PIDS=$(netstat -ano 2>/dev/null | grep ":8000.*LISTENING" | awk '{print $5}' | sort -u)
if [ -n "$BACKEND_PIDS" ]; then
  FOUND=1
  echo -e "  ${YELLOW}发现后端残留进程:${NC}"
  echo "$BACKEND_PIDS" | while read PID; do
    if [ -n "$PID" ]; then
      PROCESS_INFO=$(tasklist //FI "PID eq $PID" //FO CSV //NH 2>/dev/null | cut -d'"' -f2)
      echo "    端口 8000: PID $PID (${PROCESS_INFO:-Unknown})"
      read -p "    是否停止? (y/N): " CONFIRM
      if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
        taskkill //F //PID $PID > /dev/null 2>&1 && echo "    ✓ 已停止" || echo "    × 停止失败"
      fi
    fi
  done
fi

# 检查前端端口 3000 和 3001
FRONTEND_PIDS=$(netstat -ano 2>/dev/null | grep -E ":3000|:3001" | grep "LISTENING" | awk '{print $5}' | sort -u)
if [ -n "$FRONTEND_PIDS" ]; then
  FOUND=1
  echo -e "  ${YELLOW}发现前端残留进程:${NC}"
  echo "$FRONTEND_PIDS" | while read PID; do
    if [ -n "$PID" ]; then
      PROCESS_INFO=$(tasklist //FI "PID eq $PID" //FO CSV //NH 2>/dev/null | cut -d'"' -f2)
      echo "    端口 3000/3001: PID $PID (${PROCESS_INFO:-Unknown})"
      read -p "    是否停止? (y/N): " CONFIRM
      if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
        taskkill //F //PID $PID > /dev/null 2>&1 && echo "    ✓ 已停止" || echo "    × 停止失败"
      fi
    fi
  done
fi

if [ $FOUND -eq 0 ]; then
  echo -e "  ${GREEN}✓${NC} 无残留进程"
fi
echo ""

# 4. 最终状态
echo "==================================="
if [ $STOPPED -eq 1 ]; then
  echo -e "  ${GREEN}✓${NC} 服务已停止"
else
  echo -e "  ${YELLOW}⚠${NC}  没有运行中的服务"
fi
echo "==================================="
