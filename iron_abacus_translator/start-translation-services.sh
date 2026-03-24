#!/bin/bash
#
# Translation Project - Start All Services
#
# This script manages the complete translation system:
# 1. Prefect Server (workflow orchestration)
# 2. Translation UI Backend (FastAPI API)
# 3. Translation UI Frontend (React UI)
#
# Usage:
#   ./start-translation-services.sh
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get script directory (project root)
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
UI_DIR="$PROJECT_ROOT/web_ui/translation_manager"
BACKEND_DIR="$UI_DIR/backend"
FRONTEND_DIR="$UI_DIR/frontend"

# Service ports
PREFECT_PORT=4200
BACKEND_PORT=8000
FRONTEND_PORT=5173

echo -e "${CYAN}╔════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   Translation Project - Starting Services     ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Project Root:${NC} $PROJECT_ROOT"
echo ""

# Function to check if a process is running on a port
check_port() {
    local port=$1
    lsof -ti:$port > /dev/null 2>&1
}

# Function to kill processes on a port
kill_port() {
    local port=$1
    local service_name=$2

    if check_port $port; then
        echo -e "${YELLOW}⚠️  Found existing process on port $port ($service_name)${NC}"
        local pids=$(lsof -ti:$port)
        for pid in $pids; do
            local proc_name=$(ps -p $pid -o comm= 2>/dev/null || echo "unknown")
            echo -e "${YELLOW}   Killing PID $pid ($proc_name)...${NC}"
            kill -9 $pid 2>/dev/null || true
        done
        sleep 1

        if check_port $port; then
            echo -e "${RED}❌ Failed to kill process on port $port${NC}"
            return 1
        else
            echo -e "${GREEN}✓ Stopped existing $service_name${NC}"
        fi
    fi
}

# Function to wait for port to be available
wait_for_port() {
    local port=$1
    local service_name=$2
    local max_wait=30
    local count=0

    echo -e "${BLUE}⏳ Waiting for $service_name on port $port...${NC}"

    while [ $count -lt $max_wait ]; do
        if check_port $port; then
            echo -e "${GREEN}✓ $service_name is running${NC}"
            return 0
        fi
        sleep 1
        count=$((count + 1))
        if [ $((count % 5)) -eq 0 ]; then
            echo -e "${BLUE}   Still waiting... (${count}s)${NC}"
        fi
    done

    echo -e "${RED}❌ Timeout waiting for $service_name${NC}"
    return 1
}

# Function to check if command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# ============================================================================
# STEP 0: Validate Environment
# ============================================================================

echo -e "${CYAN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│ Step 0: Validating Environment                │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────┘${NC}"
echo ""

# Check Python
if ! command_exists python3; then
    echo -e "${RED}❌ Python 3 not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python 3: $(python3 --version)${NC}"

# Check Node
if ! command_exists node; then
    echo -e "${RED}❌ Node.js not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Node.js: $(node --version)${NC}"

# Check npm
if ! command_exists npm; then
    echo -e "${RED}❌ npm not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ npm: $(npm --version)${NC}"

echo ""

# ============================================================================
# STEP 1: Stop Existing Services
# ============================================================================

echo -e "${CYAN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│ Step 1: Stopping Existing Services            │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────┘${NC}"
echo ""

kill_port $PREFECT_PORT "Prefect Server"
kill_port $BACKEND_PORT "Translation UI Backend"
kill_port $FRONTEND_PORT "Translation UI Frontend"

# Also kill by process name patterns
echo -e "${BLUE}Cleaning up orphaned processes...${NC}"

# Prefect
if pgrep -f "prefect server start" > /dev/null; then
    pkill -9 -f "prefect server start" || true
    echo -e "${GREEN}✓ Killed orphaned Prefect processes${NC}"
fi

# Uvicorn
if pgrep -f "uvicorn.*app:app" > /dev/null; then
    pkill -9 -f "uvicorn.*app:app" || true
    echo -e "${GREEN}✓ Killed orphaned Uvicorn processes${NC}"
fi

# Vite
if pgrep -f "vite.*translation_manager" > /dev/null; then
    pkill -9 -f "vite.*translation_manager" || true
    echo -e "${GREEN}✓ Killed orphaned Vite processes${NC}"
fi

echo ""

# ============================================================================
# STEP 2: Start Prefect Server
# ============================================================================

echo -e "${CYAN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│ Step 2: Starting Prefect Server               │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────┘${NC}"
echo ""

# Check if Prefect is installed
if ! command_exists prefect; then
    echo -e "${YELLOW}⚠️  Prefect not found. Installing...${NC}"
    pip install prefect
fi

# Set Prefect API URL to local server
export PREFECT_API_URL="http://127.0.0.1:${PREFECT_PORT}/api"

# Start Prefect server in background
echo -e "${BLUE}Starting Prefect server on port $PREFECT_PORT...${NC}"
cd "$PROJECT_ROOT"

nohup prefect server start --host 0.0.0.0 --port $PREFECT_PORT > prefect-server.log 2>&1 &
PREFECT_PID=$!
echo -e "${GREEN}✓ Prefect server started (PID: $PREFECT_PID)${NC}"
echo -e "${BLUE}  Log: $PROJECT_ROOT/prefect-server.log${NC}"

# Wait for Prefect to be ready
wait_for_port $PREFECT_PORT "Prefect Server"

echo ""

