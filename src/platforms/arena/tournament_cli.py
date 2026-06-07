"""
MTT/SNG CLI 用户交互模块。

CLITournamentPlayer 通过 create() 方法将 ArenaAgent 的 get_action 替换为终端输入，
与 CLIRingPlayer 思路一致但更简单（只有手牌决策，没有桌位决策）。

关键区别：
- Ring 通过 AsyncChannel 双工通信，payload 序列化
- MTT/SNG 中 ArenaAgent 直接持有 GameEngine 引用，
  agent._translate_state(engine) 已有完整的 GameState 构造逻辑，直接复用
"""
import asyncio
import functools
import logging
from typing import Any, Dict, List, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from treys import Card

from src.platforms.arena.game import ActionType as ArenaActionType, Street
from src.platforms.arena.agent import ArenaAgent

console = Console()
arena_logger = logging.getLogger("arena")


class CLITournamentPlayer:
    """
    CLI 用户玩家（锦标赛模式）。

    通过 create() 方法替换 ArenaAgent.get_action 为终端输入，
    保持 agent 的所有状态和逻辑不变。
    """

    @classmethod
    def create(cls, agent: ArenaAgent) -> ArenaAgent:
        """
        替换 agent.get_action 为 CLI 输入。

        保持 ArenaAgent 的 strategy、player_id、seat_id 等状态不变。
        """
        async def _cli_get_action(arena_state):
            return await cls._cli_decide_hand_action(agent, arena_state)

        agent.get_action = _cli_get_action
        agent.is_human = True
        return agent

    # ─── 默认动作 ───

    @staticmethod
    def _get_default_action(available: List[str], to_call: int) -> Tuple[str, int]:
        """推荐默认动作：check > call > fold"""
        if "CHECK" in available:
            return "CHECK", 0
        if "CALL" in available:
            return "CALL", 0
        return "FOLD", 0

    @staticmethod
    def _get_default_action_label(available: List[str], to_call: int) -> str:
        """默认动作的显示标签"""
        action, amount = CLITournamentPlayer._get_default_action(available, to_call)
        if action == "CALL":
            return f"call ({to_call})"
        if action == "CHECK":
            return "check"
        return "fold"

    # ─── 手牌决策 ───

    @staticmethod
    async def _cli_decide_hand_action(
        agent: ArenaAgent, engine: 'GameEngine'
    ) -> Tuple[ArenaActionType, int]:
        """CLI 手牌决策：显示牌面，等待用户输入"""
        # 用 agent._translate_state 构造 GameState，再转为显示 payload
        game_state = agent._translate_state(engine)
        payload = CLITournamentPlayer._game_state_to_payload(game_state, engine)
        available = payload.get("available_actions", [])
        to_call = payload.get("to_call", 0)
        default_label = CLITournamentPlayer._get_default_action_label(available, to_call)

        CLITournamentPlayer._display_hand_state(payload, default_label)

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
                    None, functools.partial(input, f"tourney> [{default_label}]: ")
                )
                cmd_line = cmd_line.strip().lower()

                # 回车 = 使用默认动作
                if not cmd_line:
                    action_str, _ = CLITournamentPlayer._get_default_action(available, to_call)
                    arena_logger.info(f"🎮 CLI 手牌决策(默认): {action_str} | {ctx}")
                    return CLITournamentPlayer._str_to_arena_action(action_str), 0

                parts = cmd_line.split()
                cmd = parts[0]

                if cmd in ("help", "h", "?"):
                    CLITournamentPlayer._print_help(available, default_label)
                    continue

                if cmd == "fold" and "FOLD" in available:
                    arena_logger.info(f"🎮 CLI 手牌决策: FOLD | {ctx}")
                    return ArenaActionType.FOLD, 0

                if cmd == "check" and "CHECK" in available:
                    arena_logger.info(f"🎮 CLI 手牌决策: CHECK | {ctx}")
                    return ArenaActionType.CHECK, 0

                if cmd == "call" and "CALL" in available:
                    arena_logger.info(f"🎮 CLI 手牌决策: CALL ({to_call}) | {ctx}")
                    return ArenaActionType.CALL, 0

                if cmd in ("allin", "all_in") and "ALL_IN" in available:
                    arena_logger.info(f"🎮 CLI 手牌决策: ALL_IN | {ctx}")
                    return ArenaActionType.ALL_IN, 0

                if cmd == "raise" and "RAISE" in available:
                    if len(parts) > 1:
                        try:
                            amount = int(parts[1])
                            arena_logger.info(f"🎮 CLI 手牌决策: RAISE {amount} | {ctx}")
                            return ArenaActionType.RAISE, amount
                        except ValueError:
                            console.print("[red]金额必须是整数[/red]")
                            continue
                    else:
                        console.print("[red]用法: raise <金额>[/red]")
                        continue

                if cmd == "status":
                    CLITournamentPlayer._display_hand_state(payload, default_label)
                    continue

                console.print(f"[red]无效命令: {cmd}。输入 help 查看帮助[/red]")

            except (KeyboardInterrupt, EOFError):
                return ArenaActionType.FOLD, 0

    # ─── GameState -> payload 转换 ───

    @staticmethod
    def _game_state_to_payload(game_state, engine: 'GameEngine') -> Dict[str, Any]:
        """从 GameState 对象构建显示 payload（与 CLIRingPlayer 的 payload 格式一致）"""
        # 确定可用动作
        available_actions = []
        if game_state.to_call == 0:
            available_actions = ["FOLD", "CHECK", "RAISE", "ALL_IN"]
        else:
            available_actions = ["FOLD", "CALL", "RAISE", "ALL_IN"]

        # 翻译当前阶段
        stage_map = {
            Street.PREFLOP: "preflop",
            Street.FLOP: "flop",
            Street.TURN: "turn",
            Street.RIVER: "river",
        }
        current_stage = stage_map.get(engine.current_street, "preflop")

        # 构建玩家信息
        players_data = {}
        for seat_id, sp in game_state.players.items():
            players_data[str(seat_id)] = {
                "user_id": sp.user_id,
                "name": sp.name,
                "chips": sp.chips,
                "is_active": sp.is_active,
                "status": sp.status,
                "bet": sp.bet,
                "hands_played": sp.hands_played,
                "vpip_actions": sp.vpip_actions,
                "pfr_actions": sp.pfr_actions,
            }

        return {
            "my_seat_id": game_state.my_seat_id,
            "hole_cards": game_state.hole_cards,
            "community_cards": game_state.community_cards,
            "pot": game_state.pot,
            "to_call": game_state.to_call,
            "min_raise": game_state.min_raise,
            "max_raise": game_state.max_raise,
            "available_actions": available_actions,
            "current_stage": current_stage,
            "players": players_data,
        }

    # ─── 显示方法（复用 CLIRingPlayer 的 Rich 显示格式）───

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
    def _print_help(available_actions: list, default_label: str = "") -> None:
        """打印命令帮助"""
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

    # ─── 工具方法 ───

    @staticmethod
    def _str_to_arena_action(action_str: str) -> ArenaActionType:
        """字符串转 ArenaActionType"""
        mapping = {
            "FOLD": ArenaActionType.FOLD,
            "CHECK": ArenaActionType.CHECK,
            "CALL": ArenaActionType.CALL,
            "RAISE": ArenaActionType.RAISE,
            "ALL_IN": ArenaActionType.ALL_IN,
        }
        return mapping.get(action_str.upper(), ArenaActionType.FOLD)
