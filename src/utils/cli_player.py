"""
统一 CLI 玩家交互模块（replaypoker / ring / sng / mtt 共用）。

设计目标：
- 所有模式的 `--pilot` 入口在轮到你时，UI 保持一致
- 默认值由配置的策略生成（默认 GTO/balanced），按 Enter 即采纳
- 共享 payload 渲染、命令解析、错误处理逻辑

调用方只需：
1. 准备一个 dict payload（与各模式原有 schema 兼容）
2. 调用 `display_hand_state` / `prompt_hand_action` 即可
"""
from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.strategies.game_state import GameState, Player as StrategyPlayer
from src.strategies.strategy_manager import StrategyManager

console = Console()
cli_logger = logging.getLogger("cli_player")


# ─── PilotMode 枚举 ───

class PilotMode(enum.Enum):
    """人类参与程度控制"""
    AUTO = "auto"         # 无人：AI 全自主
    MANAGED = "managed"   # 托管：AI 自主 + 人类可打断
    ASSIST = "assist"     # 辅助：AI 建议 + 人类确认


# ─── StdinMonitor 类 ───

class StdinMonitor:
    """托管/辅助模式的非阻塞 stdin 监控器"""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._paused = False          # 人类是否暂停了自动游戏
        self._takeover = False        # 人类是否接管下一手决策

    async def start(self):
        """启动后台 stdin 读取循环"""
        self._task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        """持续从 stdin 读取行，放入队列"""
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, input)
                await self._queue.put(line.strip())
            except (EOFError, KeyboardInterrupt):
                break

    async def get_command(self, timeout: float = 0.01) -> Optional[str]:
        """非阻塞获取一条命令，超时返回 None"""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def stop(self):
        """停止 stdin 监控"""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_takeover(self) -> bool:
        return self._takeover

# Action 名称归一化：兼容各模式
#   ring/sng/mtt: FOLD / CHECK / CALL / RAISE / ALL_IN
#   browser:      fold / check / call / raise / bet / allin
_ACTION_ALIASES = {
    "FOLD": "fold",
    "CHECK": "check",
    "CALL": "call",
    "RAISE": "raise",
    "BET": "bet",
    "ALL_IN": "allin",
    "ALLIN": "allin",
    "ALL-IN": "allin",
    "NONE": "none",
    "SIT_IN": "sit_in",
    "SIT_OUT": "sit_out",
    "LEAVE": "leave",
    "ADD_CHIPS": "add",
    "ADD": "add",
}


def normalize_action(action: str) -> str:
    return _ACTION_ALIASES.get(action.upper(), action.lower())


# ─── 数据类型 ───

@dataclass
class ActionChoice:
    """统一的动作选项"""
    action: str                           # 归一化后的小写动作名: fold/check/call/raise/bet/allin/none/...
    amount: int = 0
    label: str = ""                        # 提示标签 e.g. "call (4)" / "raise (6)"
    reasoning: str = ""                   # 默认动作的来源说明
    source: str = "manual"                # "manual" | "strategy:gto" | "fallback"
    raw: str = ""                         # 原始字符串（区分 RAISE / BET 等）
    # 决策元数据（由策略 ActionPlan 拷贝，供手牌历史记录使用）
    equity: float = 0.0
    pot_odds: float = 0.0
    ev: float = 0.0
    confidence: float = 1.0
    strategy_name: str = ""


# ─── payload → GameState ───

