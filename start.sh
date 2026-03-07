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

# ─── 检查并激活虚拟环境 ───────────────────────────────────────────────────────
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
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

# ─── 参数处理与配置 ──────────────────────────────────────────────────────────
ARG_MODE=$1
ARG_STRATEGY=$2
ARG_TARGET_TYPE=$3
ARG_TARGET_VAL=$4

# 默认配置
MODE_FLAG="--mode auto"
MODE_NAME="🤖 自动模式 (Auto)"
STRATEGY_FLAG="range"
STRATEGY_NAME="📊 Range 策略"
TASK_FLAG="--profit 2000"
TASK_NAME="💰 盈利目标: 2000"
HEADLESS_FLAG=""
HEADLESS_NAME="🖥️ 显示窗口"
SKIP_INTERACTIVE=true

# 若传入 --interactive 则进入手动选择流程
if [[ "$1" == "--interactive" || "$1" == "-i" ]]; then
    SKIP_INTERACTIVE=false
    shift
    ARG_MODE=$1
    ARG_STRATEGY=$2
    ARG_TARGET_TYPE=$3
    ARG_TARGET_VAL=$4
fi

# 处理命令行参数
if [ -n "$ARG_MODE" ]; then
    SKIP_INTERACTIVE=true
    case "$ARG_MODE" in
        auto)
            MODE_FLAG="--mode auto"
            MODE_NAME="🤖 自动模式 (Auto)"
            ;;
        apprentice)
            MODE_FLAG="--mode apprentice"
            MODE_NAME="📚 学徒模式 (Apprentice)"
            STRATEGY_FLAG=""
            ;;
        assist)
            MODE_FLAG="--mode assist"
            MODE_NAME="💡 辅助模式 (Assist)"
            ;;
    esac
fi

if [ -n "$ARG_STRATEGY" ]; then
    case "$ARG_STRATEGY" in
        gto) STRATEGY_FLAG="gto" ; STRATEGY_NAME="📐 GTO 策略" ;;
        checkorfold) STRATEGY_FLAG="checkorfold" ; STRATEGY_NAME="🛡️ 保育策略" ;;
        exploitative) STRATEGY_FLAG="exploitative" ; STRATEGY_NAME="🎯 剥削策略" ;;
        range) STRATEGY_FLAG="range" ; STRATEGY_NAME="📊 Range 策略" ;;
        headless) HEADLESS_FLAG="--headless" ; HEADLESS_NAME="👻 无头模式" ;;
    esac
fi

# 任务目标参数处理
if [ -n "$ARG_TARGET_TYPE" ] && [ -n "$ARG_TARGET_VAL" ]; then
    case "$ARG_TARGET_TYPE" in
        profit) TASK_FLAG="--profit $ARG_TARGET_VAL" ; TASK_NAME="💰 盈利目标: $ARG_TARGET_VAL" ;;
        hands) TASK_FLAG="--hands $ARG_TARGET_VAL" ; TASK_NAME="🃏 局数限制: $ARG_TARGET_VAL" ;;
        cycles) TASK_FLAG="--cycles $ARG_TARGET_VAL" ; TASK_NAME="🔄 周期限制: $ARG_TARGET_VAL" ;;
        time) TASK_FLAG="--duration $ARG_TARGET_VAL" ; TASK_NAME="⏱️ 时间限制: $ARG_TARGET_VAL 分钟" ;;
    esac
fi

