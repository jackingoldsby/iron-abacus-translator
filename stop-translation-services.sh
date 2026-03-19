#!/bin/bash
#
# Translation Project - Stop All Services
#
# This script stops all translation system services:
# 1. Prefect Server (workflow orchestration)
# 2. Translation UI Backend (FastAPI API)
# 3. Translation UI Frontend (React UI)
#
# Usage:
#   ./stop-translation-services.sh
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
echo -e "${CYAN}║   Translation Project - Stopping Services     ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════╝${NC}"
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
            local proc_name=$(ps -p $pid -o comm= 2>/dev/null || echo "unknown")
            local proc_args=$(ps -p $pid -o args= 2>/dev/null || echo "")
            echo -e "${YELLOW}   Killing PID $pid${NC}"
            echo -e "${BLUE}      Process: $proc_name${NC}"
            echo -e "${BLUE}      Command: ${proc_args:0:60}...${NC}"
            kill -9 $pid 2>/dev/null || true
            count=$((count + 1))
        done

        sleep 1

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

# Function to kill processes by pattern
kill_by_pattern() {
    local pattern=$1
    local service_name=$2

    local pids=$(pgrep -f "$pattern" 2>/dev/null || true)

    if [ -n "$pids" ]; then
        echo -e "${YELLOW}🔍 Found processes matching '$pattern' ($service_name)${NC}"
        local count=0

        for pid in $pids; do
            local proc_name=$(ps -p $pid -o comm= 2>/dev/null || echo "unknown")
            echo -e "${YELLOW}   Killing PID $pid ($proc_name)${NC}"
            kill -9 $pid 2>/dev/null || true
            count=$((count + 1))
        done

        sleep 0.5
        echo -e "${GREEN}✓ Stopped $count process(es)${NC}"
    else
        echo -e "${BLUE}ℹ️  No processes found matching pattern${NC}"
    fi
}

# ============================================================================
# STEP 1: Stop Prefect Server
# ============================================================================

echo -e "${CYAN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│ Step 1: Stopping Prefect Server               │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────┘${NC}"
echo ""

kill_port $PREFECT_PORT "Prefect Server"

echo -e "${BLUE}Cleaning up orphaned Prefect processes...${NC}"
kill_by_pattern "prefect server start" "Prefect Server"
kill_by_pattern "prefect.server" "Prefect Server"

echo ""

# ============================================================================
# STEP 2: Stop Translation UI Backend
# ============================================================================

echo -e "${CYAN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│ Step 2: Stopping Translation UI Backend       │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────┘${NC}"
echo ""

kill_port $BACKEND_PORT "Translation UI Backend"

echo -e "${BLUE}Cleaning up orphaned Backend processes...${NC}"
kill_by_pattern "uvicorn.*app:app" "Uvicorn Backend"
kill_by_pattern "uvicorn.*translation_manager" "Uvicorn Backend"

echo ""

# ============================================================================
# STEP 3: Stop Translation UI Frontend
# ============================================================================

echo -e "${CYAN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│ Step 3: Stopping Translation UI Frontend      │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────┘${NC}"
echo ""

kill_port $FRONTEND_PORT "Translation UI Frontend"

echo -e "${BLUE}Cleaning up orphaned Frontend processes...${NC}"
kill_by_pattern "vite.*translation_manager" "Vite Frontend"
kill_by_pattern "node.*translation_manager/frontend" "Node Frontend"

echo ""

# ============================================================================
# STEP 4: Clean Up Any Remaining Related Processes
# ============================================================================

echo -e "${CYAN}┌────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│ Step 4: Final Cleanup                         │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────┘${NC}"
echo ""

# Kill any remaining Python processes related to our backend
echo -e "${BLUE}Checking for orphaned Python processes...${NC}"
kill_by_pattern "python.*translation_manager.*app:app" "Python Backend Processes"

# Kill any remaining Node processes from our frontend
echo -e "${BLUE}Checking for orphaned Node processes...${NC}"
kill_by_pattern "node.*vite.*5173" "Node Frontend Processes"

echo ""

# ============================================================================
# SUCCESS!
# ============================================================================

echo -e "${CYAN}╔════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       ✓ All Services Stopped Successfully!    ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════╝${NC}"
echo ""

# Show log files if they exist
LOG_FILES=(
    "$PROJECT_ROOT/prefect-server.log"
    "$BACKEND_DIR/backend.log"
    "$FRONTEND_DIR/frontend.log"
)

HAS_LOGS=false
for log in "${LOG_FILES[@]}"; do
    if [ -f "$log" ]; then
        HAS_LOGS=true
        break
    fi
done

if [ "$HAS_LOGS" = true ]; then
    echo -e "${BLUE}┌────────────────────────────────────────────────┐${NC}"
    echo -e "${BLUE}│ Log Files                                      │${NC}"
    echo -e "${BLUE}├────────────────────────────────────────────────┤${NC}"

    for log in "${LOG_FILES[@]}"; do
        if [ -f "$log" ]; then
            local size=$(du -h "$log" 2>/dev/null | cut -f1)
            local name=$(basename $(dirname "$log"))/$(basename "$log")
            printf "${BLUE}│${NC} %-46s ${BLUE}│${NC}\n" "$name ($size)"
        fi
    done

    echo -e "${BLUE}└────────────────────────────────────────────────┘${NC}"
    echo ""
    echo -e "${YELLOW}📋 To view logs:${NC}"
    for log in "${LOG_FILES[@]}"; do
        if [ -f "$log" ]; then
            echo -e "   ${CYAN}cat $log${NC}"
        fi
    done
    echo ""
    echo -e "${YELLOW}🗑️  To clear all logs:${NC}"
    echo -e "   ${CYAN}rm -f $PROJECT_ROOT/prefect-server.log${NC}"
    echo -e "   ${CYAN}rm -f $BACKEND_DIR/backend.log${NC}"
    echo -e "   ${CYAN}rm -f $FRONTEND_DIR/frontend.log${NC}"
    echo ""
fi

echo -e "${YELLOW}🚀 To restart services:${NC}"
echo -e "   ${CYAN}./start-translation-services.sh${NC}"
echo ""

# Verify all ports are free
echo -e "${BLUE}Verifying ports are free...${NC}"
ALL_FREE=true
for port in $PREFECT_PORT $BACKEND_PORT $FRONTEND_PORT; do
    if check_port $port; then
        echo -e "${RED}⚠️  Port $port is still in use${NC}"
        ALL_FREE=false
    else
        echo -e "${GREEN}✓ Port $port is free${NC}"
    fi
done

echo ""

if [ "$ALL_FREE" = true ]; then
    echo -e "${GREEN}✓ All ports are free and ready for restart${NC}"
else
    echo -e "${YELLOW}⚠️  Some ports are still in use. You may need to:${NC}"
    echo -e "${YELLOW}   1. Run this script again${NC}"
    echo -e "${YELLOW}   2. Manually kill processes: sudo lsof -ti:PORT | xargs kill -9${NC}"
fi

echo ""