def payload_to_gamestate(payload: Dict[str, Any], my_seat_id: Optional[int] = None) -> GameState:
    """从各模式通用的 payload dict 构造 strategies.GameState。

    兼容字段（按 schema 出现频率从高到低）：
    - hole_cards / community_cards: List[str] (e.g. ["Ah","Kd"])
    - pot / to_call / min_raise / max_raise: int
    - my_seat_id: int（调用方未传时回退到 payload 字段）
    - players: Dict[str|int, {name, chips, status, is_active, hands_played, vpip_actions, pfr_actions}]
    """
    gs = GameState()
    gs.hole_cards = list(payload.get("hole_cards") or [])
    gs.community_cards = list(payload.get("community_cards") or [])
    gs.pot = int(payload.get("pot", 0) or 0)
    gs.to_call = int(payload.get("to_call", 0) or 0)
    gs.min_raise = int(payload.get("min_raise", 0) or 0)
    gs.max_raise = int(payload.get("max_raise", 0) or 0)
    gs.current_stage = payload.get("current_stage", "preflop")

    if my_seat_id is None:
        my_seat_id = payload.get("my_seat_id")
    gs.my_seat_id = my_seat_id
    gs.total_chips = int(payload.get("my_chips", payload.get("total_chips", 0)) or 0)
    gs.big_blind = int(payload.get("big_blind", 0) or 0)

    for sid_key, pd in (payload.get("players") or {}).items():
        try:
            sid = int(sid_key)
        except (ValueError, TypeError):
            continue
        gs.players[sid] = StrategyPlayer(
            seat_id=sid,
            user_id=str(pd.get("user_id", "")),
            name=pd.get("name", "") or f"Seat{sid}",
            chips=int(pd.get("chips", 0) or 0),
            is_active=bool(pd.get("is_active", pd.get("status", "active") not in ("folded", "sit_out"))),
            status=pd.get("status", "active"),
            hands_played=int(pd.get("hands_played", 0) or 0),
            vpip_actions=int(pd.get("vpip_actions", 0) or 0),
            pfr_actions=int(pd.get("pfr_actions", 0) or 0),
        )
    return gs


# ─── 策略建议 ───

# 单例：避免每次决策都重建（strategies 可能持有内部缓存）
_strategy_singleton: Dict[str, Any] = {}


def get_strategy_suggestion(
    state: GameState,
    strategy_name: str = "tag",
) -> Optional[ActionChoice]:
    """运行指定策略，返回推荐动作。

    失败时返回 None（调用方应回退到自己的启发式默认）。
    """
    try:
        # 使用稳定的 key（策略名 + id(state)）让同一局内复用同一实例
        cache_key = strategy_name
        strategy = _strategy_singleton.get(cache_key)
        if strategy is None:
            mgr = StrategyManager()
            strategy = mgr.create_strategy(table_id="cli_default", strategy_type=strategy_name)
            if strategy is None:
                cli_logger.warning(f"策略 '{strategy_name}' 创建失败")
                return None
            _strategy_singleton[cache_key] = strategy

        plan = strategy.make_decision(state)
        if plan is None:
            return None

        to_call = state.to_call
        pot = state.pot
        action_type, amount = plan.get_action_for_bet(to_call, pot)

        return ActionChoice(
            action=normalize_action(action_type.value),
            amount=int(amount or 0),
            label=_format_action_label(action_type.value, amount, to_call, state.min_raise, state.max_raise),
            reasoning=f"[{plan.strategy_name}] {plan.reasoning}",
            source=f"strategy:{strategy_name}",
            raw=action_type.value,
            equity=plan.my_equity,
            pot_odds=plan.pot_odds,
            ev=plan.ev,
            confidence=plan.confidence,
            strategy_name=plan.strategy_name,
        )
    except Exception as e:
        cli_logger.warning(f"策略建议失败: {e}")
        return None


def _format_action_label(action: str, amount: int, to_call: int, min_raise: int, max_raise: int) -> str:
    """生成动作的展示标签"""
    a = action.upper()
    if a == "CALL":
        return f"call ({amount or to_call})"
    if a in ("RAISE", "BET"):
        lo = min_raise or amount
        hi = max_raise or amount
        if lo and hi and lo != hi:
            return f"{a.lower()} <金额> ({lo}-{hi})"
        return f"{a.lower()} {amount}" if amount else f"{a.lower()} <金额>"
    return a.lower()


# ─── 金额快捷键（min/half/pot/max/Nx/3/4）───

