#!/usr/bin/env python3
"""
德州扑克 AI - 统一入口

流程：选平台 → 配置 → 运行 → 报告
"""
import asyncio
import argparse
import sys
import os
from typing import Optional

# 确保项目根目录在 Python 路径中
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, IntPrompt
from rich.text import Text

from src.utils.logger import bot_logger

console = Console()

AVAILABLE_STRATEGIES = ["gto", "range", "exploitative", "checkorfold", "aggressive", "neural", "icm"]


def select_platform() -> str:
    """交互式选择平台"""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("1.", "Arena  (本地模拟对抗)")
    table.add_row("2.", "Browser (浏览器在线对战)")
    table.add_row("3.", "MTT    (多桌锦标赛)")
    table.add_row("4.", "SNG    (Sit & Go 单桌赛)")

    console.print(Panel(table, title="选择平台", border_style="cyan"))
    choice = Prompt.ask("请选择", choices=["1", "2", "3", "4"], default="1")
    if choice == "1":
        return "arena"
    elif choice == "3":
        return "mtt"
    elif choice == "4":
        return "sng"
    return "browser"


def configure_arena():
    """交互式配置竞技场"""
    from src.platforms.arena.platform import ArenaConfig, ArenaPlayerConfig

    console.print()
    num_players = IntPrompt.ask("玩家数量", default=3, choices=[str(i) for i in range(2, 7)])

    players: list[ArenaPlayerConfig] = []
    for i in range(num_players):
        console.print(f"\n[bold]Player {i + 1}:[/bold]")
        name = Prompt.ask("  名称", default=f"Player{i + 1}")
        strategy = Prompt.ask(
            f"  策略 ({'/'.join(AVAILABLE_STRATEGIES)})",
            choices=AVAILABLE_STRATEGIES,
            default=AVAILABLE_STRATEGIES[i % len(AVAILABLE_STRATEGIES)]
        )
        initial_stack = IntPrompt.ask("  初始筹码", default=1000)
        players.append(ArenaPlayerConfig(name=name, strategy=strategy, initial_stack=initial_stack))

    console.print()
    termination = Prompt.ask("终止条件 (rounds/last_standing/time)", choices=["rounds", "last_standing", "time"], default="rounds")

    max_rounds = 100
    max_duration_min = None
    if termination == "rounds":
        max_rounds = IntPrompt.ask("最大轮数", default=100)
    elif termination == "last_standing":
        max_rounds = IntPrompt.ask("最大轮数上限", default=500)
    elif termination == "time":
        max_duration_min = IntPrompt.ask("最大持续时间(分钟)", default=10)

    small_blind = IntPrompt.ask("小盲", default=1)
    big_blind = IntPrompt.ask("大盲", default=2)

    return ArenaConfig(
        players=players,
        small_blind=small_blind,
        big_blind=big_blind,
        termination=termination,
        max_rounds=max_rounds,
        max_duration_min=max_duration_min,
    )


def configure_browser(args) -> dict:
    """配置浏览器平台"""
    from src.platforms.browser.browser_platform import BrowserPlatformConfig, TableSelectionStrategy

    config = BrowserPlatformConfig.from_file()
    if args.stakes:
        config.preferred_stakes = args.stakes
    if args.strategy:
        strategy_map = {
            "fifo": TableSelectionStrategy.FIFO,
            "most": TableSelectionStrategy.MOST_PLAYERS,
            "least": TableSelectionStrategy.LEAST_PLAYERS,
            "random": TableSelectionStrategy.RANDOM,
        }
        config.table_selection_strategy = strategy_map[args.strategy]
    config.headless = args.headless

    return {"config": config, "mode": args.mode}


