@echo off
REM Village Planning System - Service Stop Script (Windows)
REM Kills all backend (uvicorn/python) and frontend (next/npm/node) processes
REM by port and process name, including child process trees.
setlocal enabledelayedexpansion

echo ===================================
echo   Village Planning System - Stop
echo ===================================
echo.

set KILLED=0

REM 1. Kill backend processes on port 8000 (entire process tree)
echo [Backend] Checking port 8000...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 .*LISTENING"') do (
  echo   Found PID %%a on port 8000
  taskkill /F /T /PID %%a > nul 2>&1
  if !errorlevel! equ 0 (
    echo   OK: Killed process tree %%a
    set KILLED=1
  ) else (
    echo   WARN: Failed to kill %%a
  )
)

REM 2. Kill frontend processes on port 3000/3001 (entire process tree)
for %%p in (3000 3001) do (
  echo [Frontend] Checking port %%p...
  for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%%p .*LISTENING"') do (
    echo   Found PID %%a on port %%p
    taskkill /F /T /PID %%a > nul 2>&1
    if !errorlevel! equ 0 (
      echo   OK: Killed process tree %%a
      set KILLED=1
    ) else (
      echo   WARN: Failed to kill %%a
    )
  )
)

REM 3. Cleanup orphaned uvicorn/python processes under this project
echo [Orphans] Checking leftover uvicorn/python processes...
for /f "tokens=2" %%a in ('wmic process where "CommandLine like '%%uvicorn%%app.main%%' and not CommandLine like '%%wmic%%'" get ProcessId 2^>nul ^| findstr /r "[0-9]"') do (
  echo   Found orphan uvicorn PID %%a
  taskkill /F /T /PID %%a > nul 2>&1
  if !errorlevel! equ 0 (
    echo   OK: Killed orphan %%a
    set KILLED=1
  )
)

REM 4. Cleanup stale PID files (no longer used, but remove if present)
if exist logs\backend.pid del /f /q logs\backend.pid > nul 2>&1
if exist logs\frontend.pid del /f /q logs\frontend.pid > nul 2>&1

REM 5. Verify ports are free
echo.
echo [Verify] Port status:
set PORT_BUSY=0
for %%p in (8000 3000 3001) do (
  netstat -ano 2>nul | findstr ":%%p .*LISTENING" > nul 2>&1
  if !errorlevel! equ 0 (
    echo   Port %%p: STILL IN USE
    set PORT_BUSY=1
  ) else (
    echo   Port %%p: free
  )
)

echo.
echo ===================================
if !KILLED! equ 1 (
  echo   Services stopped
) else (
  echo   No running services found
)
if !PORT_BUSY! equ 1 (
  echo   WARNING: Some ports still in use
  echo   Run again or check manually: netstat -ano ^| findstr ":8000 :3000 :3001"
)
echo ===================================
echo.
