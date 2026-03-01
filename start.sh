#!/bin/bash

# Poker AI 启动脚本
# 使用方法: ./start.sh

# ─── 颜色定义 ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ─── 初始化 ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="data/poker_ai.pid"

# ─── 检查虚拟环境 ─────────────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo -e "${RED}错误: 虚拟环境不存在，请先运行 'uv sync' 创建虚拟环境${NC}"
    exit 1
fi

# ─── 停止进程函数 ─────────────────────────────────────────────────────────────
stop_running_process() {
    local pid="$1"
    echo -e "${YELLOW}正在停止 Poker AI (PID: $pid)...${NC}"
    kill "$pid" 2>/dev/null

    for i in {1..10}; do
        if ! ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Poker AI 已停止${NC}"
            rm -f "$PID_FILE"
            # 清理浏览器锁文件
            rm -f "data/browser_data/SingletonLock"
            return 0
        fi
        sleep 1
    done

    echo -e "${YELLOW}进程未响应，强制停止...${NC}"
    kill -9 "$pid" 2>/dev/null
    sleep 1

    if ! ps -p "$pid" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Poker AI 已强制停止${NC}"
        rm -f "$PID_FILE"
        rm -f "data/browser_data/SingletonLock"
        return 0
    else
        echo -e "${RED}❌ 错误: 无法停止进程 $pid${NC}"
        return 1
    fi
}

# ─── 检查是否已有进程在运行 ──────────────────────────────────────────────────
RUNNING_PID=""
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        RUNNING_PID="$OLD_PID"
    else
        # PID 文件残留，清理掉
        rm -f "$PID_FILE"
    fi
fi

if [ -n "$RUNNING_PID" ]; then
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║       ⚠️  Poker AI 正在运行              ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo -e "  当前进程 PID: ${CYAN}$RUNNING_PID${NC}"
    echo ""
    echo -e "  请选择操作:"
    echo -e "  ${GREEN}[1]${NC} 关闭（停止当前运行的进程）"
    echo -e "  ${YELLOW}[2]${NC} 重启（停止后重新启动）"
    echo -e "  ${RED}[3]${NC} 取消（保持当前运行，退出脚本）"
    echo ""
    read -rp "  请输入选项 [1/2/3]: " choice

    case "$choice" in
        1)
            stop_running_process "$RUNNING_PID"
            exit 0
            ;;
        2)
            stop_running_process "$RUNNING_PID"
            if [ $? -ne 0 ]; then
                exit 1
            fi
            echo ""
            echo -e "${CYAN}准备重新启动...${NC}"
            ;;
        3|*)
            echo -e "${NC}已取消，当前进程继续运行。${NC}"
            exit 0
            ;;
    esac
fi

# ─── 交互式参数配置 ──────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         🃏 Poker AI 启动配置             ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# 选择运行模式
echo -e "${BOLD}【1/3】运行模式${NC}"
echo -e "  ${GREEN}[1]${NC} assist     - 辅助模式（AI 在终端给出建议，你来操作）"
echo -e "  ${CYAN}[2]${NC} auto       - 自动模式（AI 全自动打牌）"
echo -e "  ${YELLOW}[3]${NC} apprentice - 学徒模式（AI 观察并记录你的操作）"
echo ""
read -rp "  请输入模式 [1/2/3，默认 1]: " mode_choice

case "$mode_choice" in
    2)
        MODE_FLAG="--auto"
        MODE_NAME="🤖 自动模式 (Auto)"
        ;;
    3)
        MODE_FLAG="--apprentice"
        MODE_NAME="📚 学徒模式 (Apprentice)"
        ;;
    *)
        MODE_FLAG=""
        MODE_NAME="💡 辅助模式 (Assist)"
        ;;
esac

# 选择策略（学徒模式不需要选策略）
STRATEGY_FLAG=""
STRATEGY_NAME="（学徒模式专用）"

