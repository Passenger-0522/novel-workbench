#!/bin/bash
# 小说工作台启动脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8765
PID_FILE="$SCRIPT_DIR/.server.pid"

# 检查是否已在运行
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "✅ 工作台已在运行（PID: $OLD_PID）"
    echo "🌐 正在打开浏览器..."
    open "http://localhost:$PORT"
    exit 0
  fi
fi

echo "🚀 启动小说工作台..."
echo "📁 项目：$(dirname "$SCRIPT_DIR")"

# 后台启动服务
cd "$SCRIPT_DIR"
nohup python3 server.py > "$SCRIPT_DIR/.server.log" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$PID_FILE"

# 等待服务启动
echo -n "⏳ 等待服务就绪"
for i in $(seq 1 15); do
  sleep 0.5
  if curl -s "http://localhost:$PORT/api/tree" > /dev/null 2>&1; then
    echo ""
    break
  fi
  echo -n "."
done

# 打开浏览器
echo "🌐 在浏览器中打开工作台..."
open "http://localhost:$PORT"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 小说工作台已启动"
echo "🌐 地址：http://localhost:$PORT"
echo "🛑 停止：运行 ./stop.sh"
echo "📋 日志：.workbench/.server.log"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