if [ "$SKIP_INTERACTIVE" = false ]; then
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║         🃏 Poker AI 启动配置             ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo ""

    # 1. 模式选择
    echo -e "${BOLD}【1/4】运行模式${NC}"
    echo -e "  ${GREEN}[1]${NC} assist     - 辅助模式"
    echo -e "  ${CYAN}[2]${NC} auto       - 自动模式"
    echo -e "  ${YELLOW}[3]${NC} apprentice - 学徒模式"
    echo ""
    read -rp "  请输入模式 [1/2/3, 默认 1]: " mode_choice
    case "$mode_choice" in
        2) MODE_FLAG="--mode auto" ; MODE_NAME="🤖 自动模式 (Auto)" ;;
        3) MODE_FLAG="--mode apprentice" ; MODE_NAME="📚 学徒模式 (Apprentice)" ; STRATEGY_FLAG="" ;;
        *) MODE_FLAG="--mode assist" ; MODE_NAME="💡 辅助模式 (Assist)" ;;
    esac

    # 2. 策略选择
    if [ "$MODE_FLAG" = "--mode auto" ] || [ "$MODE_FLAG" = "--mode assist" ]; then
        echo ""
        echo -e "${BOLD}【2/4】决策策略${NC}"
        echo -e "  ${GREEN}[1]${NC} range        - Range 策略（默认）"
        echo -e "  ${CYAN}[2]${NC} exploitative - 剥削性策略"
        echo -e "  ${YELLOW}[3]${NC} gto          - GTO 策略"
        echo -e "  ${RED}[4]${NC} checkorfold  - 保守策略"
        echo ""
        read -rp "  请输入策略 [1/2/3/4, 默认 1]: " strat_choice
        case "$strat_choice" in
            2) STRATEGY_FLAG="exploitative" ; STRATEGY_NAME="🎯 剥削性 (Exploitative)" ;;
            3) STRATEGY_FLAG="gto" ; STRATEGY_NAME="📐 GTO 策略" ;;
            4) STRATEGY_FLAG="checkorfold" ; STRATEGY_NAME="🛡️ 保守 (CheckOrFold)" ;;
            *) STRATEGY_FLAG="range" ; STRATEGY_NAME="📊 Range 策略" ;;
        esac
    fi

    # 3. 任务目标 (仅自动模式)
    if [ "$MODE_FLAG" = "--mode auto" ]; then
        echo ""
        echo -e "${BOLD}【3/4】任务目标${NC}"
        echo -e "  ${GREEN}[1]${NC} 无限运行"
        echo -e "  ${CYAN}[2]${NC} 盈利目标 (profit)"
        echo -e "  ${YELLOW}[3]${NC} 局数限制 (hands)"
        echo -e "  ${RED}[4]${NC} 时间限制 (minutes)"
        echo ""
        read -rp "  请选择目标类型 [1-4, 默认 1]: " task_choice
        case "$task_choice" in
            2)
                read -rp "  请输入盈利金额目标: " t_val
                TASK_FLAG="--profit $t_val"
                TASK_NAME="� 盈利目标: $t_val"
                ;;
            3)
                read -rp "  请输入局数上限: " t_val
                TASK_FLAG="--hands $t_val"
                TASK_NAME="� 局数限制: $t_val"
                ;;
            4)
                read -rp "  请输入运行分钟数: " t_val
                TASK_FLAG="--duration $t_val"
                TASK_NAME="⏱️ 时间限制: $t_val 分钟"
                ;;
        esac
    fi

    # 4. 浏览器
    echo ""
    echo -e "${BOLD}【4/4】浏览器模式${NC}"
    echo -e "  ${GREEN}[1]${NC} 显示窗口"
    echo -e "  ${CYAN}[2]${NC} 无头模式"
    echo ""
    read -rp "  请输入选项 [1/2, 默认 1]: " head_choice
    if [ "$head_choice" = "2" ]; then
        HEADLESS_FLAG="--headless"
        HEADLESS_NAME="👻 无头模式"
    fi
fi

# ─── 汇总并确认 ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║           📋 启动配置确认                ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo -e "  运行模式: ${CYAN}$MODE_NAME${NC}"
[ -n "$STRATEGY_FLAG" ] && echo -e "  决策策略: ${CYAN}$STRATEGY_NAME${NC}"
[ "$MODE_FLAG" = "--mode auto" ] && echo -e "  任务目标: ${CYAN}$TASK_NAME${NC}"
echo -e "  浏览器:   ${CYAN}$HEADLESS_NAME${NC}"
echo ""

if [ "$SKIP_INTERACTIVE" = true ]; then
    confirm="Y"
else
    read -rp "  确认启动？[Y/n]: " confirm
fi

if [[ "$confirm" =~ ^[Nn]$ ]]; then
    exit 0
fi

# ─── 准备启动 ─────────────────────────────────────────────────────────────────
mkdir -p logs data

# 深度清理可能残留的浏览器锁文件和损坏标志
if [ -d "data/browser_data" ]; then
    find data/browser_data -name "SingletonLock" -delete 2>/dev/null
    find data/browser_data -name "SingletonCookie" -delete 2>/dev/null
    find data/browser_data -name "SingletonSocket" -delete 2>/dev/null
    # 有时清理这些文件能解决“个人资料”报错
fi

LOG_FILE="logs/poker_ai_$(date +%Y%m%d_%H%M%S).log"
LOG_LATEST="logs/poker_ai.log"
CMD="python -m src.main $MODE_FLAG"
[ -n "$STRATEGY_FLAG" ] && CMD="$CMD --strategy $STRATEGY_FLAG"
[ -n "$TASK_FLAG" ] && CMD="$CMD $TASK_FLAG"
[ -n "$HEADLESS_FLAG" ] && CMD="$CMD $HEADLESS_FLAG"

# 导出环境变量供直接策略读取 (兼容性)
[ -n "$STRATEGY_FLAG" ] && export POKER_STRATEGY="$STRATEGY_FLAG"

echo ""
echo -e "${GREEN}🚀 正在启动 Poker AI (nohup 后台模式)...${NC}"
echo -e "   命令: ${CYAN}$CMD${NC}"
echo -e "   日志: ${CYAN}$LOG_FILE${NC}"
echo ""

nohup $CMD >> "$LOG_FILE" 2>&1 &
POKER_PID=$!
echo $POKER_PID > "$PID_FILE"
# 建立软链接 logs/poker_ai.log 指向最新日志
ln -sf "$(basename "$LOG_FILE")" "$LOG_LATEST"

sleep 1
if ps -p "$POKER_PID" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 已在后台启动 (PID: $POKER_PID)${NC}"
    echo -e "   实时查看日志: ${CYAN}tail -f $LOG_FILE${NC}"
else
    echo -e "${RED}❌ 启动失败，请检查日志: $LOG_FILE${NC}"
    rm -f "$PID_FILE"
fi
