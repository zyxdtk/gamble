#!/bin/bash

# Poker AI 启动脚本
# 使用方法: ./start.sh

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# PID 文件路径
PID_FILE="data/poker_ai.pid"

# 检查虚拟环境是否存在
if [ ! -d ".venv" ]; then
    echo "错误: 虚拟环境不存在,请先运行 'uv sync' 创建虚拟环境"
    exit 1
fi

# 检查是否已经有进程在运行
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "检测到 Poker AI 已在运行 (PID: $OLD_PID)"
        echo "正在停止旧进程..."
        kill "$OLD_PID" 2>/dev/null
        sleep 2
        
        # 如果进程还在,强制杀死
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            echo "强制停止进程..."
            kill -9 "$OLD_PID" 2>/dev/null
            sleep 1
        fi
        
        echo "旧进程已停止"
    fi
    rm -f "$PID_FILE"
fi

# 清理可能残留的浏览器锁文件
if [ -f "data/browser_data/SingletonLock" ]; then
    echo "清理浏览器锁文件..."
    rm -f "data/browser_data/SingletonLock"
fi

# 创建日志目录
mkdir -p logs
mkdir -p data

# 生成日志文件名(带时间戳)
LOG_FILE="logs/poker_ai_$(date +%Y%m%d_%H%M%S).log"

# 激活虚拟环境并启动程序,输出同时显示在终端和保存到日志文件
echo "正在启动 Poker AI..."
echo "日志文件: $LOG_FILE"

# 后台启动并保存 PID
source .venv/bin/activate && python -m src.main 2>&1 | tee "$LOG_FILE" &
POKER_PID=$!

# 保存 PID 到文件
echo $POKER_PID > "$PID_FILE"
echo "Poker AI 已启动 (PID: $POKER_PID)"
echo "使用 './stop.sh' 停止程序"

# 等待进程结束
wait $POKER_PID

# 清理 PID 文件
rm -f "$PID_FILE"
