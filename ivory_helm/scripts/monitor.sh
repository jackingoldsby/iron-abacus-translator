#!/bin/bash
# Unified monitoring for Ivory Helm (OCR) and Iron Abacus (translation).
# Works locally or over SSH.
#
# Usage:
#   ./monitor.sh ocr /local/path/to/strips/                  # local Ivory Helm
#   ./monitor.sh ocr jbirp5:~/ocr_data/ocr_strips/三俠五義/  # remote Ivory Helm
#   ./monitor.sh translate D1379                              # local Iron Abacus
#   ./monitor.sh translate D1379 jbirp5                       # remote Iron Abacus
#
# Options:
#   INTERVAL=10 ./monitor.sh ocr /path/   # poll every 10s (default: 30)

set -euo pipefail

INTERVAL="${INTERVAL:-30}"
MODE="${1:-}"
TARGET="${2:-}"
REMOTE="${3:-}"

usage() {
    echo "Usage:"
    echo "  $0 ocr <strips_dir_or_host:path>"
    echo "  $0 translate <work_id> [ssh_host]"
    echo ""
    echo "Environment:"
    echo "  INTERVAL=N  poll every N seconds (default: 30)"
    exit 1
}

[[ -z "$MODE" || -z "$TARGET" ]] && usage

monitor_ocr() {
    local target="$1"

    # Determine if remote (contains ':')
    if [[ "$target" == *:* ]]; then
        local host="${target%%:*}"
        local path="${target#*:}"
        local cmd="ssh $host cat $path/progress.json 2>/dev/null"
    else
        local cmd="cat $target/progress.json 2>/dev/null"
    fi

    echo "Monitoring OCR: $target (every ${INTERVAL}s, Ctrl-C to stop)"
    echo "---"

    while true; do
        local output
        output=$(eval "$cmd" 2>/dev/null) || output=""
        local ts
        ts=$(date "+%H:%M:%S")

        if [[ -z "$output" ]]; then
            echo "[$ts] No progress.json yet"
        else
            local status book_id passed pending best_effort total round_num
            status=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
            book_id=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('book_id','?'))" 2>/dev/null || echo "?")
            passed=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('passed',0))" 2>/dev/null || echo "?")
            pending=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('pending',0))" 2>/dev/null || echo "?")
            best_effort=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('best_effort',0))" 2>/dev/null || echo "?")
            total=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_pages',0))" 2>/dev/null || echo "?")
            round_num=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('round',0))" 2>/dev/null || echo "?")

            echo "[$ts] $book_id | $status | round $round_num | passed $passed/$total | pending $pending | best_effort $best_effort"

            if [[ "$status" == "complete" || "$status" == "error" ]]; then
                if [[ "$status" == "error" ]]; then
                    echo ""
                    echo "ERROR:"
                    echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','unknown'))" 2>/dev/null || true
                fi
                echo "---"
                echo "Final status: $status"
                break
            fi
        fi
        sleep "$INTERVAL"
    done
}

monitor_translate() {
    local work_id="$1"
    local host="${2:-}"

    if [[ -n "$host" ]]; then
        local cmd="ssh $host 'cd ~/pipeline/iron_abacus_translator && python -m cli.run_pipeline $work_id --status'"
    else
        local script_dir
        script_dir="$(cd "$(dirname "$0")/../.." && pwd)"
        local cmd="cd $script_dir/iron_abacus_translator && python -m cli.run_pipeline $work_id --status"
    fi

    echo "Monitoring translation: $work_id ${host:+(via $host)} (every ${INTERVAL}s, Ctrl-C to stop)"
    echo "---"

    while true; do
        local ts
        ts=$(date "+%H:%M:%S")
        echo "[$ts]"
        eval "$cmd" 2>&1 || echo "  (status check failed)"
        echo "---"
        sleep "$INTERVAL"
    done
}

case "$MODE" in
    ocr)
        monitor_ocr "$TARGET"
        ;;
    translate)
        monitor_translate "$TARGET" "${REMOTE:-}"
        ;;
    *)
        usage
        ;;
esac
