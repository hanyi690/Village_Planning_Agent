@echo off
REM 村庄规划系统停止脚本 (Windows)

echo ===================================
echo   村庄规划系统 - 服务停止
echo ===================================
echo.

echo 🛑 停止后端和前端服务...

REM 停止后端 (uvicorn/python on port 8000)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
  echo 停止后端进程 PID: %%a
  taskkill /F /PID %%a > nul 2>&1
)

REM 停止前端 (Next.js on port 3000 or 3001)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000.*LISTENING"') do (
  echo 停止前端进程 PID: %%a
  taskkill /F /PID %%a > nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3001.*LISTENING"') do (
  echo 停止前端进程 PID: %%a
  taskkill /F /PID %%a > nul 2>&1
)

echo.
echo ===================================
echo   服务已停止
echo ===================================
echo.
pause
