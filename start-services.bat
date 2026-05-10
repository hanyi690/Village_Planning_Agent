@echo off
REM Village Planning System - Service Startup Script (Windows)

REM 切换到脚本所在目录
cd /d "%~dp0"

echo ===================================
echo   Village Planning System
echo ===================================
echo Current directory: %CD%
echo Script location: %~dp0
echo.

REM Check if directories exist
if not exist "backend" (
  echo ERROR: backend directory not found!
  echo Looking for: %~dp0backend
  pause
  exit /b 1
)

if not exist "frontend" (
  echo ERROR: frontend directory not found!
  echo Looking for: %~dp0frontend
  pause
  exit /b 1
)

echo OK: directories found
echo.

REM Create logs directory
if not exist logs mkdir logs

REM 生成带时间戳的日志文件名
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set TODAY=%%a%%b%%c)
set BK_LOG=logs\backend-%TODAY%.log
set FE_LOG=logs\frontend-%TODAY%.log

REM 启动后台，所有输出写入日志文件（窗口不再弹出）
start "Backend-8000" /min cmd /c "cd /d %~dp0backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > %~dp0%BK_LOG% 2>&1"

REM 启动前端，同样写入日志
start "Frontend-3000" /min cmd /c "cd /d %~dp0frontend && npm run dev > %~dp0%FE_LOG% 2>&1"

echo.
echo ===================================
echo Services started in separate windows
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
echo ===================================
echo.
echo This window will close in 10 seconds...
echo Press any key to keep it open
timeout /t 10 >nul