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
    table.add_row("1.", "Arena       (本地模拟对抗)")
    table.add_row("2.", "MTT         (多桌锦标赛)")
    table.add_row("3.", "SNG         (Sit & Go 单桌赛)")
    table.add_row("4.", "Ring        (无限注现金桌)")
    table.add_row("5.", "ReplayPoker (浏览器在线对战)")

    console.print(Panel(table, title="选择平台", border_style="cyan"))
    choice = Prompt.ask("请选择", choices=["1", "2", "3", "4", "5"], default="1")
    if choice == "1":
        return "arena"
    elif choice == "2":
        return "mtt"
    elif choice == "3":
        return "sng"
    elif choice == "4":
        return "ring"
    return "replaypoker"


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
        # 区分桌子选择策略和扑克策略
        table_strategy_map = {
            "fifo": TableSelectionStrategy.FIFO,
            "most": TableSelectionStrategy.MOST_PLAYERS,
            "least": TableSelectionStrategy.LEAST_PLAYERS,
            "random": TableSelectionStrategy.RANDOM,
        }
        if args.strategy in table_strategy_map:
            config.table_selection_strategy = table_strategy_map[args.strategy]
        else:
            # 扑克策略（如 gto, checkorfold, range 等）
            config.strategy_type = args.strategy
    config.headless = args.headless

    return {"config": config, "cli_mode": getattr(args, 'cli', False)}


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


async def run_mtt(args=None):
    """运行 MTT 锦标赛"""
    from src.platforms.arena.mtt import MTTConfig, MTTPlayerConfig, PrizePayout, MTTManager

    has_human = getattr(args, 'human', False) if args else False

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
        is_human = has_human and i == 0
        player_configs.append(MTTPlayerConfig(
            name="You" if is_human else f"Player{i + 1}",
            strategy="mixed",
            starting_stack=config.starting_stack,
            is_human=is_human,
        ))

    manager.register_players(player_configs)
    manager.initial_seating()

    # 人类玩家替换
    if has_human:
        from src.platforms.arena.tournament_cli import CLITournamentPlayer
        for pid, agent in manager.player_agents.items():
            pc = None
            for i, cfg in enumerate(manager.player_configs):
                if f"mtt_p{i}" == pid:
                    pc = cfg
                    break
            if pc and pc.is_human:
                CLITournamentPlayer.create(agent)
                console.print(f"[bold cyan]{agent.name} 已切换为 CLI 人类玩家[/bold cyan]")

    console.print("\n[bold green]MTT 锦标赛开始...[/bold green]\n")
    report = await manager.run()
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


def configure_ring():
    """交互式配置 Ring Game"""
    from src.platforms.arena.ring import RingConfig, RingPlayerConfig

    console.print()
    num_players = IntPrompt.ask("玩家数量", default=4, choices=[str(i) for i in range(2, 10)])

    players: list[RingPlayerConfig] = []
    for i in range(num_players):
        console.print(f"\n[bold]Player {i + 1}:[/bold]")
        name = Prompt.ask("  名称", default=f"Player{i + 1}")
        hand_strategy = Prompt.ask(
            f"  手牌策略 ({'/'.join(AVAILABLE_STRATEGIES)})",
            choices=AVAILABLE_STRATEGIES,
            default=AVAILABLE_STRATEGIES[i % len(AVAILABLE_STRATEGIES)]
        )
        table_strategy = Prompt.ask(
            "  桌位策略 (default/conservative/aggressive)",
            choices=["default", "conservative", "aggressive"],
            default="default",
        )
        initial_bank = IntPrompt.ask("  初始银行", default=2000)
        buyin_amount = IntPrompt.ask("  买入金额", default=200)
        players.append(RingPlayerConfig(
            name=name,
            hand_strategy=hand_strategy,
            table_strategy=table_strategy,
            initial_bank=initial_bank,
            buyin_amount=buyin_amount,
        ))

    small_blind = IntPrompt.ask("小盲", default=1)
    big_blind = IntPrompt.ask("大盲", default=2)
    max_rounds = IntPrompt.ask("最大手数", default=200)

    return RingConfig(
        players=players,
        small_blind=small_blind,
        big_blind=big_blind,
        max_rounds=max_rounds,
    )