def print_report(report):
    """用 rich 输出比赛报告"""
    table = Table(title="比赛报告", show_lines=True)
    table.add_column("玩家", style="bold")
    table.add_column("策略")
    table.add_column("最终筹码", justify="right")
    table.add_column("盈亏", justify="right")
    table.add_column("VPIP%", justify="right")
    table.add_column("PFR%", justify="right")
    table.add_column("胜手数", justify="right")

    for ps in report.player_stats:
        profit_style = "green" if ps.profit > 0 else ("red" if ps.profit < 0 else "white")
        table.add_row(
            ps.name,
            ps.strategy,
            str(ps.final_stack),
            f"[{profit_style}]{ps.profit:+d}[/{profit_style}]",
            f"{ps.vpip:.1f}",
            f"{ps.pfr:.1f}",
            str(ps.hands_won),
        )

    console.print()
    console.print(Panel(
        f"总手数: {report.num_hands}  |  持续时间: {report.duration_sec:.1f}s",
        border_style="cyan"
    ))
    console.print(table)


async def run_arena(config):
    """运行竞技场模式"""
    from src.platforms.arena.platform import ArenaPlatform

    platform = ArenaPlatform(config)
    await platform.initialize()
    console.print("\n[bold green]开始比赛...[/bold green]\n")
    report = await platform.run()
    print_report(report)
    await platform.shutdown()


def configure_mtt():
    """交互式配置 MTT 锦标赛"""
    from src.platforms.arena.mtt import MTTConfig, PrizePayout

    console.print()
    entries = IntPrompt.ask("参赛人数", default=18)
    blind_type = Prompt.ask("盲注结构 (standard/turbo/deepstack)",
                            choices=["standard", "turbo", "deepstack"], default="standard")
    starting_stack = IntPrompt.ask("起始筹码", default=1000)
    entry_fee = IntPrompt.ask("买入费", default=100)

    return MTTConfig(
        entries=entries,
        entry_fee=entry_fee,
        starting_stack=starting_stack,
        blind_schedule=blind_type,
    )


def run_mtt(args=None):
    """运行 MTT 锦标赛"""
    from src.platforms.arena.mtt import MTTConfig, MTTPlayerConfig, PrizePayout, MTTManager

    if args and args.mtt_entries:
        entries = args.mtt_entries
        blind_type = args.mtt_blinds
        starting_stack = args.mtt_stack
        entry_fee = args.mtt_fee

        # 解析自定义奖金分配
        prize_payout = None
        if args.mtt_prize:
            pcts = [float(x) for x in args.mtt_prize.split(",")]
            prize_payout = PrizePayout({i + 1: pct / 100 for i, pct in enumerate(pcts)})

        config = MTTConfig(
            entries=entries,
            entry_fee=entry_fee,
            starting_stack=starting_stack,
            blind_schedule=blind_type,
            prize_structure=prize_payout,
        )
    else:
        config = configure_mtt()

    # 注册参赛者
    manager = MTTManager(config)
    strategies = ["gto", "range", "exploitative", "checkorfold", "aggressive"]
    player_configs = []
    for i in range(config.entries):
        player_configs.append(MTTPlayerConfig(
            name=f"Player{i + 1}",
            strategy="mixed",
            starting_stack=config.starting_stack,
        ))

    manager.register_players(player_configs)
    manager.initial_seating()

    console.print("\n[bold green]MTT 锦标赛开始...[/bold green]\n")
    report = manager.run()
    print_mtt_report(report)
    return report


def print_mtt_report(report):
    """用 rich 输出 MTT 锦标赛报告"""
    from src.platforms.arena.mtt import MTTReport

    table = Table(title="MTT 锦标赛报告", show_lines=True)
    table.add_column("名次", justify="right", style="bold")
    table.add_column("玩家", style="bold")
    table.add_column("策略")
    table.add_column("奖金", justify="right")
    table.add_column("淘汰手", justify="right")

    for ps in report.player_stats:
        prize_style = "green" if ps.prize_won > 0 else "white"
        busted_str = f"#{ps.busted_hand}" if ps.busted_hand > 0 else "冠军!"
        table.add_row(
            str(ps.finish_pos),
            ps.name,
            ps.strategy,
            f"[{prize_style}]{ps.prize_won}[/{prize_style}]",
            busted_str,
        )

    console.print()
    console.print(Panel(
        f"参赛: {report.entries} 人  |  奖池: {report.prize_pool}  |  "
        f"总手数: {report.total_hands}  |  耗时: {report.duration_sec:.1f}s",
        border_style="cyan"
    ))
    console.print(table)


