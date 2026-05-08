# 远程服务器部署指南

## 服务器信息
- IP: 114.132.186.148
- 用户名: zby
- 密码: 1a2B3c@4

---

## 连接方式

### Windows Terminal / PowerShell
```powershell
ssh zby@114.132.186.148
# 输入密码: 1a2B3c@4
```

### Windows CMD
```cmd
ssh zby@114.132.186.148
# 输入密码: 1a2B3c@4
```

### PuTTY / 其他SSH工具
- Host: 114.132.186.148
- Port: 22
- Username: zby
- Password: 1a2B3c@4

---

## 部署流程

### 连接后执行以下命令:

```bash
# 1. 查找项目目录
ls -la
# 常见位置: /home/zby/VillagePlan 或 ~/VillagePlan

# 2. 进入项目目录（假设是 ~/VillagePlan）
cd ~/VillagePlan

# 3. 检查当前状态
git status
ls -la backend/
ls -la frontend/

# 4. 停止现有服务
pkill -f "uvicorn main:app"  # 停止后端
pkill -f "npm run dev"       # 停止前端

# 5. 拉取最新代码
git pull origin main

# 6. 配置前端环境变量（如果缺失）
cd frontend
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_TILE_SOURCE=tianditu
EOF
cd ..

# 7. 更新依赖
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..

# 8. 启动服务
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
cd ..

cd frontend
npm run dev &
cd ..

# 9. 验证服务
curl http://localhost:8000/health
curl http://localhost:3000
```

---

## 一键部署脚本

如果项目已同步，可直接运行:

```bash
cd ~/VillagePlan
bash scripts/deploy_remote.sh
```

---

## 常见问题排查

### 1. 后端无法启动
```bash
# 查看后端日志
cat logs/backend.log

# 检查Python环境
python --version
pip list | grep fastapi
```

### 2. 前端无法访问API
```bash
# 检查前端环境配置
cat frontend/.env.local

# 检查后端是否运行
curl http://localhost:8000/health

# 检查前端日志
cat logs/frontend.log
```

### 3. 服务端口被占用
```bash
# 查看8000端口占用
lsof -i :8000

# 查看3000端口占用
lsof -i :3000

# 强制停止占用进程
kill -9 <PID>
```

---

## 外网访问

部署完成后，外网访问地址:
- 后端: http://114.132.186.148:8000
- 前端: http://114.132.186.148:3000

需要确保服务器防火墙开放 8000 和 3000 端口。