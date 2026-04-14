#!/bin/bash
# Village Planning System Startup Script
# Cross-platform compatible (Linux and Windows/Git Bash)

set -e

echo "==================================="
echo "  Village Planning System - Start"
echo "==================================="
echo ""

# Detect OS
IS_WINDOWS=false
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
  IS_WINDOWS=true
fi

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Function: Check if process is running
is_process_running() {
  local pid=$1
  if [ "$IS_WINDOWS" = true ]; then
    tasklist //FI "PID eq $pid" 2>&1 | grep -q "$pid" 2>/dev/null
  else
    ps -p "$pid" >/dev/null 2>&1
  fi
}

# Function: Kill process by PID
kill_process() {
  local pid=$1
  if [ "$IS_WINDOWS" = true ]; then
    taskkill //F //PID "$pid" > /dev/null 2>&1 || true
  else
    kill -9 "$pid" 2>/dev/null || true
  fi
}

# Function: Check if port is listening
is_port_listening() {
  local port=$1
  if [ "$IS_WINDOWS" = true ]; then
    netstat -ano 2>/dev/null | grep -q ":$port.*LISTENING"
  else
    ss -tlnp 2>/dev/null | grep -q ":$port" || lsof -i ":$port" >/dev/null 2>&1
  fi
}

# 1. Initialize logs directory
echo "Initializing logs directory..."
mkdir -p logs
rm -f logs/backend_*.log logs/frontend_*.log
echo -e "  ${GREEN}done${NC} Logs directory ready"
echo ""

# 2. Stop old processes (if exist)
echo "Checking and stopping old processes..."
if [ -f logs/backend.pid ]; then
  OLD_PID=$(cat logs/backend.pid)
  if is_process_running "$OLD_PID"; then
    echo "  Stopping old backend process (PID: $OLD_PID)"
    kill_process "$OLD_PID"
  fi
  rm -f logs/backend.pid
fi

if [ -f logs/frontend.pid ]; then
  OLD_PID=$(cat logs/frontend.pid)
  if is_process_running "$OLD_PID"; then
    echo "  Stopping old frontend process (PID: $OLD_PID)"
    kill_process "$OLD_PID"
  fi
  rm -f logs/frontend.pid
fi
echo -e "  ${GREEN}done${NC} Old processes cleaned"
echo ""

# 3. Start backend service
echo -e "${BLUE}Starting backend service...${NC}"
cd backend
nohup python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 --no-access-log > ../logs/backend_stdout.log 2> ../logs/backend_stderr.log &
BACKEND_PID=$!
echo $BACKEND_PID > ../logs/backend.pid
echo -e "  ${GREEN}done${NC} Backend starting... (PID: $BACKEND_PID)"
cd ..

# Wait for backend to start
echo "  Waiting for backend to be ready..."
for i in {1..15}; do
  sleep 1
  if is_port_listening 8000; then
    echo -e "  ${GREEN}done${NC} Backend service started: http://localhost:8000"
    break
  fi
  if [ $i -eq 15 ]; then
    echo -e "  ${RED}failed${NC} Backend startup timeout, check logs:"
    echo "  ===== stderr ====="
    tail -n 20 logs/backend_stderr.log 2>/dev/null || echo "  (no stderr output)"
    echo "  ===== stdout ====="
    tail -n 20 logs/backend_stdout.log 2>/dev/null || echo "  (no stdout output)"
    exit 1
  fi
done
echo ""

# 4. Start frontend service
echo -e "${BLUE}Starting frontend service...${NC}"
cd frontend
nohup npm run dev > ../logs/frontend_stdout.log 2> ../logs/frontend_stderr.log &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../logs/frontend.pid
echo -e "  ${GREEN}done${NC} Frontend starting... (PID: $FRONTEND_PID)"
cd ..

# Wait for frontend to start
echo "  Waiting for frontend to be ready..."
FRONTEND_PORT=""
for i in {1..20}; do
  sleep 1
  # Extract port from log
  FRONTEND_PORT=$(grep -o "Local:.*http://localhost:[0-9]*" logs/frontend_stdout.log 2>/dev/null | grep -o "[0-9]*$" | head -1)
  if [ -n "$FRONTEND_PORT" ]; then
    echo -e "  ${GREEN}done${NC} Frontend service started: http://localhost:$FRONTEND_PORT"
    break
  fi
  if [ $i -eq 20 ]; then
    echo -e "  ${YELLOW}warning${NC}  Frontend may still be starting, default port: 3001"
    FRONTEND_PORT=3001
  fi
done
echo ""

# 5. Show service status
echo "==================================="
echo -e "  ${GREEN}done${NC} Services started successfully!"
echo "==================================="
echo ""
echo "Access URLs:"
echo "  Frontend: ${BLUE}http://localhost:$FRONTEND_PORT${NC}"
echo "  Backend:  ${BLUE}http://localhost:8000${NC}"
echo "  API Docs: ${BLUE}http://localhost:8000/docs${NC}"
echo ""
echo "Process Info:"
echo "  Backend PID:  ${GREEN}$BACKEND_PID${NC}"
echo "  Frontend PID: ${GREEN}$FRONTEND_PID${NC}"
echo ""
echo "Log Files:"
echo "  Backend: ${BLUE}tail -f logs/backend_stdout.log${NC}"
echo "           ${BLUE}tail -f logs/backend_stderr.log${NC}"
echo "  Frontend: ${BLUE}tail -f logs/frontend_stdout.log${NC}"
echo "            ${BLUE}tail -f logs/frontend_stderr.log${NC}"
echo ""
echo "Stop Services:"
echo "  ${YELLOW}./stop-services.sh${NC}"
echo "  Or: kill \$(cat logs/backend.pid) && kill \$(cat logs/frontend.pid)"
echo ""
echo "==================================="