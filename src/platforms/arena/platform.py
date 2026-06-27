"""
Arena-based game platform implementation.

Wraps Competition to implement the GamePlatform interface,
and provides a standalone run() method for complete tournament execution.
"""

import asyncio
import time
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field

from ...core.interfaces import (
    GamePlatform,
    GameState,
    Player,
    GameAction,
    ActionType,
)
from ...core.events import (
    EventBus,
    EventType,
    GameEvent,
    get_event_bus,
)
from .game import GameEngine, Street, ActionType as ArenaActionType
from .competition import Competition
from .mtt import MTTManager, MTTConfig, MTTReport, MTTPlayerStats
from ...utils.logger import bot_logger


@dataclass
class ArenaPlayerConfig:
    """单个竞技场玩家配置"""
    name: str
    strategy: str  # "gto", "range", "exploitative", "checkorfold", "aggressive", "neural"
    initial_stack: int = 1000


@dataclass
class ArenaConfig:
    """竞技场比赛配置"""
    players: List[ArenaPlayerConfig]
    small_blind: int = 5
    big_blind: int = 10
    termination: str = "rounds"  # "rounds", "last_standing", "time"
    max_rounds: int = 100
    max_duration_min: Optional[int] = None


@dataclass
class PlayerStats:
    """玩家统计数据"""
    name: str
    strategy: str
    final_stack: int
    profit: int
    vpip: float
    pfr: float
    hands_won: int
    hands_played: int
    total_rebuys: int = 0
    locked_profit: int = 0
    # 风格量化指标
    af: float = 0.0
    three_bet_pct: float = 0.0
    wtsd: float = 0.0
    wsdp: float = 0.0
    bb_per_100: float = 0.0
    avg_pot_won: float = 0.0


@dataclass
class HandSummary:
    """单手牌简要记录"""
    hand_idx: int
    pot: int
    winners: List[str] = field(default_factory=list)
    stacks: Dict[str, int] = field(default_factory=dict)


@dataclass
class ArenaReport:
    """竞技场比赛报告"""
    num_hands: int
    duration_sec: float
    player_stats: List[PlayerStats]
    hand_log: List[HandSummary]