def configure_sng():
    """交互式配置 Sit & Go"""
    from src.platforms.arena.sitngo import SNGConfig

    console.print()
    preset = Prompt.ask("SNG 类型 (hu/6max/9max/10max)",
                        choices=["hu", "6max", "9max", "10max"], default="9max")
    blind_type = Prompt.ask("盲注结构 (standard/turbo)",
                            choices=["standard", "turbo"], default="turbo")
    starting_stack = IntPrompt.ask("起始筹码", default=1500)
    entry_fee = IntPrompt.ask("买入费", default=50)

    return SNGConfig(
        preset=preset,
        entry_fee=entry_fee,
        starting_stack=starting_stack,
        blind_schedule=blind_type,
    )


def run_sng(args=None):
    """运行 Sit & Go 单桌赛"""
    from src.platforms.arena.sitngo import SNGConfig, SitAndGo
    from src.platforms.arena.mtt import MTTPlayerConfig

    if args and hasattr(args, 'sng_preset') and args.sng_preset:
        config = SNGConfig(
            preset=args.sng_preset,
            entry_fee=args.sng_fee,
            starting_stack=args.sng_stack,
            blind_schedule=args.sng_blinds,
        )
    else:
        config = configure_sng()

    manager = SitAndGo(config)
    strategies = ["gto", "range", "aggressive", "checkorfold", "exploitative", "icm"]
    player_configs = []
    for i in range(config.num_players):
        player_configs.append(MTTPlayerConfig(
            name=f"Player{i + 1}",
            strategy=strategies[i % len(strategies)],
            starting_stack=config.starting_stack,
        ))

    manager.register_players(player_configs)
    manager.initial_seating()

    console.print("\n[bold green]Sit & Go 开始...[/bold green]\n")
    report = manager.run()
    print_sng_report(report)
    return report


def print_sng_report(report):
    """用 rich 输出 Sit & Go 报告"""
    from src.platforms.arena.sitngo import SNG_PRESETS

    preset_name = SNG_PRESETS.get(report.preset, {}).get("name", report.preset)
    table = Table(title=f"Sit & Go ({preset_name}) 报告", show_lines=True)
    table.add_column("名次", justify="right", style="bold")
    table.add_column("玩家", style="bold")
    table.add_column("策略")
    table.add_column("奖金", justify="right")
    table.add_column("淘汰手", justify="right")

    for ps in report.player_stats:
        prize_style = "green" if ps.prize_won > 0 else "white"
        busted_str = f"#{ps.busted_hand}" if ps.busted_hand > 0 else "冠军!"
        table.add_row(
            str(ps.finish_pos),
            ps.name,
            ps.strategy,
            f"[{prize_style}]{ps.prize_won}[/{prize_style}]",
            busted_str,
        )

    console.print()
    console.print(Panel(
        f"参赛: {report.entries} 人  |  奖池: {report.prize_pool}  |  "
        f"总手数: {report.total_hands}  |  耗时: {report.duration_sec:.1f}s",
        border_style="cyan"
    ))
    console.print(table)


