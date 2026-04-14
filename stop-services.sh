#!/bin/bash
# Village Planning System Stop Script
# Cross-platform compatible (Linux and Windows/Git Bash)

set -e

echo "==================================="
echo "  Village Planning System - Stop"
echo "==================================="
echo ""

STOPPED=0

# Detect OS
IS_WINDOWS=false
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
  IS_WINDOWS=true
fi

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

# Function: Get process info
get_process_info() {
  local pid=$1
  if [ "$IS_WINDOWS" = true ]; then
    tasklist //FI "PID eq $pid" //FO CSV //NH 2>/dev/null | cut -d'"' -f2
  else
    ps -p "$pid" -o comm= 2>/dev/null || echo "Unknown"
  fi
}

# Function: Get PIDs listening on port
get_port_pids() {
  local port=$1
  if [ "$IS_WINDOWS" = true ]; then
    netstat -ano 2>/dev/null | grep ":$port.*LISTENING" | awk '{print $5}' | sort -u
  else
    # Use ss or lsof
    if command -v ss >/dev/null 2>&1; then
      ss -tlnp 2>/dev/null | grep ":$port" | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u
    elif command -v lsof >/dev/null 2>&1; then
      lsof -t -i ":$port" 2>/dev/null | sort -u
    fi
  fi
}

# 1. Stop backend
echo "Checking backend service..."
if [ -f logs/backend.pid ]; then
  BACKEND_PID=$(cat logs/backend.pid)
  echo "  PID file: $BACKEND_PID"

  if is_process_running "$BACKEND_PID"; then
    echo -e "  ${GREEN}Stopping backend${NC} (PID: $BACKEND_PID)..."
    kill_process "$BACKEND_PID"
    sleep 1
    echo -e "  ${GREEN}done${NC} Backend stopped"
    STOPPED=1
  else
    echo -e "  ${YELLOW}warning${NC} Backend process not running (PID: $BACKEND_PID)"
  fi

  rm -f logs/backend.pid
else
  echo -e "  ${YELLOW}warning${NC} Backend PID file not found"
fi
echo ""

# 2. Stop frontend
echo "Checking frontend service..."
if [ -f logs/frontend.pid ]; then
  FRONTEND_PID=$(cat logs/frontend.pid)
  echo "  PID file: $FRONTEND_PID"

  if is_process_running "$FRONTEND_PID"; then
    echo -e "  ${GREEN}Stopping frontend${NC} (PID: $FRONTEND_PID)..."
    kill_process "$FRONTEND_PID"
    sleep 1
    echo -e "  ${GREEN}done${NC} Frontend stopped"
    STOPPED=1
  else
    echo -e "  ${YELLOW}warning${NC} Frontend process not running (PID: $FRONTEND_PID)"
  fi

  rm -f logs/frontend.pid
else
  echo -e "  ${YELLOW}warning${NC} Frontend PID file not found"
fi
echo ""

# 3. Cleanup residual processes
echo "Checking residual processes..."
FOUND=0

# Check backend port 8000
BACKEND_PIDS=$(get_port_pids 8000)
if [ -n "$BACKEND_PIDS" ]; then
  FOUND=1
  echo -e "  ${YELLOW}Found residual backend processes:${NC}"
  echo "$BACKEND_PIDS" | while read PID; do
    if [ -n "$PID" ]; then
      PROCESS_INFO=$(get_process_info "$PID")
      echo "    Port 8000: PID $PID (${PROCESS_INFO:-Unknown})"
      read -p "    Stop this process? (y/N): " CONFIRM
      if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
        kill_process "$PID" && echo "    done Stopped" || echo "    failed Stop failed"
      fi
    fi
  done
fi

# Check frontend ports 3000 and 3001
FRONTEND_PIDS=$(get_port_pids 3000)
FRONTEND_PIDS_3001=$(get_port_pids 3001)
if [ -n "$FRONTEND_PIDS" ] || [ -n "$FRONTEND_PIDS_3001" ]; then
  FOUND=1
  echo -e "  ${YELLOW}Found residual frontend processes:${NC}"
  for PID in $FRONTEND_PIDS $FRONTEND_PIDS_3001; do
    if [ -n "$PID" ]; then
      PROCESS_INFO=$(get_process_info "$PID")
      echo "    Port 3000/3001: PID $PID (${PROCESS_INFO:-Unknown})"
      read -p "    Stop this process? (y/N): " CONFIRM
      if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
        kill_process "$PID" && echo "    done Stopped" || echo "    failed Stop failed"
      fi
    fi
  done
fi

if [ $FOUND -eq 0 ]; then
  echo -e "  ${GREEN}done${NC} No residual processes"
fi
echo ""

# 4. Final status
echo "==================================="
if [ $STOPPED -eq 1 ]; then
  echo -e "  ${GREEN}done${NC} Services stopped"
else
  echo -e "  ${YELLOW}warning${NC} No running services found"
fi
echo "==================================="