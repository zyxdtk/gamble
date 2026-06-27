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
    num_players = IntPrompt.ask("玩家数量", default=3, choices=[str(i) for i in range(2, 10)])

    # 筹码档位选择
    bb = 10
    stack_choice = Prompt.ask(
        "筹码档位",
        choices=["short", "medium", "deep", "custom"],
        default="medium",
    )
    stack_presets = {"short": 50, "medium": 100, "deep": 200}
    if stack_choice == "custom":
        bb_count = IntPrompt.ask("每玩家BB数", default=100)
        default_stack = bb_count * bb
    else:
        default_stack = stack_presets[stack_choice] * bb

    players: list[ArenaPlayerConfig] = []
    # 动态获取可用策略列表（含版本化名称）
    from src.strategies.strategy_manager import StrategyManager
    sm = StrategyManager()
    available = sm.list_available_strategies()
    strategy_display = '/'.join(available) if available else '/'.join(AVAILABLE_STRATEGIES)
    strategy_choices = available if available else AVAILABLE_STRATEGIES

    for i in range(num_players):
        console.print(f"\n[bold]Player {i + 1}:[/bold]")
        name = Prompt.ask("  名称", default=f"Player{i + 1}")
        strategy = Prompt.ask(
            f"  策略 ({strategy_display})",
            choices=strategy_choices,
            default=strategy_choices[i % len(strategy_choices)]
        )
        initial_stack = IntPrompt.ask("  初始筹码", default=default_stack)
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

    small_blind = IntPrompt.ask("小盲", default=5)
    big_blind = IntPrompt.ask("大盲", default=10)

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
    from src.utils.cli_player import PilotMode

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

    return {"config": config, "pilot_mode": getattr(args, 'pilot_mode', PilotMode.AUTO)}


def print_report(report):
    """用 rich 输出比赛报告"""
    table = Table(title="比赛报告", show_lines=True)
    table.add_column("玩家", style="bold")
    table.add_column("策略")
    table.add_column("最终筹码", justify="right")
    table.add_column("盈亏", justify="right")
    table.add_column("BB/100", justify="right")
    table.add_column("AF", justify="right")
    table.add_column("3B%", justify="right")
    table.add_column("VPIP%", justify="right")
    table.add_column("PFR%", justify="right")
    table.add_column("WTSD%", justify="right")
    table.add_column("W$SD%", justify="right")
    table.add_column("胜手数", justify="right")

    for ps in report.player_stats:
        profit_style = "green" if ps.profit > 0 else ("red" if ps.profit < 0 else "white")
        table.add_row(
            ps.name,
            ps.strategy,
            str(ps.final_stack),
            f"[{profit_style}]{ps.profit:+d}[/{profit_style}]",
            f"{ps.bb_per_100:+.1f}",
            f"{ps.af:.1f}",
            f"{ps.three_bet_pct:.1f}",
            f"{ps.vpip:.1f}",
            f"{ps.pfr:.1f}",
            f"{ps.wtsd:.1f}",
            f"{ps.wsdp:.1f}",
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


# ─── 调度注册表 ───

from src.core.dispatch import SessionConfig, register_runner, get_runner


@register_runner("arena", "competition")
async def run_arena_competition(session: SessionConfig):
    """Arena 对抗赛 runner"""
    from src.platforms.arena.platform import ArenaConfig, ArenaPlayerConfig

    gk = session.game_kwargs
    players = []
    strategies = list(AVAILABLE_STRATEGIES)
    arena_players = gk.get("arena_players", len(strategies))

    # 解析筹码配置
    stack_config = gk.get("arena_stack")
    bb = 10  # 默认大盲
    stack_presets = {"short": 50, "medium": 100, "deep": 200}

    for i in range(min(arena_players, 9)):
        # 计算每玩家初始筹码
        if stack_config:
            parts = [s.strip() for s in stack_config.split(",")]
            part = parts[i % len(parts)]
            bb_count = stack_presets.get(part.lower())
            if bb_count is None:
                bb_count = int(part)
            initial_stack = bb_count * bb
        else:
            initial_stack = 1000  # 默认 100BB

        players.append(ArenaPlayerConfig(
            name=f"Player{i + 1}",
            strategy=strategies[i % len(strategies)],
            initial_stack=initial_stack,
        ))
    config = ArenaConfig(players=players, max_rounds=gk.get("hands", 100))
    await run_arena(config)


@register_runner("arena", "mtt")
async def run_arena_mtt(session: SessionConfig):
    """Arena MTT runner"""
    # 复用现有 run_mtt，构建兼容的 args 对象
    from types import SimpleNamespace
    args = SimpleNamespace(
        pilot_mode=session.pilot,
        mtt_entries=session.game_kwargs.get("mtt_entries", 18),
        mtt_blinds=session.game_kwargs.get("mtt_blinds", "standard"),
        mtt_stack=session.game_kwargs.get("mtt_stack", 1000),
        mtt_fee=session.game_kwargs.get("mtt_fee", 100),
        mtt_prize=session.game_kwargs.get("mtt_prize", None),
    )
    await run_mtt(args)


@register_runner("arena", "sng")
async def run_arena_sng(session: SessionConfig):
    """Arena SNG runner"""
    from types import SimpleNamespace
    args = SimpleNamespace(
        pilot_mode=session.pilot,
        sng_preset=session.game_kwargs.get("sng_preset", None),
        sng_fee=session.game_kwargs.get("sng_fee", 50),
        sng_stack=session.game_kwargs.get("sng_stack", 1500),
        sng_blinds=session.game_kwargs.get("sng_blinds", "turbo"),
    )
    await run_sng(args)


@register_runner("arena", "ring")
async def run_arena_ring(session: SessionConfig):
    """Arena Ring runner"""
    from src.platforms.arena.ring import RingConfig, RingPlayerConfig

    strategies = ["gto", "range", "exploitative", "aggressive", "checkorfold"]
    players = []
    num_players = 4
    has_human = session.pilot == PilotMode.ASSIST
    gk = session.game_kwargs
    for i in range(num_players):
        is_human = has_human and i == 0
        players.append(RingPlayerConfig(
            name="You" if is_human else f"Player{i + 1}",
            hand_strategy="gto" if is_human else strategies[i % len(strategies)],
            table_strategy="default",
            initial_bank=2000,
            buyin_amount=gk.get("ring_buyin", 200),
            is_human=is_human,
            pilot_mode=session.pilot if is_human else PilotMode.AUTO,
        ))
    config = RingConfig(players=players, max_rounds=gk.get("hands", 100))
    await run_ring(config, has_human=has_human)


@register_runner("browser", "ring")
async def run_browser_ring(session: SessionConfig):
    """Browser Ring (ReplayPoker) runner"""
    from types import SimpleNamespace
    args = SimpleNamespace(
        pilot_mode=session.pilot,
        mode="replaypoker",
        strategy=session.strategy or None,
        headless=session.platform_kwargs.get("headless", False),
        stakes=session.platform_kwargs.get("stakes", None),
        buyin=session.game_kwargs.get("buyin", "min"),
        hands=session.game_kwargs.get("hands", 0),
    )
    await run_replaypoker(args)


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
    from src.utils.cli_player import PilotMode

    pilot_mode = getattr(args, 'pilot_mode', PilotMode.AUTO) if args else PilotMode.AUTO
    has_human = pilot_mode == PilotMode.ASSIST

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
            pilot_mode=pilot_mode if is_human else PilotMode.AUTO,
        ))

    manager.register_players(player_configs)
    manager.initial_seating()

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

    small_blind = IntPrompt.ask("小盲", default=5)
    big_blind = IntPrompt.ask("大盲", default=10)
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

    platform = RingPlatform(config)
    await platform.initialize()

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
    from src.utils.cli_player import PilotMode

    pilot_mode = getattr(args, 'pilot_mode', PilotMode.AUTO) if args else PilotMode.AUTO
    has_human = pilot_mode == PilotMode.ASSIST

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
            pilot_mode=pilot_mode if is_human else PilotMode.AUTO,
        ))

    manager.register_players(player_configs)
    manager.initial_seating()

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
    from src.core.payload import browser_state_to_payload

    # 将 PokerGameState + actions dict 转为统一 payload schema
    payload = browser_state_to_payload(state, actions)
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


