#!/bin/bash
# ============================================
# Village Planning Agent - 远程服务器部署脚本
# 服务器: 114.132.186.148
# 执行方式: 在服务器终端运行此脚本
# ============================================

set -e  # 遇错即停

echo "==========================================="
echo "  Village Planning Agent 部署更新脚本"
echo "==========================================="
echo ""

# 配置变量
PROJECT_DIR="/home/zby/VillagePlan"  # 修改为实际项目目录
GIT_REPO="https://github.com/your-repo/Village_Planning_Agent.git"  # 修改为实际仓库地址

# 检查项目目录
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ 项目目录不存在: $PROJECT_DIR"
    echo "请先克隆项目或修改 PROJECT_DIR 变量"
    exit 1
fi

cd "$PROJECT_DIR"
echo "📁 当前目录: $(pwd)"

# ============================================
# 步骤1: 停止现有服务
# ============================================
echo ""
echo "步骤1: 停止现有服务..."

# 查找并停止后端进程
BACKEND_PID=$(pgrep -f "uvicorn main:app" || true)
if [ -n "$BACKEND_PID" ]; then
    echo "  停止后端进程 (PID: $BACKEND_PID)"
    kill $BACKEND_PID 2>/dev/null || true
    sleep 2
fi

# 查找并停止前端进程
FRONTEND_PID=$(pgrep -f "npm run dev" || true)
if [ -n "$FRONTEND_PID" ]; then
    echo "  停止前端进程 (PID: $FRONTEND_PID)"
    kill $FRONTEND_PID 2>/dev/null || true
    sleep 2
fi

echo "✅ 服务已停止"

# ============================================
# 步骤2: 拉取最新代码
# ============================================
echo ""
echo "步骤2: 拉取最新代码..."

# 检查是否有未提交的更改
if git status --porcelain | grep -q .; then
    echo "⚠️  发现本地更改，暂存后更新..."
    git stash
fi

git fetch origin
git checkout main
git pull origin main

echo "✅ 代码已更新"

# ============================================
# 步骤3: 配置环境变量
# ============================================
echo ""
echo "步骤3: 检查环境变量配置..."

# 后端环境配置
if [ ! -f ".env" ]; then
    echo "⚠️  后端缺少 .env 文件，从示例创建..."
    cp .env.example .env
    echo "❗ 请手动编辑 .env 文件，填入API密钥"
fi

# 前端环境配置
if [ ! -f "frontend/.env.local" ]; then
    echo "⚠️  前端缺少 .env.local 文件，创建默认配置..."
    cat > frontend/.env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_TILE_SOURCE=tianditu
EOF
fi

echo "✅ 环境配置检查完成"

# ============================================
# 步骤4: 更新依赖
# ============================================
echo ""
echo "步骤4: 更新依赖..."

# Python依赖
echo "  更新Python依赖..."
cd backend
pip install -r requirements.txt --quiet || pip3 install -r requirements.txt --quiet
cd ..

# Node依赖
echo "  更新Node依赖..."
cd frontend
npm install --silent
cd ..

echo "✅ 依赖已更新"

# ============================================
# 步骤5: 启动服务
# ============================================
echo ""
echo "步骤5: 启动服务..."

# 创建日志目录
mkdir -p logs

# 启动后端
echo "  启动后端服务..."
cd backend
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 > ../logs/backend.log 2>&1 &
BACKEND_PID=$!
cd ..
echo "  后端 PID: $BACKEND_PID"

# 等待后端启动
sleep 5

# 检查后端是否启动成功
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✅ 后端启动成功 (http://localhost:8000)"
else
    echo "❌ 后端启动失败，请检查 logs/backend.log"
fi

# 启动前端
echo "  启动前端服务..."
cd frontend
nohup npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo "  前端 PID: $FRONTEND_PID"

# 等待前端启动
sleep 3

echo ""
echo "==========================================="
echo "  部署完成!"
echo "==========================================="
echo ""
echo "服务地址:"
echo "  后端: http://114.132.186.148:8000"
echo "  前端: http://114.132.186.148:3000"
echo ""
echo "日志文件:"
echo "  后端日志: logs/backend.log"
echo "  前端日志: logs/frontend.log"
echo ""
echo "进程PID:"
echo "  后端: $BACKEND_PID"
echo "  前端: $FRONTEND_PID"
echo ""
echo "如需停止服务:"
echo "  kill $BACKEND_PID $FRONTEND_PID"
echo ""

# 保存PID到文件
echo "$BACKEND_PID" > logs/backend.pid
echo "$FRONTEND_PID" > logs/frontend.pid