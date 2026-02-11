#!/bin/bash
# 村庄规划系统启动脚本
# 每次启动自动清空日志文件

echo "==================================="
echo "  村庄规划系统 - 服务启动"
echo "==================================="
echo ""

# 1. 清空日志文件
echo "📝 清空日志文件..."
mkdir -p logs
> logs/backend.log
> logs/frontend.log
echo "✅ 日志已清空"
echo ""

# 2. 停止旧进程（如果存在）
echo "🛑 检查并停止旧进程..."
if [ -f logs/backend.pid ]; then
  OLD_PID=$(cat logs/backend.pid)
  if tasklist //FI "PID eq $OLD_PID" 2>&1 | grep -q $OLD_PID; then
    echo "  停止旧后端进程 (PID: $OLD_PID)"
    taskkill //F //PID $OLD_PID > /dev/null 2>&1
  fi
fi

if [ -f logs/frontend.pid ]; then
  OLD_PID=$(cat logs/frontend.pid)
  if tasklist //FI "PID eq $OLD_PID" 2>&1 | grep -q $OLD_PID; then
    echo "  停止旧前端进程 (PID: $OLD_PID)"
    taskkill //F //PID $OLD_PID > /dev/null 2>&1
  fi
fi
echo "✅ 旧进程已清理"
echo ""

# 3. 启动后端服务
echo "🚀 启动后端服务..."
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 > ../logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > ../logs/backend.pid
echo "✅ 后端启动中... (PID: $BACKEND_PID)"
cd ..
sleep 3

# 4. 检查后端启动状态
if netstat -ano | grep ":8000" | grep "LISTENING" > /dev/null; then
  echo "✅ 后端服务已启动: http://localhost:8000"
else
  echo "❌ 后端启动失败，查看日志:"
  tail -n 20 logs/backend.log
  exit 1
fi
echo ""

# 5. 启动前端服务
echo "🎨 启动前端服务..."
cd frontend
npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../logs/frontend.pid
echo "✅ 前端启动中... (PID: $FRONTEND_PID)"
cd ..
sleep 5

# 6. 检查前端启动状态
FRONTEND_PORT=$(grep -o "Local:.*http://localhost:[0-9]*" logs/frontend.log | grep -o "[0-9]*$" | head -1)
if [ -z "$FRONTEND_PORT" ]; then
  FRONTEND_PORT=3001
fi
if netstat -ano | grep ":$FRONTEND_PORT" | grep "LISTENING" > /dev/null; then
  echo "✅ 前端服务已启动: http://localhost:$FRONTEND_PORT"
else
  echo "❌ 前端启动失败，查看日志:"
  tail -n 20 logs/frontend.log
  exit 1
fi
echo ""

# 7. 显示服务状态
echo "==================================="
echo "  服务启动成功！"
echo "==================================="
echo ""
echo "🌐 访问地址:"
echo "  前端: http://localhost:$FRONTEND_PORT"
echo "  后端: http://localhost:8000"
echo "  API文档: http://localhost:8000/docs"
echo ""
echo "📋 进程信息:"
echo "  后端 PID: $BACKEND_PID"
echo "  前端 PID: $FRONTEND_PID"
echo ""
echo "📝 日志文件:"
echo "  后端: tail -f logs/backend.log"
echo "  前端: tail -f logs/frontend.log"
echo ""
echo "🛑 停止服务:"
echo "  ./stop-services.sh"
echo "  或: kill \$(cat logs/backend.pid) && kill \$(cat logs/frontend.pid)"
echo ""
echo "==================================="
