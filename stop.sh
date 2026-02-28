#!/bin/bash

# Poker AI 停止脚本
# 使用方法: ./stop.sh

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# PID 文件路径
PID_FILE="data/poker_ai.pid"

# 检查 PID 文件是否存在
if [ ! -f "$PID_FILE" ]; then
    echo "未找到运行中的 Poker AI 进程"
    exit 0
fi

# 读取 PID
PID=$(cat "$PID_FILE")

# 检查进程是否存在
if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "进程 $PID 不存在,可能已经停止"
    rm -f "$PID_FILE"
    exit 0
fi

# 停止进程
echo "正在停止 Poker AI (PID: $PID)..."
kill "$PID" 2>/dev/null

# 等待进程结束
for i in {1..10}; do
    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "Poker AI 已停止"
        rm -f "$PID_FILE"
        exit 0
    fi
    sleep 1
done

# 如果还没停止,强制杀死
echo "进程未响应,强制停止..."
kill -9 "$PID" 2>/dev/null
sleep 1

if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "Poker AI 已强制停止"
    rm -f "$PID_FILE"
else
    echo "错误: 无法停止进程 $PID"
    exit 1
fi
