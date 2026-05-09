#!/bin/bash
# 在服务器上安全启动服务的脚本（不影响其他服务）

PROJECT_DIR="/opt/swimlane-tool"
PORT=8222

cd $PROJECT_DIR

# 检查端口是否被占用
check_port() {
    local port=$1
    local service_name=$2
    
    if netstat -tlnp 2>/dev/null | grep -q ":$port " || ss -tlnp 2>/dev/null | grep -q ":$port "; then
        echo "⚠️  警告: 端口 $port ($service_name) 已被占用！"
        echo "占用该端口的进程:"
        netstat -tlnp 2>/dev/null | grep ":$port " || ss -tlnp 2>/dev/null | grep ":$port "
        echo ""
        read -p "是否继续启动服务？(y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "已取消启动"
            exit 1
        fi
    fi
}

# 检查端口
check_port $PORT "泳道图服务"

# 停止可能存在的旧进程（仅停止本项目的进程）
echo "检查并停止旧进程..."
pkill -f "python3.*proxy_server.py" 2>/dev/null && echo "已停止旧的服务进程" || echo "没有运行中的服务进程"
sleep 2

# 启动单端口服务（前端页面 + API）
echo "启动泳道图服务（端口 $PORT）..."
cd "$PROJECT_DIR"
PYTHONIOENCODING=utf-8 nohup python3 proxy_server.py $PORT > backend.log 2>&1 &
SERVICE_PID=$!
echo $SERVICE_PID > backend.pid
echo "服务PID: $SERVICE_PID"

sleep 2

# 验证服务是否启动成功
echo ""
echo "验证服务状态..."
if netstat -tlnp 2>/dev/null | grep -q ":$PORT " || ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    echo "✅ 泳道图服务启动成功（端口 $PORT）"
else
    echo "❌ 泳道图服务启动失败，请查看日志: tail -f $PROJECT_DIR/backend.log"
fi

echo ""
echo "=========================================="
echo "服务启动完成"
echo "=========================================="
echo "访问地址: http://182.92.97.169:$PORT/index.html"
echo "API地址: http://182.92.97.169:$PORT/api/convert"
echo "健康检查: http://182.92.97.169:$PORT/api/health"
echo ""
echo "管理命令:"
echo "  查看进程: ps aux | grep proxy_server"
echo "  查看日志: tail -f $PROJECT_DIR/backend.log"
echo "  停止服务: kill \$(cat $PROJECT_DIR/backend.pid)"

