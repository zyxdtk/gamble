import sys
import os
import asyncio
import argparse
from pathlib import Path

# Add project root to sys.path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.bot.task_manager import TaskManager, TaskConfig, TaskType


async def main():
    parser = argparse.ArgumentParser(
        description="Poker Bot - Auto play poker with AI strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Assist mode (default) - AI provides suggestions
  python src/main.py

  # Auto mode - AI plays automatically
  python src/main.py --mode auto

  # Auto mode with specific strategy and duration
  python src/main.py --mode auto --strategy checkorfold --hands 10

  # Auto mode with dealer cycle limit
  python src/main.py --mode auto --strategy gto --cycles 2

  # Auto mode with profit target
  python src/main.py --mode auto --strategy gto --profit 1000 --stop-loss 500

  # Apprentice mode - AI observes and learns
  python src/main.py --mode apprentice
        """
    )

    # 模式选择
    parser.add_argument(
        "--mode",
        choices=["assist", "auto", "apprentice"],
        default="assist",
        help="运行模式: assist=辅助模式(默认), auto=自动模式, apprentice=学徒模式"
    )

    # 策略类型
    parser.add_argument(
        "--strategy",
        choices=["gto", "checkorfold", "exploitative"],
        default="gto",
        help="使用的策略类型 (默认: gto)"
    )

    # 任务类型
    task_group = parser.add_mutually_exclusive_group()
    task_group.add_argument(
        "--hands",
        type=int,
        default=None,
        help="玩多少手牌后自动退出"
    )
    task_group.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="完成多少圈庄家位周期后自动退出"
    )
    task_group.add_argument(
        "--duration",
        type=int,
        default=None,
        help="运行多少分钟后自动退出"
    )
    task_group.add_argument(
        "--profit",
        type=int,
        default=None,
        help="盈利目标（达到此金额后退出）"
    )

    # 止损
    parser.add_argument(
        "--stop-loss",
        type=int,
        default=None,
        help="止损金额（亏损达到此金额后退出）"
    )

    # 浏览器选项
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式运行浏览器（不显示界面）"
    )

    # 兼容旧参数
    parser.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--apprentice", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # 处理旧参数兼容
    if args.auto:
        args.mode = "auto"
    elif args.apprentice:
        args.mode = "apprentice"

    # 创建任务配置
    if args.mode == "assist":
        # 辅助模式 - 不使用 TaskManager
        await run_assist_mode(args)
    elif args.mode == "apprentice":
        # 学徒模式
        await run_apprentice_mode(args)
    else:
        # 自动模式 - 使用 TaskManager
        await run_auto_mode(args)


async def run_auto_mode(args):
    """运行自动模式（使用 TaskManager）"""
    # 确定任务类型
    if args.cycles:
        task_type = TaskType.CYCLES
        target = args.cycles
    elif args.hands:
        task_type = TaskType.HANDS
        target = args.hands
    elif args.duration:
        task_type = TaskType.DURATION
        target = args.duration
    elif args.profit:
        task_type = TaskType.PROFIT_TARGET
        target = args.profit
    else:
        task_type = TaskType.INFINITE
        target = 0

    # 创建任务配置
    config = TaskConfig(
        task_type=task_type,
        target_value=target,
        strategy=args.strategy,
        stop_loss=args.stop_loss
    )

    # 创建并运行任务
    task_mgr = TaskManager(config)

    try:
        await task_mgr.initialize(headless=args.headless)
        await task_mgr.run()
    except KeyboardInterrupt:
        print("\n[MAIN] Stopping by user request...")
    finally:
        await task_mgr.stop()


async def run_assist_mode(args):
    """运行辅助模式（传统方式）"""
    from src.bot.browser_manager import BrowserManager

    os.environ["POKER_STRATEGY"] = args.strategy

    manager = BrowserManager(
        headless=args.headless,
        auto_mode=False,
        apprentice_mode=False
    )

    try:
        await manager.start()
        print("\n" + "="*50)
        print("🚀 ASSIST MODE: AI will provide suggestions in terminal.")
        print("="*50 + "\n")

        while True:
            await manager.run_tick()
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n[MAIN] Stopping...")
    finally:
        await manager.stop()


async def run_apprentice_mode(args):
    """运行学徒模式"""
    from src.bot.browser_manager import BrowserManager

    manager = BrowserManager(
        headless=args.headless,
        auto_mode=False,
        apprentice_mode=True
    )

    try:
        await manager.start()
        print("\n" + "="*50)
        print("🚀 APPRENTICE MODE: AI will observe and log your play.")
        print("="*50 + "\n")

        while True:
            await manager.run_tick()
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n[MAIN] Stopping...")
    finally:
        await manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
