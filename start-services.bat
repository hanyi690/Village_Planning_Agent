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

REM Start backend
echo Starting backend...
start "Backend-8000" cmd /k "cd /d %~dp0backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000"

REM Wait 5 seconds
ping -n 6 127.0.0.1 >nul

REM Start frontend
echo Starting frontend...
start "Frontend-3000" cmd /k "cd /d %~dp0frontend && npm run dev"

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