class ArenaPlatform(GamePlatform):
    """
    GamePlatform implementation for the local simulation arena.

    Supports two usage patterns:
    1. Standalone: create ArenaConfig, call run() -> ArenaReport
    2. GameRunner-compatible: use GamePlatform interface methods
    """

    def __init__(self, config: ArenaConfig, event_bus: EventBus = None):
        self._config = config
        self._event_bus = event_bus or get_event_bus()
        self._subscribers: List[Callable] = []

        self._competition: Optional[Competition] = None
        self._initialized = False

        # GamePlatform 兼容属性
        self._game_engine: Optional[GameEngine] = None
        self._current_player_idx = 0
        self._hand_in_progress = False
        self._hero_seat_id = 0

    async def initialize(self, **kwargs) -> None:
        """初始化竞技场平台"""
        strategy_names = [p.strategy for p in self._config.players]
        player_stacks = [p.initial_stack for p in self._config.players]

        self._competition = Competition(
            strategy_names=strategy_names,
            initial_stack=player_stacks[0] if len(set(player_stacks)) == 1 else 1000,
            small_blind=self._config.small_blind,
            big_blind=self._config.big_blind,
            player_stacks=player_stacks,
        )

        # 设置玩家名称
        for i, pc in enumerate(self._config.players):
            if pc.name:
                self._competition.agents[i].name = pc.name

        # GamePlatform 兼容
        self._game_engine = self._competition.engine
        self._hero_seat_id = 0
        self._initialized = True

        self._event_bus.publish(EventType.CONNECTED, {"platform": "arena"})
        bot_logger.info("ArenaPlatform 初始化成功")

    async def run(self) -> ArenaReport:
        """运行完整比赛并返回报告"""
        if not self._competition:
            await self.initialize()

        start_time = time.time()
        hand_log: List[HandSummary] = []

        if self._config.termination == "rounds":
            await self._run_rounds(self._config.max_rounds, hand_log)
        elif self._config.termination == "last_standing":
            await self._run_last_standing(self._config.max_rounds, hand_log)
        elif self._config.termination == "time":
            await self._run_time_limited(self._config.max_duration_min or 10, hand_log)
        else:
            await self._run_rounds(self._config.max_rounds, hand_log)

        duration = time.time() - start_time
        num_hands = self._competition.stats[0]['hands_played'] if self._competition else 0

        # 构建玩家统计
        player_stats = self._build_player_stats()

        report = ArenaReport(
            num_hands=num_hands,
            duration_sec=duration,
            player_stats=player_stats,
            hand_log=hand_log,
        )

        self._competition._print_summary(num_hands, duration)
        return report

    async def _run_rounds(self, max_rounds: int, hand_log: List[HandSummary]):
        """按轮数运行比赛"""
        for h in range(max_rounds):
            dealer_idx = h % len(self._competition.agents)
            self._record_hand_start(h + 1, hand_log)
            await self._competition._run_single_hand(dealer_idx, h + 1)
            self._record_hand_result(h + 1, hand_log)

            if h % 10 == 9:
                self._print_progress(h + 1, max_rounds)

    async def _run_last_standing(self, max_rounds: int, hand_log: List[HandSummary]):
        """运行至唯一幸存者"""
        for h in range(max_rounds):
            dealer_idx = h % len(self._competition.agents)
            await self._competition._run_single_hand(dealer_idx, h + 1)

            active_count = sum(
                1 for p in self._competition.engine.players if p.stack > 0
            )
            if active_count <= 1:
                break

    async def _run_time_limited(self, max_minutes: int, hand_log: List[HandSummary]):
        """按时间限制运行比赛"""
        import time as _time
        deadline = _time.time() + max_minutes * 60
        h = 0

        while _time.time() < deadline:
            dealer_idx = h % len(self._competition.agents)
            await self._competition._run_single_hand(dealer_idx, h + 1)
            h += 1

    def _record_hand_start(self, hand_idx: int, hand_log: List[HandSummary]):
        """记录手牌开始状态"""
        stacks = {
            self._competition.agents[i].name: self._competition.engine.players[i].stack
            for i in range(len(self._competition.agents))
        }
        hand_log.append(HandSummary(hand_idx=hand_idx, pot=0, stacks=dict(stacks)))

    def _record_hand_result(self, hand_idx: int, hand_log: List[HandSummary]):
        """记录手牌结果"""
        if hand_log and hand_log[-1].hand_idx == hand_idx:
            entry = hand_log[-1]
            entry.pot = self._competition.engine.pot
            # 更新栈状态
            for i in range(len(self._competition.agents)):
                entry.stacks[self._competition.agents[i].name] = self._competition.engine.players[i].stack

    def _print_progress(self, current: int, total: int):
        """打印比赛进度"""
        stacks = " ".join(
            f"{self._competition.agents[i].name}: {self._competition.engine.players[i].stack}"
            for i in range(len(self._competition.agents))
        )
        print(f"Hand {current}/{total} | {stacks}")

    def _build_player_stats(self) -> List[PlayerStats]:
        """构建玩家统计数据"""
        result = []
        bb = self._config.big_blind
        for i, agent in enumerate(self._competition.agents):
            s = self._competition.stats[i]
            hp = s['hands_played'] or 1
            vpip = (s['vpip_count'] / hp * 100) if hp > 0 else 0
            pfr = (s['pfr_count'] / hp * 100) if hp > 0 else 0

            # AF = (bet + raise) / call
            total_aggressive = s['bet_count'] + s['raise_count']
            af = total_aggressive / s['call_count'] if s['call_count'] > 0 else float(total_aggressive)

            # 3B%
            three_bet_pct = (s['three_bet_count'] / s['three_bet_opps'] * 100) if s['three_bet_opps'] > 0 else 0

            # WTSD% = saw_showdown / saw_flop
            wtsd = (s['saw_showdown_count'] / s['saw_flop_count'] * 100) if s['saw_flop_count'] > 0 else 0

            # W$SD% = won_at_showdown / saw_showdown
            wsdp = (s['won_at_showdown'] / s['saw_showdown_count'] * 100) if s['saw_showdown_count'] > 0 else 0

            # BB/100
            bb_per_100 = (s['profit'] / bb) / hp * 100 if hp > 0 else 0

            # Avg Pot
            avg_pot_won = (s['total_pot_won'] / s['wins']) if s['wins'] > 0 else 0

            result.append(PlayerStats(
                name=agent.name,
                strategy=self._config.players[i].strategy,
                final_stack=self._competition.engine.players[i].stack,
                profit=s['profit'],
                vpip=vpip,
                pfr=pfr,
                hands_won=s['wins'],
                hands_played=s['hands_played'],
                total_rebuys=s['total_rebuys'],
                locked_profit=s['locked_profit'],
                af=af,
                three_bet_pct=three_bet_pct,
                wtsd=wtsd,
                wsdp=wsdp,
                bb_per_100=bb_per_100,
                avg_pot_won=avg_pot_won,
            ))
        return result

    # === GamePlatform 接口方法（供 GameRunner 兼容使用）===

    async def get_game_state(self) -> GameState:
        """获取当前游戏状态"""
        if not self._game_engine:
            raise RuntimeError("ArenaPlatform 未初始化")

        street_map = {
            Street.PREFLOP: "preflop",
            Street.FLOP: "flop",
            Street.TURN: "turn",
            Street.RIVER: "river",
            Street.SHOWDOWN: "showdown",
        }

        from treys import Card

        core_state = GameState(
            hole_cards=[Card.int_to_str(c) for c in self._game_engine.players[self._hero_seat_id].hole_cards],
            community_cards=[Card.int_to_str(c) for c in self._game_engine.community_cards],
            pot=self._game_engine.pot,
            my_seat_id=self._hero_seat_id,
            active_seat=self._current_player_idx if self._hand_in_progress else None,
            to_call=self._game_engine.current_bet - self._game_engine.players[self._hero_seat_id].bet_this_street,
            min_raise=self._game_engine.min_raise,
            max_raise=self._game_engine.players[self._hero_seat_id].stack + self._game_engine.players[self._hero_seat_id].bet_this_street,
            available_actions=self._get_available_actions(),
            players={},
            total_chips=self._game_engine.players[self._hero_seat_id].stack,
            current_stage=street_map.get(self._game_engine.current_street, "preflop"),
            big_blind=self._config.big_blind,
        )

        for idx, player in enumerate(self._game_engine.players):
            core_player = Player(
                seat_id=idx,
                user_id=f"player_{idx}",
                name=player.name,
                chips=player.stack,
                is_active=player.is_active,
                is_acting=(idx == self._current_player_idx and self._hand_in_progress),
                status="all_in" if player.is_all_in else ("active" if player.is_active else "folded"),
                hands_played=0,
                vpip_actions=0,
                pfr_actions=0,
                bet=player.bet_this_street,
            )
            core_state.players[idx] = core_player

        return core_state

    async def execute_action(self, action: GameAction) -> bool:
        """执行动作"""
        if not self._game_engine:
            raise RuntimeError("ArenaPlatform 未初始化")

        action_map = {
            ActionType.FOLD: ArenaActionType.FOLD,
            ActionType.CHECK: ArenaActionType.CHECK,
            ActionType.CALL: ArenaActionType.CALL,
            ActionType.RAISE: ArenaActionType.RAISE,
            ActionType.ALL_IN: ArenaActionType.ALL_IN,
            ActionType.BET: ArenaActionType.RAISE,
        }

        arena_action = action_map.get(action.action_type, ArenaActionType.FOLD)
        bot_logger.info(f"执行动作: {action.action_type.value} (金额: {action.amount})")

        success = self._game_engine.execute_action(
            player_idx=self._hero_seat_id,
            action_type=arena_action,
            amount=action.amount,
        )

        if success:
            self._event_bus.publish(EventType.PLAYER_ACTION, {
                "action": action.action_type.value,
                "amount": action.amount,
                "reasoning": action.reasoning,
            })

        return success

    async def wait_for_my_turn(self, timeout: float = 300.0) -> bool:
        """等待轮到自己行动"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self._hand_in_progress and self._current_player_idx == self._hero_seat_id:
                return True
            await asyncio.sleep(0.1)
        return False

    async def wait_for_hand_start(self, timeout: float = 300.0) -> bool:
        """等待新一手牌开始"""
        if not self._game_engine:
            raise RuntimeError("ArenaPlatform 未初始化")

        dealer_idx = 0
        self._game_engine.reset_hand(dealer_idx=dealer_idx)
        self._game_engine.deal_hole_cards()
        self._current_player_idx = self._game_engine.post_blinds()
        self._hand_in_progress = True

        state = await self.get_game_state()
        self._event_bus.publish(EventType.HAND_START, {
            "hand_number": 1,
            "hole_cards": state.hole_cards,
        })
        self._event_bus.publish(EventType.HOLE_CARDS_DEALT, {"cards": state.hole_cards})
        self._event_bus.publish(EventType.PREFLOP, {})

        return True

    async def shutdown(self) -> None:
        """关闭竞技场"""
        self._game_engine = None
        self._initialized = False
        self._hand_in_progress = False
        self._event_bus.publish(EventType.DISCONNECTED, {"platform": "arena"})
        bot_logger.info("ArenaPlatform 已关闭")

    async def run_mtt(self, config: MTTConfig) -> MTTReport:
        """运行 MTT 锦标赛并返回报告"""
        from .mtt import MTTPlayerConfig

        manager = MTTManager(config)

        # 注册参赛者
        strategies = ["gto", "range", "exploitative", "checkorfold", "aggressive"]
        player_configs = []
        for i in range(config.entries):
            name = f"Player{i + 1}"
            strategy = "mixed" if config.strategy_distribution == "mixed" else config.strategy_distribution
            player_configs.append(MTTPlayerConfig(
                name=name,
                strategy=strategy,
                starting_stack=config.starting_stack,
            ))

        manager.register_players(player_configs)
        manager.initial_seating()
        return await manager.run()

    def subscribe_events(self, callback: Callable[[GameEvent], None]) -> None:
        """订阅游戏事件"""
        self._subscribers.append(callback)
        self._event_bus.subscribe_all(callback)

    def _get_available_actions(self) -> List[ActionType]:
        """获取当前玩家可用动作"""
        if not self._game_engine or not self._hand_in_progress:
            return []

        player = self._game_engine.players[self._current_player_idx]
        to_call = self._game_engine.current_bet - player.bet_this_street

        actions = []
        if to_call == 0:
            actions.append(ActionType.CHECK)
            actions.append(ActionType.RAISE)
        else:
            actions.append(ActionType.FOLD)
            actions.append(ActionType.CALL)
            if player.stack > 0:
                actions.append(ActionType.RAISE)

        if player.stack > 0 and to_call > player.stack:
            actions.append(ActionType.ALL_IN)

        return actions