async def run_replaypoker(args):
    """运行 ReplayPoker 浏览器模式"""
    from src.platforms.browser.browser_platform import BrowserPlatform, BrowserPlatformConfig
    from src.utils.cli_player import PilotMode

    config_data = configure_browser(args)
    config: BrowserPlatformConfig = config_data["config"]
    pilot_mode: PilotMode = config_data["pilot_mode"]

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

    # 统一使用 BrowserAutoPlayer，通过 pilot_mode 区分行为
    _PILOT_LABELS = {
        PilotMode.AUTO: "无人",
        PilotMode.MANAGED: "托管",
        PilotMode.ASSIST: "辅助",
    }
    mode_label = _PILOT_LABELS.get(pilot_mode, "自动")
    console.print(f"\n[bold]=== ReplayPoker {mode_label}模式 ===[/bold]")
    config.auto_mode = True
    platform = BrowserPlatform(config=config)

    from src.platforms.browser.auto_player import BrowserAutoPlayer

    auto_player = BrowserAutoPlayer(
        platform=platform,
        strategy_type=config.strategy_type,
        buyin_amount=buyin_amount,
        pilot_mode=pilot_mode,
    )
    await auto_player.run()


def _resolve_session(args) -> tuple:
    """将 --mode / --platform / --game 统一解析为 (platform, game, pilot) 三元组

    优先级：--platform + --game > --mode
    使用 --mode 时打印黄色废弃提示
    """
    from src.utils.cli_player import PilotMode

    pilot = args.pilot_mode

    # 新参数优先
    if getattr(args, 'platform', None) and getattr(args, 'game', None):
        return args.platform, args.game, pilot

    # 旧 --mode 映射
    mode = getattr(args, 'mode', None)
    if mode:
        console.print(
            "[yellow]提示: --mode 参数已废弃，请使用 --platform <arena|browser> --game <ring|mtt|sng|competition>[/yellow]"
        )
        _MODE_MAP = {
            "arena":       ("arena", "competition", pilot),
            "mtt":         ("arena", "mtt", pilot),
            "sng":         ("arena", "sng", pilot),
            "ring":        ("arena", "ring", pilot),
            "replaypoker": ("browser", "ring", pilot),
            "auto":        ("browser", "ring", PilotMode.AUTO),
            "cli":         ("browser", "ring", PilotMode.ASSIST),
        }
        if mode in _MODE_MAP:
            return _MODE_MAP[mode]

    # 无参数：交互式
    return None


