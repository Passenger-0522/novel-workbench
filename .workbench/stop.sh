#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.server.pid"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    rm "$PID_FILE"
    echo "🛑 小说工作台已停止（PID: $PID）"
  else
    rm "$PID_FILE"
    echo "ℹ️ 工作台未在运行"
  fi
else
  echo "ℹ️ 工作台未在运行"
fi
