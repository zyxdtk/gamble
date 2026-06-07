"""
Ring Game CLI 用户交互模块。

CLIRingPlayer 通过 create() 方法将 RingPlayer 的决策钩子替换为终端输入，
RingPlayer 的 run() 主循环、状态管理、通道通信等逻辑完全复用。

交互设计：
- 手牌决策：按回车使用推荐默认动作（check > call > fold）
- 桌位决策：按回车默认 none（继续游戏），无需手动输入
"""
import asyncio
import functools
import logging
from typing import Any, Dict, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.strategies.table_strategy import TableAction, TableActionType

console = Console()
arena_logger = logging.getLogger("arena")


class CLIRingPlayer:
    """
    CLI 用户玩家。

    通过 create() 方法将 RingPlayer 的决策钩子替换为终端输入，
    RingPlayer 的 run() 主循环、状态管理、通道通信等逻辑完全复用。
    """

    @classmethod
    def create(cls, player: "RingPlayer") -> "RingPlayer":
        """
        从现有 RingPlayer 创建 CLIRingPlayer。

        通过替换决策钩子，保持 RingPlayer 的所有状态和逻辑不变，
        RingPlatform.run() 中正常启动 player.run() 任务即可。
        """
        async def _cli_hand(payload):
            return await cls._cli_decide_hand_action(player, payload)

        async def _cli_table(payload):
            return await cls._cli_decide_table_action(player, payload)

        player._decide_hand_action = _cli_hand
        player._decide_table_action = _cli_table
        player.is_human = True
        return player

    # ─── 默认动作 ───

    @staticmethod
    def _get_default_hand_action(available: list, to_call: int) -> Tuple[str, int]:
        """推荐默认动作：check > call > fold"""
        if "CHECK" in available:
            return "CHECK", 0
        if "CALL" in available:
            return "CALL", 0
        return "FOLD", 0

    @staticmethod
    def _get_default_hand_action_label(available: list, to_call: int) -> str:
        """默认动作的显示标签"""
        action, amount = CLIRingPlayer._get_default_hand_action(available, to_call)
        if action == "CALL":
            return f"call ({to_call})"
        if action == "CHECK":
            return "check"
        return "fold"

    # ─── 手牌决策 ───

    @staticmethod
    async def _cli_decide_hand_action(player, payload: Dict[str, Any]) -> Tuple[str, int]:
        """CLI 手牌决策：显示牌面，等待用户输入"""
        available = payload.get("available_actions", [])
        to_call = payload.get("to_call", 0)
        default_label = CLIRingPlayer._get_default_hand_action_label(available, to_call)

        CLIRingPlayer._display_hand_state(payload, default_label)

        # 决策上下文，用于日志
        ctx = (
            f"stage={payload.get('current_stage', '?')} "
            f"hand={' '.join(payload.get('hole_cards', []))} "
            f"board={' '.join(payload.get('community_cards', []))} "
            f"pot={payload.get('pot', 0)} to_call={to_call}"
        )

        while True:
            try:
                loop = asyncio.get_running_loop()
                cmd_line = await loop.run_in_executor(
                    None, functools.partial(input, f"ring> [{default_label}]: ")
                )
                cmd_line = cmd_line.strip().lower()

                # 回车 = 使用默认动作
                if not cmd_line:
                    action, amount = CLIRingPlayer._get_default_hand_action(available, to_call)
                    arena_logger.info(f"🎮 CLI 手牌决策(默认): {action} {amount} | {ctx}")
                    return action, amount

                parts = cmd_line.split()
                cmd = parts[0]

                if cmd in ("help", "h", "?"):
                    CLIRingPlayer._print_hand_help(available, default_label)
                    continue

                if cmd == "fold" and "FOLD" in available:
                    arena_logger.info(f"🎮 CLI 手牌决策: FOLD | {ctx}")
                    return "FOLD", 0

                if cmd == "check" and "CHECK" in available:
                    arena_logger.info(f"🎮 CLI 手牌决策: CHECK | {ctx}")
                    return "CHECK", 0

                if cmd == "call" and "CALL" in available:
                    arena_logger.info(f"🎮 CLI 手牌决策: CALL ({to_call}) | {ctx}")
                    return "CALL", 0

                if cmd in ("allin", "all_in") and "ALL_IN" in available:
                    arena_logger.info(f"🎮 CLI 手牌决策: ALL_IN | {ctx}")
                    return "ALL_IN", 0

                if cmd == "raise" and "RAISE" in available:
                    if len(parts) > 1:
                        try:
                            amount = int(parts[1])
                            arena_logger.info(f"🎮 CLI 手牌决策: RAISE {amount} | {ctx}")
                            return "RAISE", amount
                        except ValueError:
                            console.print("[red]金额必须是整数[/red]")
                            continue
                    else:
                        console.print("[red]用法: raise <金额>[/red]")
                        continue

                if cmd == "status":
                    CLIRingPlayer._display_hand_state(payload, default_label)
                    continue

                console.print(f"[red]无效命令: {cmd}。输入 help 查看帮助[/red]")

            except (KeyboardInterrupt, EOFError):
                return "FOLD", 0

    # ─── 桌位决策 ───

    @staticmethod
    async def _cli_decide_table_action(player, payload: Dict[str, Any]) -> TableAction:
        """CLI 桌位决策：显示桌位状态，等待用户输入"""
        CLIRingPlayer._display_table_action_prompt(payload, player)

        while True:
            try:
                loop = asyncio.get_running_loop()
                cmd_line = await loop.run_in_executor(
                    None, functools.partial(input, "ring[table]> [none]: ")
                )
                cmd_line = cmd_line.strip().lower()

                # 回车 = none（继续游戏）
                if not cmd_line:
                    arena_logger.info("🎮 CLI 桌位决策(默认): NONE")
                    return TableAction(action_type=TableActionType.NONE, reasoning="CLI 默认")

                parts = cmd_line.split()
                cmd = parts[0]

                if cmd in ("help", "h", "?"):
                    CLIRingPlayer._print_table_help()
                    continue

                if cmd == "none":
                    arena_logger.info("🎮 CLI 桌位决策: NONE")
                    return TableAction(action_type=TableActionType.NONE, reasoning="CLI 用户决策")

                if cmd == "sit_in":
                    arena_logger.info("🎮 CLI 桌位决策: SIT_IN")
                    return TableAction(action_type=TableActionType.SIT_IN, reasoning="CLI 用户决策")

                if cmd == "sit_out":
                    arena_logger.info("🎮 CLI 桌位决策: SIT_OUT")
                    return TableAction(action_type=TableActionType.SIT_OUT, reasoning="CLI 用户决策")

                if cmd == "leave":
                    arena_logger.info("🎮 CLI 桌位决策: LEAVE")
                    return TableAction(action_type=TableActionType.LEAVE, reasoning="CLI 用户决策")

                if cmd == "add":
                    if len(parts) > 1:
                        try:
                            amount = int(parts[1])
                            arena_logger.info(f"🎮 CLI 桌位决策: ADD_CHIPS {amount}")
                            return TableAction(
                                action_type=TableActionType.ADD_CHIPS,
                                amount=amount,
                                reasoning="CLI 用户决策",
                            )
                        except ValueError:
                            console.print("[red]金额必须是整数[/red]")
                            continue
                    else:
                        console.print("[red]用法: add <金额>[/red]")
                        continue

                if cmd == "status":
                    console.print(
                        f"  桌上: {player.chips_on_table}  银行: {player.bank}  "
                        f"盈亏: {player.total_profit:+d}"
                    )
                    continue

                console.print(f"[red]无效命令: {cmd}。输入 help 查看帮助[/red]")

            except (KeyboardInterrupt, EOFError):
                return TableAction(action_type=TableActionType.NONE, reasoning="CLI 用户中断")

    # ─── 显示方法 ───

    @staticmethod
    def _display_hand_state(payload: Dict[str, Any], default_label: str = "") -> None:
        """Rich 格式化显示手牌状态"""
        hole_cards = payload.get("hole_cards", [])
        community_cards = payload.get("community_cards", [])
        pot = payload.get("pot", 0)
        to_call = payload.get("to_call", 0)
        min_raise = payload.get("min_raise", 0)
        max_raise = payload.get("max_raise", 0)
        current_stage = payload.get("current_stage", "preflop")
        available_actions = payload.get("available_actions", [])

        # 手牌显示
        hand_str = " ".join(hole_cards) if hole_cards else "???"
        board_str = " ".join(community_cards) if community_cards else "(空)"

        stage_cn = {
            "preflop": "翻牌前",
            "flop": "翻牌",
            "turn": "转牌",
            "river": "河牌",
        }.get(current_stage, current_stage)

        # 构建玩家表格
        players_table = Table(show_header=True, header_style="bold cyan", box=None)
        players_table.add_column("座位", style="bold")
        players_table.add_column("玩家")
        players_table.add_column("筹码", justify="right")
        players_table.add_column("状态")
        players_table.add_column("下注", justify="right")

        players_data = payload.get("players", {})
        for seat_id_str, p_data in sorted(players_data.items(), key=lambda x: int(x[0])):
            status = p_data.get("status", "active")
            status_style = {
                "active": "green",
                "folded": "red",
                "all_in": "yellow",
            }.get(status, "white")

            players_table.add_row(
                seat_id_str,
                p_data.get("name", "?"),
                str(p_data.get("chips", 0)),
                f"[{status_style}]{status}[/{status_style}]",
                str(p_data.get("bet", 0)),
            )

        console.print()
        console.print(Panel(
            f"[bold]{stage_cn}[/bold]  |  "
            f"手牌: [bold cyan]{hand_str}[/bold cyan]  |  "
            f"公共牌: [bold cyan]{board_str}[/bold cyan]  |  "
            f"底池: [bold yellow]{pot}[/bold yellow]  |  "
            f"需跟注: [bold]{to_call}[/bold]",
            title=f"[bold]你的回合 (座位 {payload.get('my_seat_id', '?')})[/bold]",
            border_style="green",
        ))
        console.print(players_table)

        # 可用动作 + 默认动作提示
        action_labels = {"ALL_IN": "allin"}
        actions_display = []
        for a in available_actions:
            label = action_labels.get(a, a.lower())
            if a == "CALL" and to_call > 0:
                actions_display.append(f"[bold cyan]call ({to_call})[/bold cyan]")
            elif a == "RAISE":
                actions_display.append(f"[bold cyan]raise <金额>[/bold cyan] ({min_raise}-{max_raise})")
            else:
                actions_display.append(f"[bold cyan]{label}[/bold cyan]")

        actions_str = " | ".join(actions_display)
        console.print(f"可用动作: {actions_str}")
        if default_label:
            console.print(f"[dim]回车 = {default_label}[/dim]")
        console.print()

    @staticmethod
    def _display_table_action_prompt(payload: Dict[str, Any], player) -> None:
        """显示桌位决策提示"""
        my_chips = payload.get("my_chips", 0)
        my_bank = payload.get("my_bank", 0)
        is_playing = payload.get("is_playing", False)
        profit = payload.get("total_profit", 0)
        bb = payload.get("current_bb", 2)

        profit_style = "green" if profit > 0 else ("red" if profit < 0 else "white")
        status = "[green]参与中[/green]" if is_playing else "[yellow]观战中[/yellow]"

        console.print(Panel(
            f"桌上筹码: [bold]{my_chips}[/bold] ({my_chips / bb:.0f} BB)  |  "
            f"银行: {my_bank}  |  "
            f"盈亏: [{profit_style}]{profit:+d}[/{profit_style}]  |  "
            f"状态: {status}",
            title="[bold]桌位状态[/bold]",
            border_style="blue",
        ))
        console.print("[dim]回车 = none (继续) | sit_out | add <金额> | leave[/dim]")

    @staticmethod
    def _print_hand_help(available_actions: list, default_label: str = "") -> None:
        """打印手牌命令帮助"""
        console.print("\n[bold]手牌命令:[/bold]")
        if "FOLD" in available_actions:
            console.print("  fold           - 弃牌")
        if "CHECK" in available_actions:
            console.print("  check          - 过牌")
        if "CALL" in available_actions:
            console.print("  call           - 跟注")
        if "RAISE" in available_actions:
            console.print("  raise <金额>   - 加注至金额")
        if "ALL_IN" in available_actions:
            console.print("  allin / all_in - 全下")
        console.print("  status         - 重新显示状态")
        console.print("  help           - 显示帮助")
        if default_label:
            console.print(f"  [dim]回车       - {default_label}[/dim]")
        console.print()

    @staticmethod
    def _print_table_help() -> None:
        """打印桌位命令帮助"""
        console.print("\n[bold]桌位命令:[/bold]")
        console.print("  none           - 无操作（默认）")
        console.print("  sit_in         - 坐入参与")
        console.print("  sit_out        - 站起观战")
        console.print("  add <金额>     - 补充筹码")
        console.print("  leave          - 离场")
        console.print("  status         - 显示状态")
        console.print("  help           - 显示帮助")
        console.print()