def parse_args():
    """解析命令行参数"""
    from src.utils.cli_player import PilotMode

    parser = argparse.ArgumentParser(description="德州扑克 AI")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["arena", "mtt", "sng", "ring", "replaypoker", "auto", "cli"],
        default=None,
        help="运行模式 (已废弃，请使用 --platform + --game)"
    )
    parser.add_argument("--platform", choices=["arena", "browser"], default=None,
                        help="平台选择: arena(本地模拟) | browser(浏览器在线)")
    parser.add_argument("--game", choices=["ring", "mtt", "sng", "competition"], default=None,
                        help="游戏类型: ring(现金桌) | mtt(多桌赛) | sng(单桌赛) | competition(对抗赛)")
    parser.add_argument("--headless", action="store_true", help="浏览器无头模式")
    parser.add_argument("--stakes", help="偏好盲注级别 (如 1/2, 5/10)")
    parser.add_argument("--strategy", help="策略类型 (扑克策略: gto/range/exploitative/checkorfold/aggressive/neural, 或桌子选择: fifo/most/least/random)")
    parser.add_argument("--hands", type=int, default=100, help="游戏手数（所有模式通用）")
    parser.add_argument("--arena-players", type=int, default=7, help="Arena 模式玩家数")
    parser.add_argument("--arena-stack", type=str, default=None,
                        help="筹码配置: short(50BB)/medium(100BB)/deep(200BB) 或逗号分隔每玩家BB数 (如 short,deep,medium)")
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
    parser.add_argument("--ring-buyin", type=int, default=200, help="Ring Game 买入金额")
    # 参与度控制
    parser.add_argument(
        "--pilot",
        choices=["auto", "managed", "assist"],
        default="auto",
        dest="pilot",
        help="人类参与程度: auto(无人)/managed(托管)/assist(辅助) (默认: auto)"
    )
    # 兼容别名（已废弃）
    parser.add_argument("--human", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cli", action="store_true", help=argparse.SUPPRESS)
    # 其他参数
    parser.add_argument("--buyin", default="min",
                        help="ReplayPoker 买入量：min/max/default 或具体整数（默认 min）")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="WARNING", help="控制台日志级别 (默认: WARNING)")

    args = parser.parse_args()

    # 兼容别名处理：--human → --pilot assist, --cli → --pilot assist
    if getattr(args, 'human', False):
        console.print("[yellow]警告: --human 已废弃，请使用 --pilot assist[/yellow]")
        args.pilot = "assist"
    if getattr(args, 'cli', False):
        console.print("[yellow]警告: --cli 已废弃，请使用 --pilot assist[/yellow]")
        args.pilot = "assist"

    # 将字符串 pilot 值转为 PilotMode 枚举
    args.pilot_mode = PilotMode(args.pilot)

    return args


async def main():
    args = parse_args()

    # 设置日志级别
    from src.utils.logger import set_log_level
    from src.utils.cli_player import PilotMode
    set_log_level(args.log_level)

    # 解析会话三元组
    session = _resolve_session(args)

    # 无参数：交互式选择平台
    if session is None:
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
        return

    platform, game, pilot = session

    # cli 模式的废弃提示
    if args.mode == "cli":
        console.print("[yellow]提示: 'cli' 模式已废弃，请使用 '--platform browser --game ring --pilot assist'[/yellow]")

    # 尝试通过注册表调度
    runner = get_runner(platform, game)
    if runner:
        session_config = SessionConfig(
            platform=platform,
            game=game,
            pilot=pilot,
            strategy=args.strategy or "gto",
            platform_kwargs={
                "headless": args.headless,
                "stakes": args.stakes,
            },
            game_kwargs={
                "hands": args.hands,
                "arena_players": args.arena_players,
                "arena_stack": args.arena_stack,
                "mtt_entries": args.mtt_entries,
                "mtt_blinds": args.mtt_blinds,
                "mtt_stack": args.mtt_stack,
                "mtt_fee": args.mtt_fee,
                "mtt_prize": args.mtt_prize,
                "sng_preset": args.sng_preset,
                "sng_blinds": args.sng_blinds,
                "sng_stack": args.sng_stack,
                "sng_fee": args.sng_fee,
                "ring_buyin": args.ring_buyin,
                "buyin": args.buyin,
            },
        )
        await runner(session_config)
    else:
        console.print(f"[red]未知组合: platform={platform} game={game}[/red]")


if __name__ == "__main__":
    asyncio.run(main())
