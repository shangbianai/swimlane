#!/bin/bash
# 在服务器上安全启动所有服务的脚本

PROJECT_DIR="/opt/swimlane-tool"
MAIN_PORT=8222      # 主服务（泳道图工具）
ADMIN_PORT=6010     # 认证 & 管理后台

cd "$PROJECT_DIR"

check_port() {
    local port=$1
    local name=$2
    if netstat -tlnp 2>/dev/null | grep -q ":$port " || ss -tlnp 2>/dev/null | grep -q ":$port "; then
        echo "⚠️  端口 $port ($name) 已被占用，尝试终止旧进程..."
        fuser -k "$port/tcp" 2>/dev/null || true
        sleep 1
    fi
}

# ──────────────────────────────────────────
# 1. 安装依赖
# ──────────────────────────────────────────
echo "检查 Python 依赖..."
pip3 install -q -r requirements.txt 2>/dev/null || true

# ──────────────────────────────────────────
# 2. 停止旧进程
# ──────────────────────────────────────────
echo "停止旧进程..."
pkill -f "python3.*proxy_server.py"      2>/dev/null || true
pkill -f "python3.*auth_admin_server.py" 2>/dev/null || true
sleep 1

# ──────────────────────────────────────────
# 3. 启动主服务（泳道图工具 + AI API）
# ──────────────────────────────────────────
check_port $MAIN_PORT "泳道图主服务"
echo "启动主服务（端口 $MAIN_PORT）..."
PYTHONIOENCODING=utf-8 nohup python3 proxy_server.py $MAIN_PORT > backend.log 2>&1 &
echo $! > backend.pid
echo "  主服务 PID: $(cat backend.pid)"

# ──────────────────────────────────────────
# 4. 启动认证 & 管理后台（端口 6010）
# ──────────────────────────────────────────
check_port $ADMIN_PORT "认证/管理后台"
echo "启动认证/管理后台（端口 $ADMIN_PORT）..."
PYTHONIOENCODING=utf-8 nohup python3 auth_admin_server.py $ADMIN_PORT > admin.log 2>&1 &
echo $! > admin.pid
echo "  后台服务 PID: $(cat admin.pid)"

sleep 2

# ──────────────────────────────────────────
# 5. 验证
# ──────────────────────────────────────────
echo ""
echo "验证服务状态..."
for port_info in "$MAIN_PORT:泳道图主服务" "$ADMIN_PORT:认证/管理后台"; do
    port="${port_info%%:*}"
    name="${port_info##*:}"
    if netstat -tlnp 2>/dev/null | grep -q ":$port " || ss -tlnp 2>/dev/null | grep -q ":$port "; then
        echo "  ✅ $name（端口 $port）启动成功"
    else
        echo "  ❌ $name（端口 $port）启动失败，请查看日志"
    fi
done

SERVER_IP=$(curl -s --max-time 3 ifconfig.me 2>/dev/null || echo "182.92.97.169")

echo ""
echo "=========================================="
echo "  服务已启动"
echo "=========================================="
echo "  泳道图工具: http://$SERVER_IP:$MAIN_PORT/"
echo "  管理后台:   http://$SERVER_IP:$ADMIN_PORT/admin"
echo ""
echo "  管理命令:"
echo "    主服务日志:  tail -f $PROJECT_DIR/backend.log"
echo "    后台日志:    tail -f $PROJECT_DIR/admin.log"
echo "    停止所有:    pkill -f proxy_server.py; pkill -f auth_admin_server.py"
echo "=========================================="

