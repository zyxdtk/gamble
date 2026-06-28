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
import copy
import enum
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.strategies.game_state import GameState, Player as StrategyPlayer
from src.strategies.strategy_manager import StrategyManager

from .diagnostics import log_exception_with_traceback  # noqa: E402

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

    安全检查：hole_cards 必须严格 2 张合法牌；community_cards 不能包含 hole_cards
    （防状态污染导致策略拿到错牌；6/28 多次出现 reasoning 引用了已不在局的旧牌）。
    """
    gs = GameState()
    raw_hole = list(payload.get("hole_cards") or [])
    raw_community = list(payload.get("community_cards") or [])

    # 牌值合法性：rank∈[2-9TJQKA] + suit∈[cdhs]
    _VALID_CARD = re.compile(r"^[2-9TJQKA][cdhs]$", re.IGNORECASE)

    def _valid_card(c):
        if not c or not isinstance(c, str) or len(c) < 2:
            return False
        return bool(_VALID_CARD.match(c))

    # 清洗 hole_cards：过滤非法值，去重
    clean_hole = []
    for c in raw_hole:
        if _valid_card(c) and c not in clean_hole:
            clean_hole.append(c)
    if len(clean_hole) != len(raw_hole):
        cli_logger.warning(
            f"[sanity] hole_cards 含非法/重复值: raw={raw_hole} → clean={clean_hole}"
        )
    # 限制为 2 张
    if len(clean_hole) > 2:
        cli_logger.warning(
            f"[sanity] hole_cards 超过 2 张: {clean_hole} → 截断为前 2 张"
        )
        clean_hole = clean_hole[:2]
    gs.hole_cards = clean_hole

    # 清洗 community_cards
    clean_community = []
    for c in raw_community:
        if _valid_card(c) and c not in clean_community:
            clean_community.append(c)
    gs.community_cards = clean_community

    # 防御：community 不应包含 hole
    if gs.hole_cards and any(c in gs.community_cards for c in gs.hole_cards):
        leaked = [c for c in gs.hole_cards if c in gs.community_cards]
        cli_logger.warning(
            f"[sanity] community_cards 包含 hole_cards: {leaked} → 从 community 移除"
        )
        gs.community_cards = [c for c in gs.community_cards if c not in gs.hole_cards]

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


# ─── 反 limp 守卫（翻前） ───
# 数据依据：6/28 当日 71 局中，"未面对 raise 的翻前跟注"进翻后 26 局总亏 -811 (-31/局)。
# 来源：limped pot 中 Tier 3 手牌（88/77/AJs/QJs 等）跟注控池无意义，胜率与底池不成比例。
# 解决：limped pot（to_call > 0 且 to_call <= bb，无人加注）时，Tier 3+ 手牌 call 强制改 fold。
_ANTI_LIMP_MAX_TIER = 2  # 允许跟 limp 的最大 tier（1=Tier1 顶级, 2=Tier2 强牌, 3+=拒绝）
# 允许跟 limp 的 Tier 3 例外：同花连牌有隐含赔率
_LIMP_SUITED_CONNECTOR_TIERS = {3}  # 仅在 SUITED CONNECTOR 时允许 Tier 3 跟 limp


def _is_limp_pot(to_call: int, big_blind: int, pot: int) -> bool:
    """检测是否处于 limped pot：有人跟注但无人加注。

    判据（保守）：
    - to_call > 0（确实需要付钱）
    - to_call <= big_blind（只需要跟盲注，未被加注）
    - pot <= 4 * big_blind（底池很小，间接佐证无人加注）
    """
    if big_blind <= 0:
        return False
    if to_call <= 0:
        return False
    if to_call > big_blind:
        return False
    if pot > 4 * big_blind:
        return False
    return True


def _hand_tier_for_cards(hole_cards) -> int:
    """计算给定手牌的 tier，1=顶级, 4=垃圾。"""
    try:
        from src.strategies.utils.position import normalize_hand_string
        from src.strategies.utils.preflop_range import PreflopRangeManager
        if not hole_cards or len(hole_cards) < 2:
            return 4
        hand_str = normalize_hand_string(hole_cards)
        mgr = PreflopRangeManager()
        return mgr.get_hand_tier(hand_str)
    except Exception:
        return 4


def _is_suited_connector(hole_cards) -> bool:
    """是否是同花连牌（同花 + rank 相连）。"""
    if not hole_cards or len(hole_cards) < 2:
        return False
    ranks = "23456789TJQKA"
    try:
        c1, c2 = hole_cards[0], hole_cards[1]
        if not c1 or not c2 or len(c1) < 2 or len(c2) < 2:
            return False
        if c1[1].lower() != c2[1].lower():
            return False
        r1, r2 = ranks.index(c1[0].upper()), ranks.index(c2[0].upper())
        if abs(r1 - r2) == 1:
            return True
    except (ValueError, IndexError):
        return False
    return False


def anti_limp_guard(suggestion, state) -> Any:
    """翻前反 limp 守卫：弱牌拒绝跟 limped pot。

    替换策略推荐：策略说 call 且处于 limped pot 且手牌 tier 太低 → 改 fold。
    返回原 suggestion 或新构造的 fold 决策。
    """
    if suggestion is None:
        return suggestion
    if suggestion.action != "call":
        return suggestion
    if state.current_stage != "preflop":
        return suggestion
    if not _is_limp_pot(state.to_call, state.big_blind, state.pot):
        return suggestion
    if not state.hole_cards or len(state.hole_cards) < 2:
        return suggestion

    tier = _hand_tier_for_cards(state.hole_cards)

    # Tier 1-2 一律允许跟 limp（顶级/强牌有隐含赔率）
    if tier <= _ANTI_LIMP_MAX_TIER:
        return suggestion

    # Tier 3 例外：同花连牌允许跟 limp
    if tier in _LIMP_SUITED_CONNECTOR_TIERS and _is_suited_connector(state.hole_cards):
        return suggestion

    # 其余 Tier 3+：强制改 fold
    new_suggestion = copy.copy(suggestion)
    new_suggestion.action = "fold"
    new_suggestion.amount = 0
    new_suggestion.reasoning = (
        f"[anti-limp] Tier{tier}拒跟limp pot(to_call={state.to_call},pot={state.pot}) | "
        f"原:{suggestion.reasoning}"
    )
    new_suggestion.source = "anti_limp_guard"
    cli_logger.info(
        f"[anti-limp] 翻前 limp pot 守卫生效: {state.hole_cards} tier={tier} "
        f"to_call={state.to_call} pot={state.pot} → fold"
    )
    return new_suggestion


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
            # 策略没返回（极少见）→ 业务异常，不是 silent
            cli_logger.warning(
                "[get_strategy_suggestion] 策略 %r make_decision 返回 None，"
                "回退到启发式: hand=%s, street=%s, pot=%s, to_call=%s",
                strategy_name, getattr(state, "hole_cards", "?"),
                getattr(state, "current_stage", "?"), getattr(state, "pot", "?"),
                getattr(state, "to_call", "?"),
            )
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
        # 关键：必须带 traceback，否则只看到 str(e) 无法定位
        # traceback.format_exc() 来自 _diagnostics，确保 from .diagnostics 已被导入
        log_exception_with_traceback(
            cli_logger, e,
            f"[get_strategy_suggestion] 策略 '{strategy_name}' make_decision 抛异常，"
            "回退到启发式",
            strategy_name=strategy_name,
            hand=getattr(state, "hole_cards", "?"),
            street=getattr(state, "current_stage", "?"),
            pot=getattr(state, "pot", "?"),
            to_call=getattr(state, "to_call", "?"),
            my_seat_id=getattr(state, "my_seat_id", "?"),
        )
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


# ─── 策略→浏览器 动作适配器 ───
# 策略在抽象层输出（raise to X, bet Y, call Z），但浏览器真实层有 allin / min-raise cap / call-allin 等约束
# 适配器负责把策略意图翻译成浏览器真实可执行动作
#
# 映射表：
# ┌─────────────────┬────────────────────┬────────────────────────┐
# │ 策略推荐         │ 浏览器可用         │ 适配结果               │
# ├─────────────────┼────────────────────┼────────────────────────┤
# │ raise to X      │ raise              │ raise (X)              │
# │ raise to X      │ allin only         │ allin (chips)          │
# │ raise to X      │ call only          │ call (to_call)         │
# │ raise to X      │ check only         │ check                  │
# │ bet X           │ bet                │ bet (X)                │
# │ bet X           │ allin only         │ allin (chips)          │
# │ call            │ call (full)        │ call (to_call)         │
# │ call            │ allin only         │ allin (chips)          │
# │ call            │ check              │ check                  │
# │ check           │ check              │ check                  │
# │ fold            │ fold               │ fold                   │
# │ raise to X      │ raise + allin      │ raise (X)              │
# └─────────────────┴────────────────────┴────────────────────────┘

def _coerce_amount_to_chips(amount: int, chips: int) -> int:
    """把策略给的 amount 修正到合法范围：<= chips, >= 0"""
    if amount is None or amount <= 0:
        return max(0, chips)
    return min(int(amount), max(0, chips))


def adapt_strategy_to_browser_action(
    suggestion: ActionChoice,
    available_actions: List[str],
    *,
    chips: int,
    to_call: int,
    pot: int,
    state: Optional["GameState"] = None,
    logger: Optional[logging.Logger] = None,
) -> ActionChoice:
    """把策略推荐的 ActionChoice 适配到浏览器真实可执行的动作

    关键修复：策略想 raise / bet，但浏览器只 allin 可用 → 改为 allin
    关键修复：策略想 call，但筹码 < to_call → 改为 allin

    Args:
        suggestion:        策略输出的 ActionChoice
        available_actions: 浏览器当前可执行动作（已归一化: check/call/bet/raise/fold/allin）
        chips:            我方剩余筹码
        to_call:          需要跟注的金额
        pot:              当前底池
        state:            完整 GameState（用于取 hole_cards/street 给日志）
        logger:           日志对象

    Returns:
        适配后的 ActionChoice（如果浏览器无任何可执行动作，保留 suggestion 触发上游 fallback）
    """
    lg = logger or cli_logger
    avail = {normalize_action(a) for a in (available_actions or [])}
    action = normalize_action(suggestion.action)
    chips = int(chips or 0)
    to_call = int(to_call or 0)
    pot = int(pot or 0)

    hole_dbg = getattr(state, "hole_cards", "?") if state else "?"
    street_dbg = getattr(state, "current_stage", "?") if state else "?"

    # ── fold: 永远透传 ──
    if action == "fold":
        return suggestion

    # ── check: 浏览器必须能 check，否则退化 call/fold ──
    if action == "check":
        if "check" in avail:
            return suggestion
        # check 不在浏览器可用动作里 → 降级
        if "call" in avail:
            call_amt = min(to_call, chips)
            label = f"call ({call_amt})"
            new_action = "call"
            new_amt = call_amt
        elif "allin" in avail:
            new_action, new_amt, label = "allin", chips, f"allin ({chips})"
        else:
            # 连 call 都没有 → 改 fold（暴露完整诊断链）
            lg.warning(
                f"[adapter] 策略推荐 check 但浏览器无 check/call/allin，降级为 fold\n"
                f"  策略推荐: action={suggestion.action!r}, reasoning={suggestion.reasoning!r}\n"
                f"  浏览器可用: raw={available_actions}, normalized={avail}\n"
                f"  状态: street={street_dbg}, hole={hole_dbg}, to_call={to_call}, "
                f"chips={chips}, pot={pot}\n"
                f"  策略元数据: equity={suggestion.equity:.3f}, ev={suggestion.ev:.1f}"
            )
            return ActionChoice(
                "fold", 0, "fold",
                f"[adapter] check→fold (avail={avail})",
                source=suggestion.source or "adapter",
            )
        # 区分"免费 call"和"必须付钱"
        if to_call == 0:
            lg.info(
                f"[adapter] 策略推荐 check 但浏览器无 check → 免费 call 0 "
                f"(等效 check): street={street_dbg}, hole={hole_dbg}, "
                f"avail={avail}, equity={suggestion.equity:.3f}"
            )
        else:
            lg.info(
                f"[adapter] 策略推荐 check 但浏览器必须付钱 → {new_action} {new_amt}: "
                f"street={street_dbg}, hole={hole_dbg}, to_call={to_call}, chips={chips}"
            )
        return ActionChoice(
            new_action, new_amt, label,
            f"[adapter] check→{new_action} ({new_amt}) | {suggestion.reasoning}",
            source=suggestion.source or "adapter",
        )

    # ── raise / bet ──
    if action in ("raise", "bet"):
        # 情形 1：raise/bet 直接可用 → 透传（修正 amount 不超过 chips）
        if action in avail:
            new_amt = _coerce_amount_to_chips(suggestion.amount, chips)
            if new_amt != suggestion.amount and new_amt > 0:
                lg.info(
                    f"[adapter] 策略推荐 {action} {suggestion.amount} 但 chips={chips} "
                    f"→ 修正为 {action} {new_amt}: street={street_dbg}, hole={hole_dbg}"
                )
            return ActionChoice(
                action, new_amt,
                f"{action} ({new_amt})" if new_amt > 0 else action,
                f"[adapter] {action} 修正 {suggestion.amount}→{new_amt} | {suggestion.reasoning}",
                source=suggestion.source or "adapter",
            )

        # 情形 2：只有 allin 可用 → 改为 allin（关键修复）
        if "allin" in avail:
            new_amt = chips
            lg.info(
                f"[adapter] 策略推荐 {action} {suggestion.amount} 但浏览器只 allin 可用 "
                f"→ 改为 allin ({new_amt}): street={street_dbg}, hole={hole_dbg}, "
                f"pot={pot}, to_call={to_call}"
            )
            return ActionChoice(
                "allin", new_amt, f"allin ({new_amt})",
                f"[adapter] {action}→allin ({new_amt}) | {suggestion.reasoning}",
                source=suggestion.source or "adapter",
            )

        # 情形 3：只有 call 可用 → 改 call（除非 to_call > chips 走 allin 路径）
        if "call" in avail:
            if to_call <= chips:
                lg.info(
                    f"[adapter] 策略推荐 {action} 但浏览器只 call 可用 → 降级为 call: "
                    f"street={street_dbg}, hole={hole_dbg}, to_call={to_call}, chips={chips}"
                )
                return ActionChoice(
                    "call", to_call, f"call ({to_call})",
                    f"[adapter] {action}→call | {suggestion.reasoning}",
                    source=suggestion.source or "adapter",
                )
            # 筹码不够 call 完整 to_call → 改 allin（理论上不会出现，因为 allin 不在 avail）
            # 但如果浏览器没列 allin 但筹码不够 call，会报错。
            lg.warning(
                f"[adapter] 策略推荐 {action} 浏览器只 call 但 chips={chips} < to_call={to_call}，"
                f"无法执行，保留建议让上游 fallback: street={street_dbg}, hole={hole_dbg}"
            )
            return suggestion

        # 情形 4：只有 check / fold → 无法加注
        if "check" in avail:
            lg.info(
                f"[adapter] 策略推荐 {action} 但浏览器只 check 可用 → 降级为 check: "
                f"street={street_dbg}, hole={hole_dbg}"
            )
            return ActionChoice(
                "check", 0, "check",
                f"[adapter] {action}→check | {suggestion.reasoning}",
                source=suggestion.source or "adapter",
            )
        # 唯一可执行是 fold
        if "fold" in avail:
            lg.warning(
                f"[adapter] 策略推荐 {action} 但浏览器无可执行加注动作 → 降级为 fold: "
                f"street={street_dbg}, hole={hole_dbg}, avail={avail}"
            )
            return ActionChoice(
                "fold", 0, "fold",
                f"[adapter] {action}→fold (无可用加注) | {suggestion.reasoning}",
                source=suggestion.source or "adapter",
            )
        # 浏览器无任何动作（极少见）→ 透传让上游处理
        return suggestion

    # ── call ──
    if action == "call":
        # 情形 1：call 可用且筹码够 → 透传，但修正 amount 为 to_call
        # （策略常传 0，浏览器实际需 to_call；保持 amount 与实际一致便于手牌历史记录）
        if "call" in avail and to_call <= chips:
            if suggestion.amount != to_call:
                return ActionChoice(
                    suggestion.action, to_call,
                    f"call ({to_call})",
                    f"[adapter] call 修正 amount {suggestion.amount}→{to_call} | {suggestion.reasoning}",
                    source=suggestion.source or "adapter",
                )
            return suggestion
        # 情形 2：筹码 < to_call 但有 allin → 改 allin
        if "allin" in avail and chips < to_call:
            lg.info(
                f"[adapter] 策略推荐 call {to_call} 但 chips={chips} 不足 → 改为 allin: "
                f"street={street_dbg}, hole={hole_dbg}, to_call={to_call}"
            )
            return ActionChoice(
                "allin", chips, f"allin ({chips})",
                f"[adapter] call→allin (筹码不足) | {suggestion.reasoning}",
                source=suggestion.source or "adapter",
            )
        # 情形 3：call 不可用但 check 可用 → 改 check
        if "call" not in avail and "check" in avail:
            lg.info(
                f"[adapter] 策略推荐 call 但浏览器只 check 可用 → 降级为 check: "
                f"street={street_dbg}, hole={hole_dbg}"
            )
            return ActionChoice(
                "check", 0, "check",
                f"[adapter] call→check | {suggestion.reasoning}",
                source=suggestion.source or "adapter",
            )
        # 情形 4：fold 是唯一选择
        if "call" not in avail and "fold" in avail:
            lg.warning(
                f"[adapter] 策略推荐 call 但浏览器无法 call → 降级为 fold: "
                f"street={street_dbg}, hole={hole_dbg}, avail={avail}"
            )
            return ActionChoice(
                "fold", 0, "fold",
                f"[adapter] call→fold (不可用) | {suggestion.reasoning}",
                source=suggestion.source or "adapter",
            )
        return suggestion

    # ── allin: 透传（已在 avail 里）──
    if action == "allin":
        if "allin" in avail:
            return ActionChoice(
                "allin", chips, f"allin ({chips})",
                suggestion.reasoning, source=suggestion.source or "adapter",
            )
        # 策略想 allin 但浏览器没列 → 降级 raise/bet
        if "raise" in avail:
            return ActionChoice("raise", chips, f"raise ({chips})",
                                f"[adapter] allin→raise | {suggestion.reasoning}",
                                source=suggestion.source or "adapter")
        if "bet" in avail:
            return ActionChoice("bet", chips, f"bet ({chips})",
                                f"[adapter] allin→bet | {suggestion.reasoning}",
                                source=suggestion.source or "adapter")
        if "call" in avail:
            return ActionChoice("call", to_call, f"call ({to_call})",
                                f"[adapter] allin→call | {suggestion.reasoning}",
                                source=suggestion.source or "adapter")
        return ActionChoice("fold", 0, "fold",
                            f"[adapter] allin→fold (无 allin/raise/bet/call) | {suggestion.reasoning}",
                            source=suggestion.source or "adapter")

    # 未知动作：透传
    return suggestion


# ─── 默认动作（兜底启发式）───

def heuristic_default(
    available: List[str],
    to_call: int,
    hole_cards: Optional[List[str]] = None,
    pot: int = 0,
    street: str = "",
) -> ActionChoice:
    """当策略建议不可用时的回退默认

    优先级：
    1. 能 check 就 check（免费）
    2. 必须 call 时：只有免费（to_call=0）才 call，否则 fold
       - 旧版"call > fold"会主动送钱，例如 J2o 跟注 5 筹码的 c-bet
       - 没有策略支撑时，不应该默认 call 任何有成本的牌
    3. 兜底 fold

    Args:
        available:  可用动作列表（已归一化）
        to_call:    需要跟注的金额
        hole_cards: 底牌（用于诊断日志）
        pot:        当前底池（用于诊断日志）
        street:     当前街道（用于诊断日志）
    """
    avail_norm = {normalize_action(a) for a in available}
    if "check" in avail_norm:
        return ActionChoice(
            "check", 0, "check",
            f"回退默认: check (street={street}, pot={pot}, to_call={to_call})",
            "fallback",
        )
    # 必须 call 时：只在免费或 0 跟注时 call，否则 fold
    if "call" in avail_norm and to_call == 0:
        return ActionChoice(
            "call", 0, "call",
            f"回退默认: call (to_call=0, street={street}, pot={pot}, "
            f"hole={hole_cards})",
            "fallback",
        )
    # 有成本 + 无策略 → fold（避免盲打）
    return ActionChoice(
        "fold", 0, "fold",
        f"回退默认: fold (无策略，to_call={to_call}, pot={pot}, "
        f"street={street}, hole={hole_cards})",
        "fallback",
    )


def build_default(
    payload: Dict[str, Any],
    strategy_name: str = "tag",
) -> ActionChoice:
    """根据 payload 构造默认动作：优先 GTO 策略，失败回退到启发式"""
    available = payload.get("available_actions") or payload.get("available") or []
    to_call = int(payload.get("to_call", 0) or 0)
    pot = int(payload.get("pot", 0) or 0)
    street = payload.get("current_stage", "")
    hole_cards = payload.get("hole_cards") or []

    state = payload_to_gamestate(payload)
    if state.hole_cards and len(state.hole_cards) >= 2 and state.my_seat_id is not None:
        suggestion = get_strategy_suggestion(state, strategy_name)
        if suggestion is not None:
            # ── 反 limp 守卫：避免弱牌在 limped pot 跟注（数据：当日 -811/26局） ──
            suggestion = anti_limp_guard(suggestion, state)
            # ── 适配器：把策略推荐映射到浏览器真实可执行动作 ──
            # 关键场景：策略想 raise/bet，但浏览器只 allin → 改为 allin
            #           策略想 call，但 chips < to_call → 改为 allin
            #           策略想 check，但必须付钱 → 改为 call
            adapted = adapt_strategy_to_browser_action(
                suggestion, available,
                chips=int(payload.get("my_chips", 0) or 0),
                to_call=to_call,
                pot=pot,
                state=state,
                logger=cli_logger,
            )
            # 适配器成功（即结果是浏览器可执行的动作）
            avail_norm = {normalize_action(a) for a in available}
            if adapted.action in avail_norm:
                return adapted
            # 适配器未能落地（极少见，浏览器无可用动作）→ 回退
            # 暴露完整诊断链：策略原始推荐 → 适配结果 → 浏览器可用 → 为什么不行
            cli_logger.warning(
                f"[fallback] 适配后 {adapted.action!r} 仍不在可用动作 {avail_norm}，"
                f"回退到启发式\n"
                f"  策略原始推荐: action={suggestion.action!r}, amount={suggestion.amount}, "
                f"reasoning={suggestion.reasoning!r}\n"
                f"  适配结果: action={adapted.action!r}, amount={adapted.amount}, "
                f"reasoning={adapted.reasoning!r}\n"
                f"  浏览器可用: raw={available}, normalized={avail_norm}\n"
                f"  状态: street={street}, hole={hole_cards}, pot={pot}, "
                f"to_call={to_call}, my_chips={int(payload.get('my_chips', 0) or 0)}, "
                f"min_raise={int(payload.get('min_raise', 0) or 0)}, "
                f"max_raise={int(payload.get('max_raise', 0) or 0)}\n"
                f"  策略元数据: equity={suggestion.equity:.3f}, pot_odds={suggestion.pot_odds:.3f}, "
                f"ev={suggestion.ev:.1f}, confidence={suggestion.confidence:.2f}"
            )
        else:
            # 策略没返回（None 或抛错）→ 打 warning
            avail_norm = {normalize_action(a) for a in available}
            cli_logger.warning(
                f"[fallback] 策略 '{strategy_name}' 未返回建议（make_decision 返回 None），"
                f"回退到启发式\n"
                f"  浏览器可用: raw={available}, normalized={avail_norm}\n"
                f"  状态: street={street}, hole={hole_cards}, pot={pot}, "
                f"to_call={to_call}, my_chips={int(payload.get('my_chips', 0) or 0)}"
            )
    else:
        # payload 不完整（无底牌或无座位）→ 不能用策略
        cli_logger.warning(
            f"[fallback] payload 缺关键字段，回退到启发式\n"
            f"  缺失: hole_cards={hole_cards} ({'OK' if hole_cards else '空'}), "
            f"my_seat_id={state.my_seat_id} ({'OK' if state.my_seat_id is not None else 'None'})\n"
            f"  状态: street={street}, pot={pot}, to_call={to_call}\n"
            f"  浏览器可用: raw={available}"
        )

    return heuristic_default(available, to_call, hole_cards, pot, street)


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