async def run_ring(config, has_human=False):
    """运行 Ring Game"""
    from src.platforms.arena.ring import RingPlatform, RingPlayer
    from src.core.messaging import AsyncChannel, Message, MessageType

    platform = RingPlatform(config)
    await platform.initialize()

    # 如果有人类玩家，将对应 RingPlayer 的决策钩子替换为 CLI 输入
    if has_human:
        from src.platforms.arena.ring_cli import CLIRingPlayer
        for i, pc in enumerate(config.players):
            if pc.is_human:
                player_id = f"ring_player_{i}"
                player = platform.players[player_id]
                CLIRingPlayer.create(player)
                console.print(f"[bold cyan]{player.name} 已切换为 CLI 人类玩家[/bold cyan]")

    console.print("\n[bold green]Ring Game 开始...[/bold green]\n")
    report = await platform.run()
    print_ring_report(report)
    await platform.shutdown()


def print_ring_report(report):
    """用 rich 输出 Ring Game 报告"""
    from src.platforms.arena.ring import RingReport

    table = Table(title="Ring Game 报告", show_lines=True)
    table.add_column("玩家", style="bold")
    table.add_column("手牌策略")
    table.add_column("桌位策略")
    table.add_column("桌上筹码", justify="right")
    table.add_column("银行", justify="right")
    table.add_column("总盈亏", justify="right")
    table.add_column("VPIP%", justify="right")
    table.add_column("PFR%", justify="right")
    table.add_column("胜手", justify="right")

    for ps in report.player_stats:
        profit_style = "green" if ps.total_profit > 0 else ("red" if ps.total_profit < 0 else "white")
        table.add_row(
            ps.name,
            ps.strategy,
            ps.table_strategy_name,
            str(ps.final_chips),
            str(ps.final_bank),
            f"[{profit_style}]{ps.total_profit:+d}[/{profit_style}]",
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


async def run_sng(args=None):
    """运行 Sit & Go 单桌赛"""
    from src.platforms.arena.sitngo import SNGConfig, SitAndGo
    from src.platforms.arena.mtt import MTTPlayerConfig

    has_human = getattr(args, 'human', False) if args else False

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
        is_human = has_human and i == 0
        player_configs.append(MTTPlayerConfig(
            name="You" if is_human else f"Player{i + 1}",
            strategy=strategies[i % len(strategies)],
            starting_stack=config.starting_stack,
            is_human=is_human,
        ))

    manager.register_players(player_configs)
    manager.initial_seating()

    # 人类玩家替换
    if has_human:
        from src.platforms.arena.tournament_cli import CLITournamentPlayer
        for pid, agent in manager.player_agents.items():
            pc = None
            for i, cfg in enumerate(manager.player_configs):
                if f"sng_p{i}" == pid:
                    pc = cfg
                    break
            if pc and pc.is_human:
                CLITournamentPlayer.create(agent)
                console.print(f"[bold cyan]{agent.name} 已切换为 CLI 人类玩家[/bold cyan]")

    console.print("\n[bold green]Sit & Go 开始...[/bold green]\n")
    report = await manager.run()
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


async def _browser_cli_decide(state, actions: dict) -> dict:
    """浏览器模式人类玩家决策：显示状态，等待终端输入

    委托给统一 CLI 模块（src.utils.cli_player），与其他模式 UI 一致。
    默认值由 GTO 策略生成，按 Enter 即采纳。
    """
    from src.utils.cli_player import (
        ActionChoice,
        build_default,
        prompt_hand_action,
    )

    # 将 PokerGameState + actions dict 转为统一 payload schema
    payload = _browser_state_to_payload(state, actions)
    to_call = int(actions.get("to_call", 0) or 0)

    # GTO 策略默认（gto 是 balanced 的别名）
    default = build_default(payload, strategy_name="gto")

    # 决策上下文，用于日志
    ctx = (
        f"hand={' '.join(getattr(state, 'hole_cards', []) or [])} "
        f"pot={getattr(state, 'pot', 0)} to_call={to_call}"
    )

    choice: ActionChoice = await prompt_hand_action(
        payload,
        default=default,
        prompt_prefix="browser",
        context=ctx,
    )

    # 浏览器模式独有的 pot_rake/rake 附加显示
    pot_rake = getattr(state, "pot_rake", 0) if state else 0
    rake = getattr(state, "rake", 0) if state else 0
    if pot_rake or rake:
        extras = []
        if pot_rake:
            extras.append(f"税后 [bold]{pot_rake}[/bold]")
        if rake:
            extras.append(f"抽税 [dim]{rake}[/dim]")
        console.print("  ".join(extras))

    # 转换回浏览器模式 {action, amount} 格式
    action = choice.action
    if action == "allin":
        action = "raise"
        amount = int(actions.get("max_raise", 999999) or 999999)
    else:
        amount = choice.amount
    bot_logger.info(
        f"浏览器 CLI 决策: {action} {amount} (来源={choice.source}) | {ctx}"
    )
    return {"action": action, "amount": amount}


def _browser_state_to_payload(state, actions: dict) -> dict:
    """将浏览器 (PokerGameState, actions) 转为统一 schema 的 payload"""
    pot = getattr(state, "pot", 0) if state else 0
    to_call = int(actions.get("to_call", 0) or 0)
    min_raise = int(actions.get("min_raise", 0) or (getattr(state, "min_raise", 0) if state else 0) or 0)
    max_raise = int(actions.get("max_raise", 0) or 0)
    hole = list(getattr(state, "hole_cards", []) or []) if state else []
    board = list(getattr(state, "community_cards", []) or []) if state else []
    my_seat = getattr(state, "my_seat_id", None) if state else None
    players = getattr(state, "players", {}) if state else {}

    # 当前阶段：浏览器用 prefs 标识，简化为 preflop/flop/turn/river
    board_n = len(board)
    if board_n == 0:
        stage = "preflop"
    elif board_n == 3:
        stage = "flop"
    elif board_n == 4:
        stage = "turn"
    else:
        stage = "river"

    available = list(actions.get("available", []) or [])
    # 浏览器侧 "bet" 跟 "raise" 在显示层等价，统一为 raise
    norm_available = []
    for a in available:
        if a == "bet":
            norm_available.append("RAISE")
        else:
            norm_available.append(a.upper())

    players_data = {}
    for sid, p in players.items():
        players_data[str(sid)] = {
            "user_id": str(sid),
            "name": getattr(p, "name", "") or f"Seat{sid}",
            "chips": getattr(p, "chips", 0),
            "is_active": getattr(p, "status", "active") not in ("folded", "sit_out"),
            "status": getattr(p, "status", "active"),
            "bet": getattr(p, "bet", 0),
            "is_acting": getattr(p, "is_acting", False),
        }

    return {
        "my_seat_id": my_seat,
        "hole_cards": hole,
        "community_cards": board,
        "pot": pot,
        "to_call": to_call,
        "min_raise": min_raise,
        "max_raise": max_raise,
        "available_actions": norm_available,
        "current_stage": stage,
        "players": players_data,
    }


def _render_browser_state(state, actions: dict, available: list):
    """渲染与 CLI 模式对齐的桌桌状态：底池、公共牌、座位、玩家列表"""
    pot = getattr(state, "pot", 0) if state else 0
    pot_rake = getattr(state, "pot_rake", 0) if state else 0
    rake = getattr(state, "rake", 0) if state else 0
    community_cards = getattr(state, "community_cards", []) if state else []
    my_seat_id = getattr(state, "my_seat_id", None) if state else None
    hole_cards = getattr(state, "hole_cards", []) if state else []
    min_raise = getattr(state, "min_raise", 0) if state else 0
    to_call = actions.get("to_call", 0)
    players = getattr(state, "players", {}) if state else {}

    # 底池行（含抽税）
    pot_parts = [f"底池 [bold yellow]{pot}[/bold yellow]"]
    if pot_rake > 0:
        pot_parts.append(f"税后 [bold]{pot_rake}[/bold]")
    if rake > 0:
        pot_parts.append(f"抽税 [dim]{rake}[/dim]")

    # 公共牌
    board_line = ""
    if community_cards:
        board_line = f"\n公共牌: [bold cyan]{' '.join(community_cards)}[/bold cyan]"

    # 手牌
    hole_line = ""
    if hole_cards:
        hole_line = f"\n手牌:   [bold magenta]{' '.join(hole_cards)}[/bold magenta]"

    # 关键信息行
    key_line = (
        f"  |  需跟注 [bold]{to_call}[/bold]"
        f"  |  最小加注 [bold]{min_raise}[/bold]"
        f"  |  我的座位 [bold]{my_seat_id}[/bold]"
    )

    console.print(Panel(
        "  ".join(pot_parts) + key_line + hole_line + board_line,
        title="[bold]你的回合 (浏览器)[/bold]",
        border_style="green",
    ))

    # 玩家列表
    if players:
        console.print("[bold]玩家:[/bold]")
        status_marker = {
            "active": "[green]●[/green]",
            "folded": "[dim]✕ 弃牌[/dim]",
            "all_in": "[red]▲ 全押[/red]",
            "sit_out": "[yellow]○ 暂离[/yellow]",
        }
        for seat_id in sorted(players.keys()):
            p = players[seat_id]
            marker = status_marker.get(p.status, f"[{p.status}]")
            acting = " [bold cyan]<- 行动中[/bold cyan]" if getattr(p, "is_acting", False) else ""
            me = " [bold magenta](我)[/bold magenta]" if seat_id == my_seat_id else ""
            name = getattr(p, "name", "") or f"Seat{seat_id}"
            chips = getattr(p, "chips", 0)
            console.print(
                f"  [dim]{seat_id:>2}[/dim]  {marker}  [bold]{name}[/bold]{me}  "
                f"筹码 [yellow]{chips}[/yellow]{acting}"
            )


async def run_replaypoker(args):
    """运行 ReplayPoker 浏览器模式"""
    from src.platforms.browser.browser_platform import BrowserPlatform, BrowserPlatformConfig

    config_data = configure_browser(args)
    config: BrowserPlatformConfig = config_data["config"]
    cli_mode = config_data["cli_mode"]
    has_human = getattr(args, 'human', False)

    # 解析 --buyin 参数（min/max/default/整数），人类和自动模式共用，默认 min
    raw_buyin = getattr(args, "buyin", "min")
    if isinstance(raw_buyin, str):
        buyin_amount: Optional[object] = raw_buyin.lower()
        if buyin_amount not in ("min", "max", "default"):
            try:
                buyin_amount = int(raw_buyin)
            except ValueError:
                console.print(f"[yellow]无效的 --buyin '{raw_buyin}'，回退到 min[/yellow]")
                buyin_amount = "min"
    else:
        buyin_amount = raw_buyin
    bot_logger.info(f"买入策略: {buyin_amount}")

    if cli_mode:
        # 完全手动浏览器控制
        from src.main_browser import BrowserTestCLI
        cli = BrowserTestCLI(config=config, headless=args.headless)
        await cli.run()
    else:
        # 自动模式：使用 BrowserAutoPlayer 编排
        mode_label = "人类" if has_human else "自动"
        console.print(f"\n[bold]=== ReplayPoker {mode_label}模式 ===[/bold]")
        config.auto_mode = True
        platform = BrowserPlatform(config=config)

        if has_human:
            # 人类模式：仍使用旧循环但加上新能力
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
                await platform._check_and_sit_in(table_id, buyin_amount)

                from src.core.interfaces import GameAction, ActionType

                while True:
                    # 弹窗处理 + WS 健康 + 入座检查
                    await platform._dismiss_overlays(table_id)
                    await platform._ensure_ws_alive(table_id)
                    await platform._check_and_sit_in(table_id, buyin_amount)

                    state = await platform.get_game_state(table_id)
                    actions = await platform.get_available_actions(table_id)

                    if actions.get("available"):
                        decision = await _browser_cli_decide(state, actions)
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
        else:
            # 全自动模式：BrowserAutoPlayer
            from src.platforms.browser.auto_player import BrowserAutoPlayer

            auto_player = BrowserAutoPlayer(
                platform=platform,
                strategy_type=config.strategy_type,
                buyin_amount=buyin_amount,
            )
            await auto_player.run()


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="德州扑克 AI")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["arena", "mtt", "sng", "ring", "replaypoker", "auto", "cli"],
        default=None,
        help="运行模式: arena/mtt/sng/ring/replaypoker/auto/cli"
    )
    parser.add_argument("--headless", action="store_true", help="浏览器无头模式")
    parser.add_argument("--stakes", help="偏好盲注级别 (如 1/2, 5/10)")
    parser.add_argument("--strategy", help="策略类型 (扑克策略: gto/range/exploitative/checkorfold/aggressive/neural, 或桌子选择: fifo/most/least/random)")
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
    # Ring 参数
    parser.add_argument("--ring-hands", type=int, default=100, help="Ring Game 手数")
    parser.add_argument("--ring-buyin", type=int, default=200, help="Ring Game 买入金额")
    # 通用参数
    parser.add_argument("--human", action="store_true", help="启用人类玩家（CLI 交互）")
    parser.add_argument("--cli", action="store_true", help="ReplayPoker 完全手动浏览器控制")
    parser.add_argument("--hands", type=int, default=0, help="ReplayPoker 限定手数（0=无限）")
    parser.add_argument("--buyin", default="min",
                        help="ReplayPoker 买入量：min/max/default 或具体整数（默认 min）")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="WARNING", help="控制台日志级别 (默认: WARNING)")
    return parser.parse_args()


