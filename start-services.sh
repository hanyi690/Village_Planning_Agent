#!/bin/bash
# 村庄规划系统启动脚本
# 每次启动自动清空日志文件

set -e

echo "==================================="
echo "  村庄规划系统 - 服务启动"
echo "==================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 1. 清空日志文件
echo "📝 初始化日志目录..."
mkdir -p logs
rm -f logs/backend_*.log logs/frontend_*.log
echo -e "  ${GREEN}✓${NC} 日志目录已准备"
echo ""

# 2. 停止旧进程（如果存在）
echo "🛑 检查并停止旧进程..."
if [ -f logs/backend.pid ]; then
  OLD_PID=$(cat logs/backend.pid)
  if tasklist //FI "PID eq $OLD_PID" 2>&1 | grep -q $OLD_PID 2>/dev/null; then
    echo "  停止旧后端进程 (PID: $OLD_PID)"
    taskkill //F //PID $OLD_PID > /dev/null 2>&1 || true
  fi
  rm -f logs/backend.pid
fi

if [ -f logs/frontend.pid ]; then
  OLD_PID=$(cat logs/frontend.pid)
  if tasklist //FI "PID eq $OLD_PID" 2>&1 | grep -q $OLD_PID 2>/dev/null; then
    echo "  停止旧前端进程 (PID: $OLD_PID)"
    taskkill //F //PID $OLD_PID > /dev/null 2>&1 || true
  fi
  rm -f logs/frontend.pid
fi
echo -e "  ${GREEN}✓${NC} 旧进程已清理"
echo ""

# 3. 启动后端服务
echo -e "${BLUE}🚀 启动后端服务...${NC}"
cd backend
nohup python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 > ../logs/backend_stdout.log 2> ../logs/backend_stderr.log &
BACKEND_PID=$!
echo $BACKEND_PID > ../logs/backend.pid
echo -e "  ${GREEN}✓${NC} 后端启动中... (PID: $BACKEND_PID)"
cd ..

# 等待后端启动
echo "  等待后端就绪..."
for i in {1..15}; do
  sleep 1
  if netstat -ano 2>/dev/null | grep ":8000.*LISTENING" > /dev/null; then
    echo -e "  ${GREEN}✓${NC} 后端服务已启动: http://localhost:8000"
    break
  fi
  if [ $i -eq 15 ]; then
    echo -e "  ${RED}✗${NC} 后端启动超时，查看日志:"
    echo "  ===== stderr ====="
    tail -n 20 logs/backend_stderr.log 2>/dev/null || echo "  (无stderr输出)"
    echo "  ===== stdout ====="
    tail -n 20 logs/backend_stdout.log 2>/dev/null || echo "  (无stdout输出)"
    exit 1
  fi
done
echo ""

# 4. 启动前端服务
echo -e "${BLUE}🎨 启动前端服务...${NC}"
cd frontend
nohup npm run dev > ../logs/frontend_stdout.log 2> ../logs/frontend_stderr.log &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../logs/frontend.pid
echo -e "  ${GREEN}✓${NC} 前端启动中... (PID: $FRONTEND_PID)"
cd ..

# 等待前端启动
echo "  等待前端就绪..."
FRONTEND_PORT=""
for i in {1..20}; do
  sleep 1
  # 从日志中提取端口号
  FRONTEND_PORT=$(grep -o "Local:.*http://localhost:[0-9]*" logs/frontend_stdout.log 2>/dev/null | grep -o "[0-9]*$" | head -1)
  if [ -n "$FRONTEND_PORT" ]; then
    echo -e "  ${GREEN}✓${NC} 前端服务已启动: http://localhost:$FRONTEND_PORT"
    break
  fi
  if [ $i -eq 20 ]; then
    echo -e "  ${YELLOW}⚠${NC}  前端可能仍在启动中，默认端口: 3001"
    FRONTEND_PORT=3001
  fi
done
echo ""

# 5. 显示服务状态
echo "==================================="
echo -e "  ${GREEN}✓${NC} 服务启动成功！"
echo "==================================="
echo ""
echo "🌐 访问地址:"
echo "  前端: ${BLUE}http://localhost:$FRONTEND_PORT${NC}"
echo "  后端: ${BLUE}http://localhost:8000${NC}"
echo "  API文档: ${BLUE}http://localhost:8000/docs${NC}"
echo ""
echo "📋 进程信息:"
echo "  后端 PID: ${GREEN}$BACKEND_PID${NC}"
echo "  前端 PID: ${GREEN}$FRONTEND_PID${NC}"
echo ""
echo "📝 日志文件:"
echo "  后端: ${BLUE}tail -f logs/backend_stdout.log${NC}"
echo "       ${BLUE}tail -f logs/backend_stderr.log${NC}"
echo "  前端: ${BLUE}tail -f logs/frontend_stdout.log${NC}"
echo "       ${BLUE}tail -f logs/frontend_stderr.log${NC}"
echo ""
echo "🛑 停止服务:"
echo "  ${YELLOW}./stop-services.sh${NC}"
echo "  或: kill \$(cat logs/backend.pid) && kill \$(cat logs/frontend.pid)"
echo ""
echo "==================================="
