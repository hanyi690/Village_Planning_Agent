#!/bin/bash
# 村庄规划系统停止脚本

echo "==================================="
echo "  村庄规划系统 - 服务停止"
echo "==================================="
echo ""

STOPPED=0

# 1. 停止后端
if [ -f logs/backend.pid ]; then
  BACKEND_PID=$(cat logs/backend.pid)
  echo "🛑 停止后端服务 (PID: $BACKEND_PID)..."

  if tasklist //FI "PID eq $BACKEND_PID" 2>&1 | grep -q $BACKEND_PID; then
    taskkill //F //PID $BACKEND_PID > /dev/null 2>&1
    echo "✅ 后端已停止"
    STOPPED=1
  else
    echo "⚠️  后端进程未运行"
  fi

  rm logs/backend.pid
else
  echo "⚠️  后端PID文件不存在"
fi
echo ""

# 2. 停止前端
if [ -f logs/frontend.pid ]; then
  FRONTEND_PID=$(cat logs/frontend.pid)
  echo "🛑 停止前端服务 (PID: $FRONTEND_PID)..."

  if tasklist //FI "PID eq $FRONTEND_PID" 2>&1 | grep -q $FRONTEND_PID; then
    taskkill //F //PID $FRONTEND_PID > /dev/null 2>&1
    echo "✅ 前端已停止"
    STOPPED=1
  else
    echo "⚠️  前端进程未运行"
  fi

  rm logs/frontend.pid
else
  echo "⚠️  前端PID文件不存在"
fi
echo ""

# 3. 清理可能残留的进程（可选）
echo "🧹 检查残留进程..."
BACKEND_PORTS=$(netstat -ano | grep ":8000" | grep "LISTENING" | awk '{print $5}' | sort -u)
FRONTEND_PORTS=$(netstat -ano | grep ":3000\|:3001" | grep "LISTENING" | awk '{print $5}' | sort -u)

if [ -n "$BACKEND_PORTS" ] || [ -n "$FRONTEND_PORTS" ]; then
  echo "⚠️  发现残留进程:"
  echo "$BACKEND_PORTS" | while read PID; do
    if [ -n "$PID" ]; then
      echo "  后端端口8000: PID $PID"
      read -p "  是否停止? (y/N): " CONFIRM
      if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
        taskkill //F //PID $PID > /dev/null 2>&1
        echo "  ✅ 已停止"
      fi
    fi
  done

  echo "$FRONTEND_PORTS" | while read PID; do
    if [ -n "$PID" ]; then
      echo "  前端端口3000/3001: PID $PID"
      read -p "  是否停止? (y/N): " CONFIRM
      if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
        taskkill //F //PID $PID > /dev/null 2>&1
        echo "  ✅ 已停止"
      fi
    fi
  done
else
  echo "✅ 无残留进程"
fi
echo ""

echo "==================================="
if [ $STOPPED -eq 1 ]; then
  echo "  服务已停止"
else
  echo "  没有运行中的服务"
fi
echo "==================================="
