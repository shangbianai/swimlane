#!/bin/bash
# 安全停止服务的脚本（仅停止本项目的服务）

PROJECT_DIR="/opt/swimlane-tool"

cd $PROJECT_DIR

echo "停止服务..."

# 读取PID文件并停止进程
if [ -f backend.pid ]; then
    BACKEND_PID=$(cat backend.pid)
    if ps -p $BACKEND_PID > /dev/null 2>&1; then
        kill $BACKEND_PID
        echo "✅ 后端服务已停止 (PID: $BACKEND_PID)"
        rm backend.pid
    else
        echo "⚠️  后端服务进程不存在 (PID: $BACKEND_PID)"
        rm backend.pid
    fi
else
    echo "⚠️  未找到后端PID文件"
fi

# 额外检查：停止可能遗留的进程（仅本项目相关）
pkill -f "python3.*proxy_server.py" 2>/dev/null && echo "已清理遗留的服务进程" || true

echo ""
echo "服务已停止"

