@echo off
chcp 65001 >nul
REM Village Planning System - Service Startup Script (Windows)

echo ===================================
echo   Village Planning System - Start
echo ===================================
echo.

REM 1. Initialize log directory
echo [INFO] Initializing log directory...
if not exist logs mkdir logs
del /f /q logs\backend_*.log 2>nul
del /f /q logs\frontend_*.log 2>nul
del /f /q logs\*.pid 2>nul
echo   [OK] Log directory ready
echo.

REM Save path variables
set "BACKEND_DIR=%CD%\backend"
set "FRONTEND_DIR=%CD%\frontend"
set "LOGS_DIR=%CD%\logs"

REM Port configuration (check environment variables, otherwise use defaults)
if not defined BACKEND_PORT set BACKEND_PORT=8000
if not defined FRONTEND_PORT set FRONTEND_PORT=3000

REM 2. Start backend service
echo [INFO] Starting backend service...
start /B cmd /c "cd /d %BACKEND_DIR% && python -m uvicorn main:app --reload --host 0.0.0.0 --port %BACKEND_PORT% --workers 1 --no-access-log > %LOGS_DIR%\backend_stdout.log 2> %LOGS_DIR%\backend_stderr.log"
echo   [OK] Backend starting...
echo.

REM Wait for backend to start (using ping for delay)
echo [INFO] Waiting for backend service...
set /a COUNT=0
:check_backend
set /a COUNT+=1
ping -n 2 127.0.0.1 >nul 2>&1
curl -s http://localhost:%BACKEND_PORT%/docs >nul 2>&1
if %errorlevel% equ 0 (
  echo   [OK] Backend started: http://localhost:%BACKEND_PORT%
) else (
  if %COUNT% lss 20 (
    goto check_backend
  ) else (
    echo   [ERROR] Backend startup timeout. Check logs:
    echo   ===== stderr =====
    type logs\backend_stderr.log 2>nul
    echo   ===== stdout =====
    type logs\backend_stdout.log 2>nul
    pause
    exit /b 1
  )
)
echo.

REM 3. Start frontend service
echo [INFO] Starting frontend service...
start /B cmd /c "cd /d %FRONTEND_DIR% && npm run dev > %LOGS_DIR%\frontend_stdout.log 2> %LOGS_DIR%\frontend_stderr.log"
echo   [OK] Frontend starting...
echo.

REM Wait for frontend to start
echo [INFO] Waiting for frontend service...
set /a COUNT=0
:check_frontend
set /a COUNT+=1
ping -n 2 127.0.0.1 >nul 2>&1
findstr "Local:" logs\frontend_stdout.log >nul 2>&1
if %errorlevel% equ 0 (
  for /f "tokens=3 delims=: " %%a in ('findstr "Local:" logs\frontend_stdout.log 2^^^>nul') do set FRONTEND_PORT=%%a
  echo   [OK] Frontend started: http://localhost:%FRONTEND_PORT%
) else (
  if %COUNT% lss 20 (
    goto check_frontend
  ) else (
    echo   [WARN] Frontend may still be starting. Default port: 3000
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
echo [LOG] Log files:
echo   Backend: type logs\backend_stdout.log
echo           type logs\backend_stderr.log
echo   Frontend: type logs\frontend_stdout.log
echo            type logs\frontend_stderr.log
echo.
echo [STOP] Stop services:
echo   stop-services.bat
echo.
echo ===================================
echo.
echo Press any key to close this window...
pause > nul