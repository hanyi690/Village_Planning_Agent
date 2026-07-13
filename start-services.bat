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

REM Create logs directory (used by Python logging dictConfig)
if not exist logs mkdir logs

REM 生成带时间戳的前端日志文件名
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set TODAY=%%a%%b%%c)
set FE_LOG=logs\frontend-%TODAY%.log

REM 启动后端 — 不重定向 stdout/stderr
REM Python logging dictConfig 已配置:
REM   - logs/planning.log (全量日志，按日轮转)
REM   - logs/planning.error.log (仅 ERROR+)
REM   - console handler 仍输出到终端
start "Backend-8000" /min cmd /c "cd /d %~dp0backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-config null"

REM 启动前端，写入日志
start "Frontend-3000" /min cmd /c "cd /d %~dp0frontend && npm run dev > %~dp0%FE_LOG% 2>&1"

echo.
echo ===================================
echo Services started in separate windows
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Backend logs (Python logging):
echo   All:   logs\planning.log
echo   Error: logs\planning.error.log
echo Frontend log:
echo   logs\frontend-%TODAY%.log
echo ===================================
echo.
echo This window will close in 10 seconds...
echo Press any key to keep it open
timeout /t 10 >nul