def compute_presets(payload: Dict[str, Any]) -> Dict[str, int]:
    """计算所有可用的金额预设，返回 {name: amount}。

    命名空间：min / half / pot / 3/4 / 2x / 3x / 4x / max
    金额语义：raise-to（加注至），不是 raise-by（再加多少）
    """
    pot = int(payload.get("pot", 0) or 0)
    to_call = int(payload.get("to_call", 0) or 0)
    min_raise = int(payload.get("min_raise", 0) or 0)
    max_raise = int(payload.get("max_raise", 0) or 0)
    my_chips = int(payload.get("my_chips", 0) or 0)

    # 如果 max_raise 没给，用 my_chips + to_call 兜底（等同于全下）
    if max_raise <= 0 and my_chips > 0:
        max_raise = my_chips + to_call

    presets: Dict[str, int] = {}

    if min_raise > 0:
        presets["min"] = min_raise

    # half / pot / 3/4：raise-to 总额
    if pot > 0:
        if to_call == 0:
            # 没人下注时：相对 pot 的绝对值
            half = max(0, pot // 2)
            full = pot
            three_q = max(0, (pot * 3) // 4)
        else:
            # 跟注后：pot-based raise-to
            # raise-to = pot + to_call + (pot * fraction)
            half = pot + to_call + max(0, pot // 2)
            full = (pot + to_call) * 2
            three_q = pot + to_call + max(0, (pot * 3) // 4)
        if half:
            presets["half"] = half
        presets["pot"] = full
        if three_q and three_q != full:
            presets["3/4"] = three_q

    # 2x/3x/4x：N 倍当前下注（to_call）
    if to_call > 0:
        presets["2x"] = to_call * 2
        presets["3x"] = to_call * 3
        presets["4x"] = to_call * 4

    # max / allin
    if max_raise > 0:
        presets["max"] = max_raise

    # 去重 + 排序（按金额升序）
    unique: Dict[str, int] = {}
    for k, v in presets.items():
        if v <= 0:
            continue
        if k not in unique:
            unique[k] = v
    return dict(sorted(unique.items(), key=lambda kv: kv[1]))


def resolve_amount(token: str, payload: Dict[str, Any]) -> Optional[int]:
    """把用户输入的金额 token 解析成整数。失败返回 None。

    支持：
    - 整数 "50" / 浮点 "12.5"（截断）
    - 预设名 "min" / "half" / "pot" / "3/4" / "2x" / "3x" / "4x" / "max"
    - 百分比 "75%" / "50%"（相对 pot）
    """
    token = token.strip().lower()
    if not token:
        return None

    # 整数
    try:
        return int(float(token))
    except ValueError:
        pass

    # 百分比
    if token.endswith("%"):
        try:
            pct = float(token[:-1]) / 100.0
            pot = int(payload.get("pot", 0) or 0)
            to_call = int(payload.get("to_call", 0) or 0)
            if pot <= 0:
                return None
            if to_call > 0:
                return int(pot + to_call + pot * pct)
            return int(pot * pct)
        except ValueError:
            return None

    # 预设名
    presets = compute_presets(payload)
    return presets.get(token)


# ─── 默认动作（兜底启发式）───

def heuristic_default(available: List[str], to_call: int) -> ActionChoice:
    """当策略建议不可用时的回退默认：check > call > fold"""
    avail_norm = {normalize_action(a) for a in available}
    if "check" in avail_norm:
        return ActionChoice("check", 0, "check", "回退默认：check > call > fold", "fallback")
    if "call" in avail_norm:
        return ActionChoice("call", to_call, f"call ({to_call})", "回退默认：check > call > fold", "fallback")
    return ActionChoice("fold", 0, "fold", "回退默认：check > call > fold", "fallback")


def build_default(
    payload: Dict[str, Any],
    strategy_name: str = "tag",
) -> ActionChoice:
    """根据 payload 构造默认动作：优先 GTO 策略，失败回退到启发式"""
    available = payload.get("available_actions") or payload.get("available") or []
    to_call = int(payload.get("to_call", 0) or 0)

    state = payload_to_gamestate(payload)
    if state.hole_cards and len(state.hole_cards) >= 2 and state.my_seat_id is not None:
        suggestion = get_strategy_suggestion(state, strategy_name)
        if suggestion is not None:
            # 仅当策略推荐的动作在可用列表里时才采用
            avail_norm = {normalize_action(a) for a in available}
            if suggestion.action in avail_norm:
                return suggestion
            # 策略推荐不在 available 里（极少见）→ 回退
            cli_logger.debug(
                f"策略推荐 {suggestion.action} 不在可用动作 {avail_norm}，回退到启发式"
            )

    return heuristic_default(available, to_call)


# ─── 渲染 ───

_STAGE_CN = {
    "preflop": "翻牌前",
    "flop": "翻牌",
    "turn": "转牌",
    "river": "河牌",
    "showdown": "摊牌",
}

_STATUS_MARK = {
    "active": "[green]●[/green]",
    "folded": "[dim]✕ 弃牌[/dim]",
    "all_in": "[red]▲ 全押[/red]",
    "sit_out": "[yellow]○ 暂离[/yellow]",
    "allin": "[red]▲ 全押[/red]",
    "sitting_out": "[yellow]○ 暂离[/yellow]",
}


def display_hand_state(
    payload: Dict[str, Any],
    default: Optional[ActionChoice] = None,
    title_suffix: str = "",
) -> None:
    """统一的桌面状态渲染（Panel + 玩家表 + 可用动作）"""
    hole = payload.get("hole_cards") or []
    board = payload.get("community_cards") or []
    pot = int(payload.get("pot", 0) or 0)
    to_call = int(payload.get("to_call", 0) or 0)
    my_seat = payload.get("my_seat_id")
    stage = payload.get("current_stage", "preflop")
    stage_cn = _STAGE_CN.get(stage, stage)
    available = payload.get("available_actions") or payload.get("available") or []

    hand_str = " ".join(hole) if hole else "???"
    board_str = " ".join(board) if board else "(空)"

    # 顶部 Panel：阶段 / 手牌 / 公共牌 / 底池 / 跟注
    console.print()
    console.print(Panel(
        f"[bold]{stage_cn}[/bold]  |  "
        f"手牌: [bold cyan]{hand_str}[/bold cyan]  |  "
        f"公共牌: [bold cyan]{board_str}[/bold cyan]  |  "
        f"底池: [bold yellow]{pot}[/bold yellow]  |  "
        f"需跟注: [bold]{to_call}[/bold]",
        title=f"[bold]你的回合 (座位 {my_seat}){title_suffix}[/bold]",
        border_style="green",
    ))

    # 玩家表
    players_data = payload.get("players") or {}
    if players_data:
        players_table = Table(show_header=True, header_style="bold cyan", box=None)
        players_table.add_column("座位", style="bold")
        players_table.add_column("玩家")
        players_table.add_column("筹码", justify="right")
        players_table.add_column("状态")
        players_table.add_column("下注", justify="right")
        for sid_str in sorted(players_data.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
            pd = players_data[sid_str]
            status = pd.get("status", "active")
            style = {"active": "green", "folded": "red", "all_in": "yellow", "sit_out": "yellow"}.get(status, "white")
            is_me = int(sid_str) == my_seat if str(sid_str).isdigit() and my_seat is not None else False
            name = pd.get("name", "?")
            if is_me:
                name = f"[bold magenta]{name} (我)[/bold magenta]"
            players_table.add_row(
                str(sid_str),
                name,
                str(pd.get("chips", 0)),
                f"[{style}]{status}[/{style}]",
                str(pd.get("bet", 0)),
            )
        console.print(players_table)

    # 可用动作
    if available:
        parts = []
        presets = compute_presets(payload)
        for a in available:
            norm = normalize_action(a)
            if norm == "call" and to_call > 0:
                parts.append(f"[bold cyan]call ({to_call})[/bold cyan]")
            elif norm in ("raise", "bet"):
                # 把所有可用的 preset 金额列出来
                preset_chips = " / ".join(
                    f"[dim]{k}={v}[/dim]" for k, v in presets.items()
                ) if presets else ""
                if preset_chips:
                    parts.append(
                        f"[bold cyan]{norm} ({preset_chips} / 金额)[/bold cyan]"
                    )
                else:
                    parts.append(f"[bold cyan]{norm} <金额>[/bold cyan]")
            else:
                parts.append(f"[bold cyan]{norm}[/bold cyan]")
        console.print(f"可用动作: {' | '.join(parts)}")

    # 默认动作提示
    if default is not None:
        if default.source.startswith("strategy"):
            console.print(
                f"[dim]回车 = {default.label}  |  来源: {default.reasoning}[/dim]"
            )
        else:
            console.print(f"[dim]回车 = {default.label}[/dim]")

    console.print()


def display_table_state(
    payload: Dict[str, Any],
    default: Optional[ActionChoice] = None,
    title: str = "桌位状态",
) -> None:
    """统一的桌位决策渲染"""
    my_chips = int(payload.get("my_chips", 0) or 0)
    my_bank = int(payload.get("my_bank", 0) or 0)
    is_playing = bool(payload.get("is_playing", False))
    profit = int(payload.get("total_profit", 0) or 0)
    bb = int(payload.get("current_bb", 2) or 2)

    profit_style = "green" if profit > 0 else ("red" if profit < 0 else "white")
    status = "[green]参与中[/green]" if is_playing else "[yellow]观战中[/yellow]"

    console.print(Panel(
        f"桌上筹码: [bold]{my_chips}[/bold] ({my_chips / bb:.0f} BB)  |  "
        f"银行: {my_bank}  |  "
        f"盈亏: [{profit_style}]{profit:+d}[/{profit_style}]  |  "
        f"状态: {status}",
        title=f"[bold]{title}[/bold]",
        border_style="blue",
    ))
    if default is not None and default.action != "none":
        console.print(f"[dim]回车 = {default.label}[/dim]")
    else:
        console.print("[dim]回车 = none (继续) | sit_in | sit_out | add <金额> | leave[/dim]")


# ─── 提示输入循环 ───

def _print_hand_help(available: List[str], default: Optional[ActionChoice]) -> None:
    console.print("\n[bold]手牌命令:[/bold]")
    avail = {normalize_action(a) for a in available}
    if "fold" in avail:
        console.print("  fold           - 弃牌")
    if "check" in avail:
        console.print("  check          - 过牌")
    if "call" in avail:
        console.print("  call           - 跟注")
    if "raise" in avail:
        console.print("  raise          - 按 GTO 默认金额加注")
        console.print("  raise <金额>   - 整数金额（raise-to）")
        console.print("  raise min      - 最小加注")
        console.print("  raise half     - 半个底池")
        console.print("  raise pot      - 满底池")
        console.print("  raise 3/4      - 3/4 底池")
        console.print("  raise 2x/3x/4x - 2/3/4 倍当前下注")
        console.print("  raise 75%      - 底池 75%")
        console.print("  raise max      - 全下")
    if "bet" in avail:
        console.print("  bet <金额|快捷> - 下注（同 raise 的快捷键）")
    if "allin" in avail:
        console.print("  allin / all_in - 全下")
    console.print("  status         - 重新显示状态")
    console.print("  help           - 显示帮助")
    if default is not None:
        console.print(f"  [dim]回车       - {default.label}[/dim]")
    console.print()


def _print_table_help() -> None:
    console.print("\n[bold]桌位命令:[/bold]")
    console.print("  none           - 无操作（默认）")
    console.print("  sit_in         - 坐入参与")
    console.print("  sit_out        - 站起观战")
    console.print("  add <金额>     - 补充筹码")
    console.print("  leave          - 离场")
    console.print("  status         - 显示状态")
    console.print("  help           - 显示帮助")
    console.print()


async def prompt_hand_action(
    payload: Dict[str, Any],
    default: Optional[ActionChoice] = None,
    prompt_prefix: str = "browser",
    context: str = "",
) -> ActionChoice:
    """统一的 CLI 手牌决策输入循环。返回归一化的 ActionChoice"""
    available = payload.get("available_actions") or payload.get("available") or []
    avail_norm = {normalize_action(a) for a in available}
    to_call = int(payload.get("to_call", 0) or 0)
    min_raise = int(payload.get("min_raise", 0) or 0)
    max_raise = int(payload.get("max_raise", 0) or 0)

    if default is None:
        default = heuristic_default(list(available), to_call)
    display_hand_state(payload, default)

    # 明确告知用户可以输入什么（避免误以为只是提示）
    console.print(
        f"[dim]输入指令并按 Enter（直接回车 = 使用默认 {default.label}）[/dim]"
    )

    # 把 prompt 单独打印（用 console.print 强制 flush），然后用裸 input() 读一行
    # 注意：input() 不支持 flush 参数（仅 print() 支持）
    console.print(f"[bold]{prompt_prefix}>[/bold] ", end="")

    while True:
        try:
            loop = asyncio.get_running_loop()
            cmd_line = await loop.run_in_executor(None, input)
        except (KeyboardInterrupt, EOFError):
            return default
        cmd_line = cmd_line.strip().lower()

        # 回车 = 默认
        if not cmd_line:
            cli_logger.info(f"CLI 手牌决策(默认): {default.action} {default.amount} | {context}")
            return default

        parts = cmd_line.split()
        cmd = parts[0]

        if cmd in ("help", "h", "?"):
            _print_hand_help(available, default)
            continue

        if cmd == "status":
            display_hand_state(payload, default)
            continue

        if cmd == "fold" and "fold" in avail_norm:
            return ActionChoice("fold", 0, "fold", "用户输入", "manual")
        if cmd == "check" and "check" in avail_norm:
            return ActionChoice("check", 0, "check", "用户输入", "manual")
        if cmd == "call" and "call" in avail_norm:
            return ActionChoice("call", to_call, f"call ({to_call})", "用户输入", "manual")
        if cmd in ("allin", "all_in") and "allin" in avail_norm:
            return ActionChoice("allin", max_raise or to_call, "allin", "用户输入", "manual")

        if cmd in ("raise", "bet") and (cmd in avail_norm):
            # `raise` 不带金额 → 用默认动作的金额（GTO 推荐的）
            if len(parts) == 1:
                # 默认动作是 raise/bet 时复用它的金额
                if default.action in ("raise", "bet") and default.amount > 0:
                    return ActionChoice(
                        cmd, default.amount, f"{cmd} {default.amount}", "用户快捷(默认金额)", "manual"
                    )
                console.print(f"[red]用法: {cmd} <金额|快捷键>[/red]")
                continue

            amount_token = parts[1]
            amount = resolve_amount(amount_token, payload)
            if amount is None:
                # 显示可用的快捷键
                presets = compute_presets(payload)
                hint = " / ".join(f"{k}={v}" for k, v in list(presets.items())[:6])
                console.print(
                    f"[red]无效金额: {amount_token}。快捷键: {hint} / <整数> / <百分比>[/red]"
                )
                continue

            if min_raise and amount < min_raise:
                console.print(
                    f"[red]加注金额 {amount} 小于最小加注 {min_raise}，已自动调整到 {min_raise}[/red]"
                )
                amount = min_raise
            if max_raise and amount > max_raise:
                console.print(
                    f"[red]加注金额 {amount} 超过最大加注 {max_raise}，已自动调整到 {max_raise}[/red]"
                )
                amount = max_raise
            return ActionChoice(cmd, amount, f"{cmd} {amount}", "用户输入", "manual")

        console.print(
            f"[red]无效命令: {cmd}。可用: {', '.join(sorted(avail_norm)) or '(无)'}[/red]"
        )


async def prompt_table_action(
    payload: Dict[str, Any],
    default: Optional[ActionChoice] = None,
    prompt_prefix: str = "ring",
    title: str = "桌位状态",
    context: str = "",
) -> ActionChoice:
    """统一的 CLI 桌位决策输入循环。返回归一化的 ActionChoice"""
    if default is None:
        default = ActionChoice("none", 0, "none", "默认继续", "fallback")
    display_table_state(payload, default, title=title)

    console.print(
        f"[dim]输入指令并按 Enter（直接回车 = 使用默认 {default.label}）[/dim]"
    )

    # input() 不支持 flush 参数，用 console.print 强制刷出 prompt
    console.print(f"[bold]{prompt_prefix}[table]>[/bold] ", end="")

    while True:
        try:
            loop = asyncio.get_running_loop()
            cmd_line = await loop.run_in_executor(None, input)
        except (KeyboardInterrupt, EOFError):
            return default
        cmd_line = cmd_line.strip().lower()

        if not cmd_line:
            cli_logger.info(f"CLI 桌位决策(默认): {default.action} | {context}")
            return default

        parts = cmd_line.split()
        cmd = parts[0]

        if cmd in ("help", "h", "?"):
            _print_table_help()
            continue

        if cmd == "status":
            display_table_state(payload, default, title=title)
            continue

        if cmd == "none":
            return ActionChoice("none", 0, "none", "用户输入", "manual")
        if cmd == "sit_in":
            return ActionChoice("sit_in", 0, "sit_in", "用户输入", "manual")
        if cmd == "sit_out":
            return ActionChoice("sit_out", 0, "sit_out", "用户输入", "manual")
        if cmd == "leave":
            return ActionChoice("leave", 0, "leave", "用户输入", "manual")

        if cmd == "add":
            if len(parts) > 1:
                try:
                    amount = int(parts[1])
                    return ActionChoice("add_chips", amount, f"add {amount}", "用户输入", "manual")
                except ValueError:
                    console.print("[red]金额必须是整数[/red]")
                    continue
            else:
                console.print("[red]用法: add <金额>[/red]")
                continue

        console.print(f"[red]无效命令: {cmd}。输入 help 查看帮助[/red]")


# ─── 兼容旧 API 的便捷函数 ───

async def decide_hand_with_strategy(
    payload: Dict[str, Any],
    prompt_prefix: str = "browser",
    strategy_name: str = "tag",
    context: str = "",
) -> Tuple[str, int]:
    """便捷函数：返回 (action, amount) 元组（兼容旧 caller 签名）"""
    default = build_default(payload, strategy_name=strategy_name)
    choice = await prompt_hand_action(payload, default=default, prompt_prefix=prompt_prefix, context=context)
    return choice.action, choice.amount
