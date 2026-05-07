@echo off
chcp 65001 >nul
REM Village Planning System - Service Startup Script (Windows)

REM 切换到脚本所在目录（解决开机启动时路径问题）
cd /d "%~dp0"

echo ===================================
echo   Village Planning System - Start
echo ===================================
echo.

REM 1. Initialize log directory
echo [INFO] Initializing log directory...
if not exist logs mkdir logs
del /f /q logs\*.log 2>nul
del /f /q logs\*.pid 2>nul
echo   [OK] Log directory ready
echo.

REM Save path variables (使用脚本所在目录)
set "PROJECT_DIR=%~dp0"
set "BACKEND_DIR=%~dp0backend"
set "FRONTEND_DIR=%~dp0frontend"
set "LOGS_DIR=%~dp0logs"

REM Port configuration (check environment variables, otherwise use defaults)
if not defined BACKEND_PORT set BACKEND_PORT=8000
if not defined FRONTEND_PORT set FRONTEND_PORT=3000

REM 2. Start backend service (独立窗口，不会随父窗口关闭)
echo [INFO] Starting backend service...
start "Village-Backend" cmd /c "cd /d %BACKEND_DIR% && python -m uvicorn main:app --reload --host 0.0.0.0 --port %BACKEND_PORT% --workers 1 --no-access-log 2>&1 | tee %LOGS_DIR%\backend.log"
echo   [OK] Backend starting in separate window...
echo.

REM Wait for backend to start
echo [INFO] Waiting for backend service...
set /a COUNT=0
:check_backend
set /a COUNT+=1
ping -n 2 127.0.0.1 >nul 2>&1
curl -s http://localhost:%BACKEND_PORT%/docs >nul 2>&1
if %errorlevel% equ 0 (
  echo   [OK] Backend started: http://localhost:%BACKEND_PORT%
) else (
  if %COUNT% lss 30 (
    goto check_backend
  ) else (
    echo   [WARN] Backend may still be starting. Port: %BACKEND_PORT%
  )
)
echo.

REM 3. Start frontend service (独立窗口)
echo [INFO] Starting frontend service...
start "Village-Frontend" cmd /c "cd /d %FRONTEND_DIR% && npm run dev"
echo   [OK] Frontend starting in separate window...
echo.

REM Wait for frontend to start
echo [INFO] Waiting for frontend service...
set /a COUNT=0
:check_frontend
set /a COUNT+=1
ping -n 3 127.0.0.1 >nul 2>&1
curl -s http://localhost:%FRONTEND_PORT% >nul 2>&1
if %errorlevel% equ 0 (
  echo   [OK] Frontend started: http://localhost:%FRONTEND_PORT%
) else (
  if %COUNT% lss 20 (
    goto check_frontend
  ) else (
    echo   [WARN] Frontend may still be starting. Port: %FRONTEND_PORT%
  )
)
echo.

REM 4. Display service status
echo ===================================
echo   Services Started Successfully!
echo ===================================
echo.
echo [URL] Access addresses:
echo   Frontend: http://localhost:%FRONTEND_PORT%
echo   Backend:  http://localhost:%BACKEND_PORT%
echo   API Docs: http://localhost:%BACKEND_PORT%/docs
echo.
echo [WINDOW] Service windows:
echo   Backend:  "Village-Backend" window
echo   Frontend: "Village-Frontend" window
echo   (关闭服务窗口即可停止服务)
echo.
echo [STOP] Stop services:
echo   stop-services.bat
echo   或直接关闭 Backend/Frontend 窗口
echo.
echo ===================================
echo.
echo This window can be closed safely.
echo Services will continue running in their own windows.
echo.
pause