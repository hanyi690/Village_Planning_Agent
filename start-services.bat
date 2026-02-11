@echo off
REM 村庄规划系统启动脚本 (Windows)
REM 每次启动自动清空日志文件

echo ===================================
echo   村庄规划系统 - 服务启动
echo ===================================
echo.

REM 1. 清空日志文件
echo 📝 清空日志文件...
if not exist logs mkdir logs
break > logs\backend.log
break > logs\frontend.log
echo ✅ 日志已清空
echo.

REM 2. 启动后端服务
echo 🚀 启动后端服务...
cd backend
start /B python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 > ..\logs\backend.log 2>&1
cd ..
echo ✅ 后端启动中...
timeout /t 3 /nobreak > nul

REM 3. 检查后端启动
netstat -ano | findstr ":8000.*LISTENING" > nul
if %errorlevel% equ 0 (
  echo ✅ 后端服务已启动: http://localhost:8000
) else (
  echo ❌ 后端启动失败，查看日志:
  type logs\backend.log
  pause
  exit /b 1
)
echo.

REM 4. 启动前端服务
echo 🎨 启动前端服务...
cd frontend
start /B npm run dev > ..\logs\frontend.log 2>&1
cd ..
echo ✅ 前端启动中...
timeout /t 5 /nobreak > nul

REM 5. 查找前端端口
findstr "Local:" logs\frontend.log > nul
if %errorlevel% equ 0 (
  for /f "tokens=*" %%a in ('findstr "Local:" logs\frontend.log') do (
    set LINE=%%a
  )
  for /f "tokens=3 delims=: " %%a in ("%LINE%") do set FRONTEND_PORT=%%a
  echo ✅ 前端服务已启动: http://localhost:%FRONTEND_PORT%
) else (
  echo ✅ 前端服务已启动: http://localhost:3001
)
echo.

REM 6. 显示服务状态
echo ===================================
echo   服务启动成功！
echo ===================================
echo.
echo 🌐 访问地址:
echo   前端: http://localhost:3001
echo   后端: http://localhost:8000
echo   API文档: http://localhost:8000/docs
echo.
echo 📝 日志文件:
echo   后端: tail -f logs\backend.log
echo   前端: tail -f logs\frontend.log
echo   或直接查看: logs\backend.log, logs\frontend.log
echo.
echo 🛑 停止服务:
echo   stop-services.bat
echo   或: Ctrl+C
echo.
echo ===================================
echo.
echo 按任意键关闭此窗口...
pause > nul