# ============================================================================
# STEP 3: Start Translation UI Backend
# ============================================================================

echo -e "${CYAN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│ Step 3: Starting Translation UI Backend       │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────┘${NC}"
echo ""

if [ ! -d "$BACKEND_DIR" ]; then
    echo -e "${RED}❌ Backend directory not found: $BACKEND_DIR${NC}"
    exit 1
fi

cd "$BACKEND_DIR"

# Check for virtual environment
VENV_PATH=""
if [ -d "venv" ]; then
    VENV_PATH="$BACKEND_DIR/venv"
elif [ -d "$PROJECT_ROOT/venv" ]; then
    VENV_PATH="$PROJECT_ROOT/venv"
fi

if [ -z "$VENV_PATH" ]; then
    echo -e "${YELLOW}⚠️  No virtual environment found. Creating one...${NC}"
    python3 -m venv "$PROJECT_ROOT/venv"
    VENV_PATH="$PROJECT_ROOT/venv"
fi

# Activate virtual environment
source "$VENV_PATH/bin/activate"
echo -e "${GREEN}✓ Virtual environment activated${NC}"

# Check if uvicorn is available
if ! command_exists uvicorn; then
    echo -e "${YELLOW}⚠️  uvicorn not found. Installing dependencies...${NC}"
    pip install -r requirements.txt
fi

# Export Prefect API URL for backend
export PREFECT_API_URL="http://127.0.0.1:${PREFECT_PORT}/api"

# Start backend
echo -e "${BLUE}Starting FastAPI backend on port $BACKEND_PORT...${NC}"
nohup uvicorn app:app --host 0.0.0.0 --port $BACKEND_PORT --reload > backend.log 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}✓ Backend started (PID: $BACKEND_PID)${NC}"
echo -e "${BLUE}  Log: $BACKEND_DIR/backend.log${NC}"

# Wait for backend to be ready
wait_for_port $BACKEND_PORT "Translation UI Backend"

echo ""

# ============================================================================
# STEP 4: Start Translation UI Frontend
# ============================================================================

echo -e "${CYAN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│ Step 4: Starting Translation UI Frontend      │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────┘${NC}"
echo ""

if [ ! -d "$FRONTEND_DIR" ]; then
    echo -e "${RED}❌ Frontend directory not found: $FRONTEND_DIR${NC}"
    exit 1
fi

cd "$FRONTEND_DIR"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}⚠️  node_modules not found. Installing dependencies...${NC}"
    npm install
fi

# Start frontend
echo -e "${BLUE}Starting React frontend on port $FRONTEND_PORT...${NC}"
nohup npm run dev > frontend.log 2>&1 &
FRONTEND_PID=$!
echo -e "${GREEN}✓ Frontend started (PID: $FRONTEND_PID)${NC}"
echo -e "${BLUE}  Log: $FRONTEND_DIR/frontend.log${NC}"

# Wait for frontend to be ready
wait_for_port $FRONTEND_PORT "Translation UI Frontend"

echo ""

# ============================================================================
# SUCCESS!
# ============================================================================

echo -e "${CYAN}╔════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║          🎉 All Services Started! 🎉          ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${GREEN}│ Service URLs                                   │${NC}"
echo -e "${GREEN}├────────────────────────────────────────────────┤${NC}"
echo -e "${GREEN}│ Prefect UI:        ${NC}http://localhost:${PREFECT_PORT}${GREEN}        │${NC}"
echo -e "${GREEN}│ Backend API:       ${NC}http://localhost:${BACKEND_PORT}${GREEN}         │${NC}"
echo -e "${GREEN}│ Backend API Docs:  ${NC}http://localhost:${BACKEND_PORT}/docs${GREEN}    │${NC}"
echo -e "${GREEN}│ Translation UI:    ${NC}http://localhost:${FRONTEND_PORT}${GREEN}        │${NC}"
echo -e "${GREEN}└────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "${BLUE}┌────────────────────────────────────────────────┐${NC}"
echo -e "${BLUE}│ Log Files                                      │${NC}"
echo -e "${BLUE}├────────────────────────────────────────────────┤${NC}"
echo -e "${BLUE}│ Prefect:  ${NC}$PROJECT_ROOT/prefect-server.log${BLUE}│${NC}"
echo -e "${BLUE}│ Backend:  ${NC}$BACKEND_DIR/backend.log${BLUE}          │${NC}"
echo -e "${BLUE}│ Frontend: ${NC}$FRONTEND_DIR/frontend.log${BLUE}        │${NC}"
echo -e "${BLUE}└────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "${YELLOW}📋 To view logs in real-time:${NC}"
echo -e "   ${CYAN}tail -f $PROJECT_ROOT/prefect-server.log${NC}"
echo -e "   ${CYAN}tail -f $BACKEND_DIR/backend.log${NC}"
echo -e "   ${CYAN}tail -f $FRONTEND_DIR/frontend.log${NC}"
echo ""
echo -e "${YELLOW}🛑 To stop all services:${NC}"
echo -e "   ${CYAN}./stop-translation-services.sh${NC}"
echo ""
echo -e "${YELLOW}💡 Quick Start:${NC}"
echo -e "   1. Open Translation UI: ${CYAN}http://localhost:${FRONTEND_PORT}${NC}"
echo -e "   2. Navigate to Works Catalog"
echo -e "   3. Click '▶️ Translate' on a work"
echo -e "   4. Monitor workflow progress in real-time"
echo ""
