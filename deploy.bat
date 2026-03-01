@echo off
chcp 65001 >nul
REM ============================================
REM Village Planning System - Docker Deploy Script
REM ============================================
REM 
REM Usage:
REM   deploy.bat           - Build and start services
REM   deploy.bat build     - Rebuild images
REM   deploy.bat stop      - Stop services
REM   deploy.bat logs      - Show logs
REM   deploy.bat clean     - Remove containers and images
REM

setlocal EnableDelayedExpansion

echo.
echo ╔════════════════════════════════════════════╗
echo ║   Village Planning System - Docker Deploy  ║
echo ╚════════════════════════════════════════════╝
echo.

REM Parse command
set "COMMAND=%1"
if "%COMMAND%"=="" set "COMMAND=start"

REM Check Docker
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not installed or not running.
    echo Please install Docker Desktop: https://www.docker.com/products/docker-desktop
    exit /b 1
)

REM Check .env file
if not exist .env (
    echo [WARN] .env file not found. Creating from .env.example...
    if exist .env.example (
        copy .env.example .env >nul
        echo [INFO] Please edit .env file with your configuration.
        echo [INFO] Required: ZHIPUAI_API_KEY or other LLM API keys
        echo.
        echo Press any key to continue or Ctrl+C to cancel...
        pause >nul
    ) else (
        echo [ERROR] .env.example not found. Please create .env file manually.
        exit /b 1
    )
)

REM Execute command
if "%COMMAND%"=="start" goto :do_start
if "%COMMAND%"=="build" goto :do_build
if "%COMMAND%"=="stop" goto :do_stop
if "%COMMAND%"=="logs" goto :do_logs
if "%COMMAND%"=="clean" goto :do_clean
if "%COMMAND%"=="help" goto :show_help
goto :show_help

:do_start
echo [INFO] Starting services...
echo.

REM Enable BuildKit for faster builds
set DOCKER_BUILDKIT=1
set COMPOSE_DOCKER_CLI_BUILD=1

REM Check if images exist
docker images village-planning-backend:latest --format "{{.ID}}" 2>nul | findstr /r "." >nul
if %errorlevel% neq 0 (
    echo [INFO] Images not found. Building for the first time...
    echo [INFO] This may take a few minutes...
    echo.
)

docker-compose up -d
if %errorlevel% neq 0 (
    echo [ERROR] Failed to start services.
    exit /b 1
)

echo.
echo [INFO] Waiting for services to be healthy...
timeout /t 5 /nobreak >nul

REM Check backend health
echo [INFO] Checking backend health...
set /a RETRY=0
:check_backend
set /a RETRY+=1
curl -s http://localhost:8000/health >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] Backend is healthy
) else (
    if %RETRY% lss 10 (
        timeout /t 2 /nobreak >nul
        goto :check_backend
    )
    echo   [WARN] Backend health check failed. Check logs: docker-compose logs backend
)

echo.
echo ╔════════════════════════════════════════════╗
echo ║          Deployment Successful!            ║
echo ╚════════════════════════════════════════════╝
echo.
echo [URL] Access addresses:
echo   Frontend: http://localhost:3000
echo   Backend:  http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo.
echo [CMD] Useful commands:
echo   View logs:    deploy.bat logs
echo   Stop services: deploy.bat stop
echo   Rebuild:      deploy.bat build
echo.
goto :eof

:do_build
echo [INFO] Rebuilding images with BuildKit...
set DOCKER_BUILDKIT=1
set COMPOSE_DOCKER_CLI_BUILD=1
docker-compose build --no-cache
echo [INFO] Build complete. Run 'deploy.bat start' to start services.
goto :eof

:do_stop
echo [INFO] Stopping services...
docker-compose down
echo [OK] Services stopped.
goto :eof

:do_logs
echo [INFO] Showing logs (Ctrl+C to exit)...
docker-compose logs -f
goto :eof

:do_clean
echo [WARN] This will remove all containers and images!
echo Press any key to continue or Ctrl+C to cancel...
pause >nul
echo [INFO] Removing containers and images...
docker-compose down -v --rmi local
echo [OK] Cleanup complete.
goto :eof

:show_help
echo.
echo Usage: deploy.bat [command]
echo.
echo Commands:
echo   (none)  Start services (build if needed)
echo   build   Rebuild all images
echo   stop    Stop all services
echo   logs    Show live logs
echo   clean   Remove containers and images
echo   help    Show this help
echo.
echo Environment Variables (in .env):
echo   ZHIPUAI_API_KEY     - ZhipuAI API key (required)
echo   NEXT_PUBLIC_API_URL - Backend URL for frontend (default: http://localhost:8000)
echo   HF_ENDPOINT         - HuggingFace mirror (default: https://hf-mirror.com)
echo.
goto :eof

endlocal
