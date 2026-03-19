#!/bin/bash
#
# Translation Manager - Stop Services Script
#
# This script will:
# 1. Kill all backend processes (port 8000)
# 2. Kill all frontend processes (port 5173)
# 3. Clean up any orphaned processes
#
# Usage:
#   ./stop-services.sh
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

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}   Translation Manager - Stopping Services     ${NC}"
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
        echo -e "${YELLOW}🔍 Found processes on port $port ($service_name)${NC}"
        local pids=$(lsof -ti:$port)
        local count=0

        for pid in $pids; do
            # Get process name
            local proc_name=$(ps -p $pid -o comm= 2>/dev/null || echo "unknown")
            echo -e "${YELLOW}   Killing PID $pid ($proc_name)...${NC}"
            kill -9 $pid 2>/dev/null || true
            count=$((count + 1))
        done

        sleep 1

        # Verify processes are killed
        if check_port $port; then
            echo -e "${RED}❌ Failed to kill all processes on port $port${NC}"
            echo -e "${RED}   Remaining processes:${NC}"
            lsof -i:$port
            return 1
        else
            echo -e "${GREEN}✓ Stopped $count process(es) on port $port${NC}"
        fi
    else
        echo -e "${BLUE}ℹ️  No processes found on port $port ($service_name)${NC}"
    fi
}

# Function to kill processes by name pattern
kill_by_pattern() {
    local pattern=$1
    local service_name=$2

    local pids=$(pgrep -f "$pattern" 2>/dev/null || true)

    if [ -n "$pids" ]; then
        echo -e "${YELLOW}🔍 Found processes matching '$pattern' ($service_name)${NC}"
        local count=0

        for pid in $pids; do
            local proc_name=$(ps -p $pid -o comm= 2>/dev/null || echo "unknown")
            echo -e "${YELLOW}   Killing PID $pid ($proc_name)...${NC}"
            kill -9 $pid 2>/dev/null || true
            count=$((count + 1))
        done

        echo -e "${GREEN}✓ Stopped $count process(es) matching '$pattern'${NC}"
    else
        echo -e "${BLUE}ℹ️  No processes found matching '$pattern' ($service_name)${NC}"
    fi
}

# Stop services
echo -e "${BLUE}Step 1: Stopping Backend (port 8000)...${NC}"
echo ""
kill_port 8000 "Backend (FastAPI)"

echo ""
echo -e "${BLUE}Step 2: Stopping Frontend (port 5173)...${NC}"
echo ""
kill_port 5173 "Frontend (Vite)"

echo ""
echo -e "${BLUE}Step 3: Cleaning up orphaned processes...${NC}"
echo ""

# Kill any remaining uvicorn processes
kill_by_pattern "uvicorn.*app:app" "Uvicorn Backend"

# Kill any remaining vite/npm processes related to our frontend
kill_by_pattern "vite.*translation_manager/frontend" "Vite Frontend"

# Kill any node processes running from our frontend directory
kill_by_pattern "node.*translation_manager/frontend" "Node Frontend"

echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}✓ All services stopped successfully!${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Clean up log files if they exist
BACKEND_LOG="$SCRIPT_DIR/backend/backend.log"
FRONTEND_LOG="$SCRIPT_DIR/frontend/frontend.log"

if [ -f "$BACKEND_LOG" ] || [ -f "$FRONTEND_LOG" ]; then
    echo -e "${YELLOW}Log files:${NC}"
    [ -f "$BACKEND_LOG" ] && echo -e "  Backend:  $BACKEND_LOG ($(du -h "$BACKEND_LOG" | cut -f1))"
    [ -f "$FRONTEND_LOG" ] && echo -e "  Frontend: $FRONTEND_LOG ($(du -h "$FRONTEND_LOG" | cut -f1))"
    echo ""
    echo -e "${YELLOW}To clear logs:${NC}"
    echo -e "  rm -f $BACKEND_LOG $FRONTEND_LOG"
    echo ""
fi
