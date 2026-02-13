@echo off
REM 村庄规划系统启动脚本 (Windows)
setlocal enabledelayedexpansion

echo ===================================
echo   村庄规划系统 - 服务启动
echo ===================================
echo.

REM 1. 清空日志文件
echo 📝 初始化日志目录...
if not exist logs mkdir logs
del /f /q logs\backend_*.log 2>nul
del /f /q logs\frontend_*.log 2>nul
echo   ✓ 日志目录已准备
echo.

REM 2. 停止旧进程
echo 🛑 检查并停止旧进程...
if exist logs\backend.pid (
  set /p OLD_PID=<logs\backend.pid
  for /f "tokens=1" %%x in ('tasklist /FI "PID eq !OLD_PID!" 2^>nul ^| find /c "!OLD_PID!"') do set RUNNING=%%x
  if !RUNNING! gtr 0 (
    echo   停止旧后端进程 PID: !OLD_PID!
    taskkill /F /PID !OLD_PID! > nul 2>&1
  )
  del /f /q logs\backend.pid > nul 2>&1
)

if exist logs\frontend.pid (
  set /p OLD_PID=<logs\frontend.pid
  for /f "tokens=1" %%x in ('tasklist /FI "PID eq !OLD_PID!" 2^>nul ^| find /c "!OLD_PID!"') do set RUNNING=%%x
  if !RUNNING! gtr 0 (
    echo   停止旧前端进程 PID: !OLD_PID!
    taskkill /F /PID !OLD_PID! > nul 2>&1
  )
  del /f /q logs\frontend.pid > nul 2>&1
)
echo   ✓ 旧进程已清理
echo.

REM 3. 启动后端服务 (使用 PowerShell)
echo 🚀 启动后端服务...
powershell -Command "Start-Process -NoNewWindow -FilePath 'python' -ArgumentList @('-m','uvicorn','main:app','--reload','--host','0.0.0.0','--port','8000','--workers','1') -WorkingDirectory '%CD%\backend' -RedirectStandardOutput '%CD%\logs\backend_stdout.log' -RedirectStandardError '%CD%\logs\backend_stderr.log'"
if %errorlevel% equ 0 (
  echo   ✓ 后端启动中...

  REM 获取后端 PID 并保存
  timeout /t 2 /nobreak > nul
  for /f "tokens=2" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do set BACKEND_PID=%%a

  REM 检查后端启动
  set /a COUNT=0
  :check_backend
  set /a COUNT+=1
  netstat -ano | findstr ":8000.*LISTENING" > nul
  if %errorlevel% equ 0 (
    echo   ✓ 后端服务已启动: http://localhost:8000
    if defined BACKEND_PID (
      echo !BACKEND_PID! > logs\backend.pid
      echo   保存后端 PID: !BACKEND_PID!
    )
  ) else (
    if !COUNT! lss 15 (
      timeout /t 1 /nobreak > nul
      goto check_backend
    ) else (
      echo   ✗ 后端启动超时，查看日志:
      echo   ===== stderr =====
      type logs\backend_stderr.log 2>nul
      echo   ===== stdout =====
      type logs\backend_stdout.log 2>nul
      pause
      exit /b 1
    )
  )
) else (
  echo   ✗ 后端启动失败
  pause
  exit /b 1
)
echo.

REM 4. 启动前端服务
echo 🎨 启动前端服务...
powershell -Command "Start-Process -NoNewWindow -FilePath 'cmd' -ArgumentList '/c','npm','run','dev' -WorkingDirectory '%CD%\frontend' -RedirectStandardOutput '%CD%\logs\frontend_stdout.log' -RedirectStandardError '%CD%\logs\frontend_stderr.log'"
if %errorlevel% equ 0 (
  echo   ✓ 前端启动中...

  REM 等待并获取前端端口
  set /a COUNT=0
  :check_frontend
  set /a COUNT+=1
  findstr "Local:" logs\frontend_stdout.log > nul
  if %errorlevel% equ 0 (
    for /f "tokens=*" %%a in ('findstr "Local:" logs\frontend_stdout.log') do set LINE=%%a
    for /f "tokens=3 delims=: " %%a in ("!LINE!") do set FRONTEND_PORT=%%a
    echo   ✓ 前端服务已启动: http://localhost:!FRONTEND_PORT!
  ) else (
    if !COUNT! lss 20 (
      timeout /t 1 /nobreak > nul
      goto check_frontend
    ) else (
      echo   ⚠ 前端可能仍在启动中，默认端口: 3001
      set FRONTEND_PORT=3001
    )
  )
) else (
  echo   ✗ 前端启动失败
  pause
  exit /b 1
)
echo.

REM 5. 显示服务状态
echo ===================================
echo   ✓ 服务启动成功！
echo ===================================
echo.
echo 🌐 访问地址:
echo   前端: http://localhost:!FRONTEND_PORT!
echo   后端: http://localhost:8000
echo   API文档: http://localhost:8000/docs
echo.
echo 📝 日志文件:
echo   后端: type logs\backend_stdout.log
echo        type logs\backend_stderr.log
echo   前端: type logs\frontend_stdout.log
echo        type logs\frontend_stderr.log
echo.
echo 🛑 停止服务:
echo   stop-services.bat
echo.
echo ===================================
echo.
echo 按任意键关闭此窗口...
pause > nul