async def run_browser(args):
    """运行浏览器模式"""
    from src.platforms.browser.browser_platform import BrowserPlatform, BrowserPlatformConfig
    from src.platforms.browser.adapters import ReplayPokerAdapter, TableInfo, TableFilter

    config_data = configure_browser(args)
    config: BrowserPlatformConfig = config_data["config"]

    if config_data["mode"] == "cli":
        # CLI 交互模式
        from src.main_browser import BrowserTestCLI
        cli = BrowserTestCLI(config=config, headless=args.headless)
        await cli.run()
    else:
        # 自动模式
        console.print("\n[bold]=== 自动模式 ===[/bold]")
        config.auto_mode = True
        platform = BrowserPlatform(config=config)
        await platform.initialize()

        try:
            logged_in = await platform.ensure_logged_in()
            if not logged_in:
                console.print("[red]登录失败，退出[/red]")
                await platform.shutdown()
                return

            table_id = await platform.open_table()
            if not table_id:
                console.print("[red]无可用桌子，退出[/red]")
                await platform.shutdown()
                return

            await asyncio.sleep(2)
            await platform.try_sit_down(table_id)

            from src.strategies import get_strategy
            from src.core.interfaces import GameAction, ActionType

            strategy = get_strategy(config.strategy_type)

            while True:
                state = await platform.get_game_state(table_id)
                actions = await platform.get_available_actions(table_id)

                if actions.get("available"):
                    decision = strategy.decide(state, actions)
                    if decision:
                        action_type_str = decision.get("action")
                        amount = decision.get("amount", 0)
                        action_map = {
                            "fold": ActionType.FOLD,
                            "check": ActionType.CHECK,
                            "call": ActionType.CALL,
                            "raise": ActionType.RAISE,
                            "bet": ActionType.BET,
                        }
                        action = GameAction(
                            action_type=action_map.get(action_type_str, ActionType.FOLD),
                            amount=amount,
                        )
                        await platform.execute_action(action, table_id)
                        console.print(f"动作: {action_type_str} {amount}")
                        await asyncio.sleep(3)
                else:
                    await asyncio.sleep(1)
        finally:
            await platform.shutdown()


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="德州扑克 AI")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["cli", "auto", "arena", "mtt", "sng"],
        default=None,
        help="运行模式: cli/auto/arena/mtt/sng"
    )
    parser.add_argument("--headless", action="store_true", help="浏览器无头模式")
    parser.add_argument("--stakes", help="偏好盲注级别 (如 1/2, 5/10)")
    parser.add_argument("--strategy", choices=["fifo", "most", "least", "random"], help="桌子选择策略")
    parser.add_argument("--arena-hands", type=int, default=100, help="Arena 模式手数")
    parser.add_argument("--arena-players", type=int, default=3, help="Arena 模式玩家数")
    # MTT 参数
    parser.add_argument("--mtt-entries", type=int, default=18, help="MTT 参赛人数")
    parser.add_argument("--mtt-blinds", choices=["standard", "turbo", "deepstack"], default="standard", help="MTT 盲注结构")
    parser.add_argument("--mtt-prize", type=str, default=None, help="MTT 奖金分配 (如 '50,30,20')")
    parser.add_argument("--mtt-stack", type=int, default=1000, help="MTT 起始筹码")
    parser.add_argument("--mtt-fee", type=int, default=100, help="MTT 买入费")
    # SNG 参数
    parser.add_argument("--sng-preset", choices=["hu", "6max", "9max", "10max"], default=None, help="SNG 类型")
    parser.add_argument("--sng-blinds", choices=["standard", "turbo"], default="turbo", help="SNG 盲注结构")
    parser.add_argument("--sng-stack", type=int, default=1500, help="SNG 起始筹码")
    parser.add_argument("--sng-fee", type=int, default=50, help="SNG 买入费")
    return parser.parse_args()


async def main():
    args = parse_args()

    # MTT 模式（同步运行，不需要 async）
    if args.mode == "mtt":
        run_mtt(args)
        return

    # SNG 模式
    if args.mode == "sng":
        run_sng(args)
        return

    # 如果直接指定了 arena 模式，跳过交互选择
    if args.mode == "arena":
        from src.platforms.arena.platform import ArenaConfig, ArenaPlayerConfig

        players = []
        strategies = ["gto", "range", "exploitative"]
        for i in range(min(args.arena_players, 6)):
            players.append(ArenaPlayerConfig(
                name=f"Player{i + 1}",
                strategy=strategies[i % len(strategies)],
                initial_stack=1000,
            ))
        config = ArenaConfig(players=players, max_rounds=args.arena_hands)
        await run_arena(config)
        return

    # 如果直接指定了 cli/auto 模式，直接进入浏览器模式
    if args.mode in ("cli", "auto"):
        await run_browser(args)
        return

    # 无参数：交互式选择平台
    platform_type = select_platform()

    if platform_type == "arena":
        config = configure_arena()
        await run_arena(config)
    elif platform_type == "mtt":
        run_mtt()
    elif platform_type == "sng":
        run_sng()
    elif platform_type == "browser":
        await run_browser(args)


if __name__ == "__main__":
    asyncio.run(main())