async def main():
    args = parse_args()

    # 设置日志级别
    from src.utils.logger import set_log_level
    set_log_level(args.log_level)

    # MTT 模式
    if args.mode == "mtt":
        await run_mtt(args)
        return

    # SNG 模式
    if args.mode == "sng":
        await run_sng(args)
        return

    # Ring 模式
    if args.mode == "ring":
        from src.platforms.arena.ring import RingConfig, RingPlayerConfig

        strategies = ["gto", "range", "exploitative", "aggressive", "checkorfold"]
        players = []
        num_players = 4
        for i in range(num_players):
            is_human = args.human and i == 0
            players.append(RingPlayerConfig(
                name="You" if is_human else f"Player{i + 1}",
                hand_strategy="gto" if is_human else strategies[i % len(strategies)],
                table_strategy="default",
                initial_bank=2000,
                buyin_amount=args.ring_buyin,
                is_human=is_human,
            ))
        config = RingConfig(players=players, max_rounds=args.ring_hands)
        await run_ring(config, has_human=args.human)
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

    # ReplayPoker 浏览器模式
    if args.mode == "replaypoker":
        await run_replaypoker(args)
        return

    # auto 模式 = ReplayPoker 自动模式
    if args.mode == "auto":
        args.mode = "replaypoker"
        await run_replaypoker(args)
        return

    # cli 模式 = ReplayPoker 手动浏览器控制
    if args.mode == "cli":
        args.mode = "replaypoker"
        args.cli = True
        await run_replaypoker(args)
        return

    # 无参数：交互式选择平台
    platform_type = select_platform()

    if platform_type == "arena":
        config = configure_arena()
        await run_arena(config)
    elif platform_type == "mtt":
        await run_mtt()
    elif platform_type == "sng":
        await run_sng()
    elif platform_type == "ring":
        config = configure_ring()
        await run_ring(config)
    elif platform_type == "replaypoker":
        await run_replaypoker(args)


if __name__ == "__main__":
    asyncio.run(main())
