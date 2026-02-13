@echo off
REM 村庄规划系统停止脚本 (Windows)
setlocal enabledelayedexpansion

echo ===================================
echo   村庄规划系统 - 服务停止
echo ===================================
echo.

set STOPPED=0

REM 1. 停止后端
echo 🛑 检查后端服务...
if exist logs\backend.pid (
  set /p BACKEND_PID=<logs\backend.pid
  echo   检查 PID 文件: !BACKEND_PID!

  for /f "tokens=1" %%x in ('tasklist /FI "PID eq !BACKEND_PID!" 2^>nul ^| find /c "!BACKEND_PID!"') do set RUNNING=%%x
  if !RUNNING! gtr 0 (
    echo   停止后端服务 PID: !BACKEND_PID!
    taskkill /F /PID !BACKEND_PID! > nul 2>&1
    timeout /t 1 /nobreak > nul
    echo   ✓ 后端已停止
    set STOPPED=1
  ) else (
    echo   ⚠ 后端进程未运行 (PID: !BACKEND_PID!)
  )

  del /f /q logs\backend.pid > nul 2>&1
) else (
  echo   ⚠ 后端PID文件不存在
)
echo.

REM 2. 停止前端
echo 🛑 检查前端服务...
if exist logs\frontend.pid (
  set /p FRONTEND_PID=<logs\frontend.pid
  echo   检查 PID 文件: !FRONTEND_PID!

  for /f "tokens=1" %%x in ('tasklist /FI "PID eq !FRONTEND_PID!" 2^>nul ^| find /c "!FRONTEND_PID!"') do set RUNNING=%%x
  if !RUNNING! gtr 0 (
    echo   停止前端服务 PID: !FRONTEND_PID!
    taskkill /F /PID !FRONTEND_PID! > nul 2>&1
    timeout /t 1 /nobreak > nul
    echo   ✓ 前端已停止
    set STOPPED=1
  ) else (
    echo   ⚠ 前端进程未运行 (PID: !FRONTEND_PID!)
  )

  del /f /q logs\frontend.pid > nul 2>&1
) else (
  echo   ⚠ 前端PID文件不存在
)
echo.

REM 3. 清理残留进程
echo 🧹 检查残留进程...
set FOUND=0

REM 检查后端端口 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
  set FOUND=1
  echo   ⚠ 发现后端残留进程: PID %%a
  set /p CONFIRM="  是否停止? (y/N): "
  if /i "!CONFIRM!"=="y" (
    taskkill /F /PID %%a > nul 2>&1
    if !errorlevel! equ 0 (
      echo   ✓ 已停止
    ) else (
      echo   × 停止失败
    )
  )
)

REM 检查前端端口 3000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000.*LISTENING"') do (
  set FOUND=1
  echo   ⚠ 发现前端残留进程: PID %%a
  set /p CONFIRM="  是否停止? (y/N): "
  if /i "!CONFIRM!"=="y" (
    taskkill /F /PID %%a > nul 2>&1
    if !errorlevel! equ 0 (
      echo   ✓ 已停止
    ) else (
      echo   × 停止失败
    )
  )
)

REM 检查前端端口 3001
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3001.*LISTENING"') do (
  set FOUND=1
  echo   ⚠ 发现前端残留进程: PID %%a
  set /p CONFIRM="  是否停止? (y/N): "
  if /i "!CONFIRM!"=="y" (
    taskkill /F /PID %%a > nul 2>&1
    if !errorlevel! equ 0 (
      echo   ✓ 已停止
    ) else (
      echo   × 停止失败
    )
  )
)

if !FOUND! equ 0 (
  echo   ✓ 无残留进程
)
echo.

REM 4. 最终状态
echo ===================================
if !STOPPED! equ 1 (
  echo   ✓ 服务已停止
) else (
  echo   ⚠ 没有运行中的服务
)
echo ===================================
echo.
