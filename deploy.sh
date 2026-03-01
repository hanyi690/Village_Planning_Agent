#!/bin/bash
# ============================================
# Village Planning System - Docker Deploy Script
# ============================================
# 
# Usage:
#   ./deploy.sh           - Build and start services
#   ./deploy.sh build     - Rebuild images
#   ./deploy.sh stop      - Stop services
#   ./deploy.sh logs      - Show logs
#   ./deploy.sh clean     - Remove containers and images
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║   Village Planning System - Docker Deploy  ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Parse command
COMMAND=${1:-start}

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}[ERROR] Docker is not installed.${NC}"
    echo "Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}[ERROR] Docker is not running.${NC}"
    echo "Please start Docker and try again."
    exit 1
fi

# Check docker-compose
if ! command -v docker-compose &> /dev/null; then
    if ! docker compose version &> /dev/null; then
        echo -e "${RED}[ERROR] docker-compose is not installed.${NC}"
        exit 1
    fi
    # Use 'docker compose' plugin
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

# Check .env file
if [ ! -f .env ]; then
    echo -e "${YELLOW}[WARN] .env file not found. Creating from .env.example...${NC}"
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${BLUE}[INFO] Please edit .env file with your configuration.${NC}"
        echo -e "${BLUE}[INFO] Required: ZHIPUAI_API_KEY or other LLM API keys${NC}"
        echo ""
        read -p "Press Enter to continue or Ctrl+C to cancel..."
    else
        echo -e "${RED}[ERROR] .env.example not found. Please create .env file manually.${NC}"
        exit 1
    fi
fi

# Function: start services
do_start() {
    echo -e "${BLUE}[INFO] Starting services...${NC}"
    echo ""
    
    # Enable BuildKit for faster builds
    export DOCKER_BUILDKIT=1
    export COMPOSE_DOCKER_CLI_BUILD=1
    
    # Check if images exist
    if ! docker images village-planning-backend:latest --format "{{.ID}}" 2>/dev/null | grep -q .; then
        echo -e "${BLUE}[INFO] Images not found. Building for the first time...${NC}"
        echo -e "${BLUE}[INFO] This may take a few minutes...${NC}"
        echo ""
    fi
    
    $DOCKER_COMPOSE up -d
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR] Failed to start services.${NC}"
        exit 1
    fi
    
    echo ""
    echo -e "${BLUE}[INFO] Waiting for services to be healthy...${NC}"
    sleep 5
    
    # Check backend health
    echo -e "${BLUE}[INFO] Checking backend health...${NC}"
    RETRY=0
    while [ $RETRY -lt 10 ]; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo -e "  ${GREEN}[OK] Backend is healthy${NC}"
            break
        fi
        RETRY=$((RETRY+1))
        sleep 2
    done
    
    if [ $RETRY -eq 10 ]; then
        echo -e "  ${YELLOW}[WARN] Backend health check failed. Check logs: docker-compose logs backend${NC}"
    fi
    
    echo ""
    echo "╔════════════════════════════════════════════╗"
    echo "║          Deployment Successful!            ║"
    echo "╚════════════════════════════════════════════╝"
    echo ""
    echo "[URL] Access addresses:"
    echo "  Frontend: http://localhost:3000"
    echo "  Backend:  http://localhost:8000"
    echo "  API Docs: http://localhost:8000/docs"
    echo ""
    echo "[CMD] Useful commands:"
    echo "  View logs:     ./deploy.sh logs"
    echo "  Stop services: ./deploy.sh stop"
    echo "  Rebuild:       ./deploy.sh build"
    echo ""
}

# Function: build images
do_build() {
    echo -e "${BLUE}[INFO] Rebuilding images with BuildKit...${NC}"
    export DOCKER_BUILDKIT=1
    export COMPOSE_DOCKER_CLI_BUILD=1
    $DOCKER_COMPOSE build --no-cache
    echo -e "${GREEN}[INFO] Build complete. Run './deploy.sh start' to start services.${NC}"
}

# Function: stop services
do_stop() {
    echo -e "${BLUE}[INFO] Stopping services...${NC}"
    $DOCKER_COMPOSE down
    echo -e "${GREEN}[OK] Services stopped.${NC}"
}

# Function: show logs
do_logs() {
    echo -e "${BLUE}[INFO] Showing logs (Ctrl+C to exit)...${NC}"
    $DOCKER_COMPOSE logs -f
}

# Function: cleanup
do_clean() {
    echo -e "${YELLOW}[WARN] This will remove all containers and images!${NC}"
    read -p "Press Enter to continue or Ctrl+C to cancel..."
    echo -e "${BLUE}[INFO] Removing containers and images...${NC}"
    $DOCKER_COMPOSE down -v --rmi local
    echo -e "${GREEN}[OK] Cleanup complete.${NC}"
}

# Function: show help
show_help() {
    echo ""
    echo "Usage: ./deploy.sh [command]"
    echo ""
    echo "Commands:"
    echo "  (none)  Start services (build if needed)"
    echo "  build   Rebuild all images"
    echo "  stop    Stop all services"
    echo "  logs    Show live logs"
    echo "  clean   Remove containers and images"
    echo "  help    Show this help"
    echo ""
    echo "Environment Variables (in .env):"
    echo "  ZHIPUAI_API_KEY     - ZhipuAI API key (required)"
    echo "  NEXT_PUBLIC_API_URL - Backend URL for frontend (default: http://localhost:8000)"
    echo "  HF_ENDPOINT         - HuggingFace mirror (default: https://hf-mirror.com)"
    echo ""
}

# Execute command
case "$COMMAND" in
    start)
        do_start
        ;;
    build)
        do_build
        ;;
    stop)
        do_stop
        ;;
    logs)
        do_logs
        ;;
    clean)
        do_clean
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo -e "${RED}[ERROR] Unknown command: $COMMAND${NC}"
        show_help
        exit 1
        ;;
esac
