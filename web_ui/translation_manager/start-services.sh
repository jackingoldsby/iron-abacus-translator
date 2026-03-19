#!/bin/bash
#
# Translation Manager - Start Services (DEPRECATED)
#
# This script has been moved to the project root.
# Redirecting to: ../../start-translation-services.sh
#
# Usage:
#   Use the root-level script instead:
#   ../../start-translation-services.sh
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}   Translation Manager - Starting Services     ${NC}"
echo -e "${BLUE}================================================${NC}"
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
            echo -e "${YELLOW}   Killing PID $pid...${NC}"
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

    echo -e "${BLUE}⏳ Waiting for $service_name to start on port $port...${NC}"

    while [ $count -lt $max_wait ]; do
        if check_port $port; then
            echo -e "${GREEN}✓ $service_name is running on port $port${NC}"
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done

    echo -e "${RED}❌ Timeout waiting for $service_name to start${NC}"
    return 1
}

# Step 1: Stop existing services
echo -e "${BLUE}Step 1: Stopping existing services...${NC}"
echo ""

kill_port 8000 "Backend (FastAPI)"
kill_port 5173 "Frontend (Vite)"

echo ""

# Step 2: Start Backend
echo -e "${BLUE}Step 2: Starting Backend (FastAPI on port 8000)...${NC}"
echo ""

if [ ! -d "$BACKEND_DIR" ]; then
    echo -e "${RED}❌ Backend directory not found: $BACKEND_DIR${NC}"
    exit 1
fi

cd "$BACKEND_DIR"

# Check if virtual environment exists
if [ ! -d "venv" ] && [ ! -d "../../../venv" ]; then
    echo -e "${YELLOW}⚠️  No virtual environment found. Install dependencies first:${NC}"
    echo -e "${YELLOW}   cd $BACKEND_DIR && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt${NC}"
    exit 1
fi

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "../../../venv" ]; then
    source ../../../venv/bin/activate
fi

# Check if uvicorn is available
if ! command -v uvicorn &> /dev/null; then
    echo -e "${RED}❌ uvicorn not found. Install requirements:${NC}"
    echo -e "${RED}   pip install -r requirements.txt${NC}"
    exit 1
fi

# Start backend in background
nohup uvicorn app:app --host 0.0.0.0 --port 8000 --reload > backend.log 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}✓ Backend started (PID: $BACKEND_PID)${NC}"
echo -e "${BLUE}  Log: $BACKEND_DIR/backend.log${NC}"

# Wait for backend to be ready
wait_for_port 8000 "Backend"

echo ""

# Step 3: Start Frontend
echo -e "${BLUE}Step 3: Starting Frontend (Vite on port 5173)...${NC}"
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

# Start frontend in background
nohup npm run dev > frontend.log 2>&1 &
FRONTEND_PID=$!
echo -e "${GREEN}✓ Frontend started (PID: $FRONTEND_PID)${NC}"
echo -e "${BLUE}  Log: $FRONTEND_DIR/frontend.log${NC}"

# Wait for frontend to be ready
wait_for_port 5173 "Frontend"

echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}✓ All services started successfully!${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "${GREEN}Backend:${NC}  http://localhost:8000"
echo -e "${GREEN}Frontend:${NC} http://localhost:5173"
echo ""
echo -e "${BLUE}Logs:${NC}"
echo -e "  Backend:  $BACKEND_DIR/backend.log"
echo -e "  Frontend: $FRONTEND_DIR/frontend.log"
echo ""
echo -e "${YELLOW}To view logs:${NC}"
echo -e "  tail -f $BACKEND_DIR/backend.log"
echo -e "  tail -f $FRONTEND_DIR/frontend.log"
echo ""
echo -e "${YELLOW}To stop services:${NC}"
echo -e "  ./stop-services.sh"
echo ""