if [ "$MODE_FLAG" != "--apprentice" ]; then
    echo ""
    echo -e "${BOLD}【2/3】决策策略${NC}"
    echo -e "  ${GREEN}[1]${NC} exploitative - 剥削性策略（根据对手弱点调整，默认）"
    echo -e "  ${CYAN}[2]${NC} gto          - GTO 博弈论最优策略（均衡打法）"
    echo -e "  ${YELLOW}[3]${NC} checkorfold  - 保守策略（只过牌或弃牌，用于测试）"
    echo ""
    read -rp "  请输入策略 [1/2/3，默认 1]: " strategy_choice

    case "$strategy_choice" in
        2)
            STRATEGY_FLAG="gto"
            STRATEGY_NAME="📐 GTO 博弈论最优"
            ;;
        3)
            STRATEGY_FLAG="checkorfold"
            STRATEGY_NAME="🛡️ 保守 (CheckOrFold)"
            ;;
        *)
            STRATEGY_FLAG="exploitative"
            STRATEGY_NAME="🎯 剥削性 (Exploitative)"
            ;;
    esac
else
    echo ""
    echo -e "  ${YELLOW}（学徒模式无需选择策略）${NC}"
fi

# 是否使用无头模式
echo ""
echo -e "${BOLD}【3/3】浏览器模式${NC}"
echo -e "  ${GREEN}[1]${NC} 显示浏览器窗口（默认，可观察运行过程）"
echo -e "  ${CYAN}[2]${NC} 无头模式（后台运行，不显示浏览器）"
echo ""
read -rp "  请输入选项 [1/2，默认 1]: " headless_choice

HEADLESS_FLAG=""
HEADLESS_NAME="🖥️ 显示窗口"
if [ "$headless_choice" = "2" ]; then
    HEADLESS_FLAG="--headless"
    HEADLESS_NAME="👻 无头模式"
fi

# ─── 汇总并确认 ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║           📋 启动配置确认                ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo -e "  运行模式: ${CYAN}$MODE_NAME${NC}"
if [ "$MODE_FLAG" != "--apprentice" ]; then
    echo -e "  决策策略: ${CYAN}$STRATEGY_NAME${NC}"
fi
echo -e "  浏览器:   ${CYAN}$HEADLESS_NAME${NC}"
echo ""
read -rp "  确认启动？[Y/n]: " confirm

if [[ "$confirm" =~ ^[Nn]$ ]]; then
    echo -e "${NC}已取消启动。${NC}"
    exit 0
fi

# ─── 准备启动 ─────────────────────────────────────────────────────────────────
mkdir -p logs
mkdir -p data

# 清理可能残留的浏览器锁文件
if [ -f "data/browser_data/SingletonLock" ]; then
    rm -f "data/browser_data/SingletonLock"
fi

# ─── 日志文件管理（固定使用 poker_ai.log，超过阈值则备份）─────────────────
LOG_FILE="logs/poker_ai.log"
LOG_BACKUP_THRESHOLD=$((5 * 1024 * 1024))  # 5MB

if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$LOG_SIZE" -ge "$LOG_BACKUP_THRESHOLD" ]; then
        BAK_FILE="logs/poker_ai.log.bak_$(date +%Y%m%d_%H%M%S)"
        mv "$LOG_FILE" "$BAK_FILE"
        echo -e "${YELLOW}📦 旧日志已备份: $BAK_FILE ($(( LOG_SIZE / 1024 ))KB)${NC}"
    fi
fi

# 构建启动命令
CMD="python -m src.main"
[ -n "$MODE_FLAG" ] && CMD="$CMD $MODE_FLAG"
[ -n "$HEADLESS_FLAG" ] && CMD="$CMD $HEADLESS_FLAG"

# 如果策略不为空，写入临时环境变量供 Python 读取
# （通过 POKER_STRATEGY 环境变量覆盖 config 中的策略设置）
if [ -n "$STRATEGY_FLAG" ]; then
    export POKER_STRATEGY="$STRATEGY_FLAG"
fi

# ─── 启动程序 ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}🚀 正在启动 Poker AI...${NC}"
echo -e "   日志文件: ${CYAN}$LOG_FILE${NC}"
echo -e "   命令: ${CYAN}$CMD${NC}"
echo ""

source .venv/bin/activate && eval "$CMD" 2>&1 | tee -a "$LOG_FILE" &
POKER_PID=$!

echo $POKER_PID > "$PID_FILE"
echo -e "${GREEN}✅ Poker AI 已启动 (PID: $POKER_PID)${NC}"
echo -e "   查看日志: ${CYAN}tail -f $LOG_FILE${NC}"
echo -e "   再次运行 ${CYAN}./start.sh${NC} 可关闭或重启"
echo ""

# 等待进程结束
wait $POKER_PID

# 清理 PID 文件
rm -f "$PID_FILE"
