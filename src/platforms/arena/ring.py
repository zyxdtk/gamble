"""
Ring Game 无限注现金桌核心实现。

与 Competition 的区别：
1. 双工通信：Platform 推送状态给 Player，Player 异步返回决策
2. 双策略分离：TableStrategy（桌位策略）+ HandStrategy（手牌策略）
3. sit in/sit out、补筹码、止盈止损

不修改 GameEngine：sit_in/sit_out 逻辑在 RingPlatform._play_hand() 中处理，
构建 players_info 时只传入 is_playing and chips > 0 的玩家。
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from treys import Card

from src.core.pilot_decider import PilotDecider
from src.core.events import EventType, get_event_bus
from src.core.messaging import AsyncChannel, Message, MessageType
from src.platforms.arena.game import ActionType as ArenaActionType
from src.platforms.arena.game import GameEngine, PlayerState, Street
from src.strategies.action_plan import ActionType as StrategyActionType
from src.strategies.game_state import GameState, Player as StrategyPlayer
from src.strategies.hand_strategy import HandStrategy, StrategyHandAdapter
from src.strategies.table_strategy import (
    AggressiveTableStrategy,
    ConservativeTableStrategy,
    DefaultTableStrategy,
    TableAction,
    TableActionType,
    TableState,
    TableStrategy,
)
from src.utils.cli_player import ActionChoice, PilotMode
from src.utils.logger import arena_logger


# ─── 配置 ───

@dataclass
class RingPlayerConfig:
    """Ring Game 玩家配置"""
    name: str
    hand_strategy: str = "gto"           # 手牌策略名称
    table_strategy: str = "default"      # 桌位策略名称
    initial_bank: int = 2000             # 初始银行余额
    buyin_amount: int = 200              # 买入金额
    is_human: bool = False               # 是否为人类玩家（兼容旧代码）
    pilot_mode: PilotMode = PilotMode.AUTO  # 人类参与程度


@dataclass
class RingConfig:
    """Ring Game 配置"""
    players: List[RingPlayerConfig]
    small_blind: int = 1
    big_blind: int = 2
    max_rounds: int = 200
    max_seats: int = 9
    min_players_to_start: int = 2


# ─── 桌位管理 ───

@dataclass
class RingSeatState:
    """桌位状态"""
    seat_id: int
    player_id: str = ""
    name: str = ""
    chips: int = 0
    is_playing: bool = True   # sit_in=True, sit_out=False


class RingTable:
    """Ring Game 桌位管理"""

    def __init__(self, table_id: str, max_seats: int, sb: int, bb: int):
        self.table_id = table_id
        self.max_seats = max_seats
        self.sb = sb
        self.bb = bb
        self.seats: List[Optional[RingSeatState]] = [None] * max_seats

    def sit_player(self, player_id: str, name: str, buyin: int) -> int:
        """玩家入座，返回 seat_id"""
        for i, seat in enumerate(self.seats):
            if seat is None:
                self.seats[i] = RingSeatState(
                    seat_id=i, player_id=player_id, name=name,
                    chips=buyin, is_playing=True,
                )
                return i
        raise ValueError(f"桌子 {self.table_id} 已满，无法入座")

    def remove_player(self, seat_id: int) -> Optional[RingSeatState]:
        """移除玩家"""
        seat = self.seats[seat_id]
        self.seats[seat_id] = None
        return seat

    def sit_in(self, seat_id: int) -> None:
        seat = self.seats[seat_id]
        if seat:
            seat.is_playing = True

    def sit_out(self, seat_id: int) -> None:
        seat = self.seats[seat_id]
        if seat:
            seat.is_playing = False

    def add_chips(self, seat_id: int, amount: int) -> None:
        seat = self.seats[seat_id]
        if seat:
            seat.chips += amount

    def get_playing_players(self) -> List[RingSeatState]:
        """获取 sit_in 且筹码 > 0 的玩家"""
        return [
            s for s in self.seats
            if s is not None and s.is_playing and s.chips > 0
        ]

    def get_seated_players(self) -> List[RingSeatState]:
        """获取所有在座的玩家（包括 sit_out）"""
        return [s for s in self.seats if s is not None]

    @property
    def active_count(self) -> int:
        return len(self.get_playing_players())


# ─── RingPlayer ───

class RingPlayer:
    """
    Ring Game 玩家。

    通过 AsyncChannel 与 Platform 通信，
    主循环：接收消息 -> 分发给策略 -> 回复决策。
    """

    def __init__(
        self,
        player_id: str,
        name: str,
        table_strategy: TableStrategy,
        hand_strategy: HandStrategy,
        channel: AsyncChannel,
        is_human: bool = False,
        pilot_mode: PilotMode = PilotMode.AUTO,
    ):
        self.player_id = player_id
        self.name = name
        self.table_strategy = table_strategy
        self.hand_strategy = hand_strategy
        self.channel = channel
        self.is_human = is_human or pilot_mode != PilotMode.AUTO

        # PilotDecider：统一 AI/人类决策编排
        self._pilot_decider: Optional[PilotDecider] = None
        if pilot_mode != PilotMode.AUTO:
            # RingPlayer 的 hand_strategy 是 HandStrategy（非 Strategy），
            # PilotDecider 需要 Strategy，通过 StrategyHandAdapter 获取底层 strategy
            underlying_strategy = getattr(hand_strategy, '_strategy', hand_strategy)
            self._pilot_decider = PilotDecider(
                strategy=underlying_strategy,
                pilot_mode=pilot_mode,
                table_strategy=table_strategy,
            )

        # 运行时状态
        self.chips_on_table: int = 0
        self.bank: int = 0
        self.is_seated: bool = False
        self.is_playing: bool = False
        self.total_profit: int = 0
        self.hands_played: int = 0
        self.hands_sat_out: int = 0
        self.seat_id: int = -1

        # 统计
        self.vpip_count: int = 0
        self.pfr_count: int = 0
        self.hands_won: int = 0
        self.rebuy_count: int = 0
        self.add_chips_total: int = 0
        self.locked_profit: int = 0

        # 全局画像统计缓存（与 ArenaAgent.global_player_stats 相同模式）
        self.global_player_stats: Dict[int, Dict[str, int]] = {}

    async def run(self) -> None:
        """主循环：接收消息 -> 分发 -> 回复"""
        try:
            while True:
                msg = await self.channel.receive_from_platform(timeout=600.0)

                if msg.msg_type == MessageType.GAME_OVER:
                    arena_logger.info(f"玩家 {self.name} 收到游戏结束")
                    break

                response = await self._handle_message(msg)
                if response:
                    await self.channel.send_to_platform(response)

        except asyncio.TimeoutError:
            arena_logger.warning(f"玩家 {self.name} 等待消息超时")
        except asyncio.CancelledError:
            arena_logger.info(f"玩家 {self.name} 任务被取消")
        except Exception as e:
            arena_logger.error(f"玩家 {self.name} 运行错误: {e}")

    async def _handle_message(self, msg: Message) -> Optional[Message]:
        """处理收到的消息，返回可选的响应"""
        if msg.msg_type == MessageType.REQUEST_ACTION:
            return await self._handle_request_action(msg)
        elif msg.msg_type == MessageType.REQUEST_TABLE_ACTION:
            return await self._handle_request_table_action(msg)
        elif msg.msg_type == MessageType.TABLE_STATE:
            # 桌位状态推送，无需回复
            self._update_state_from_table_state(msg.payload)
            return None
        elif msg.msg_type == MessageType.HAND_STATE:
            # 手牌状态推送，无需回复
            return None
        elif msg.msg_type == MessageType.HAND_RESULT:
            self._handle_hand_result(msg.payload)
            return None
        return None

    async def _handle_request_action(self, msg: Message) -> Message:
        """处理手牌决策请求"""
        payload = msg.payload

        # 调用可重写的决策钩子
        action_str, amount = await self._decide_hand_action(payload)

        # 翻牌前行为统计
        current_stage = payload.get("current_stage", "preflop")
        if current_stage == "preflop":
            if action_str in ("CALL", "RAISE", "ALL_IN"):
                self.vpip_count += 1
            if action_str in ("RAISE", "ALL_IN"):
                self.pfr_count += 1

        arena_logger.info(
            f"[RING] 玩家 {self.name} 决策: {action_str} {amount}"
        )

        return Message(
            msg_type=MessageType.HAND_ACTION,
            payload={"action": action_str, "amount": amount},
            request_id=msg.request_id,
        )

    async def _decide_hand_action(self, payload: Dict[str, Any]) -> Tuple[str, int]:
        """手牌决策钩子 — 通过 PilotDecider 统一 AI/人类决策"""
        # 如果有 PilotDecider（非 AUTO 模式），走统一决策流程
        if self._pilot_decider:
            choice: ActionChoice = await self._pilot_decider.decide_hand(
                payload, prompt_prefix="ring",
                context=f"stage={payload.get('current_stage', '?')} pot={payload.get('pot', 0)}",
            )
            action_str = choice.raw or choice.action.upper()
            if choice.action == "allin" and not choice.raw:
                action_str = "ALL_IN"
            arena_logger.info(
                f"[PILOT] 玩家 {self.name} 手牌决策: {action_str} {choice.amount} (来源={choice.source})"
            )
            return action_str, choice.amount

        # AUTO 模式：纯 AI 策略决策
        game_state = self._restore_game_state(payload)

        if game_state is None:
            return "FOLD", 0

        plan = self.hand_strategy.make_decision(game_state)

        to_call = payload.get("to_call", 0)
        pot = payload.get("pot", 0)
        action_type, amount = plan.get_action_for_bet(to_call, pot)

        # 通知手牌策略观察事件
        self._notify_hand_event(payload, action_type, amount)

        return action_type.value, amount

    async def _handle_request_table_action(self, msg: Message) -> Message:
        """处理桌位决策请求"""
        payload = msg.payload

        # 调用可重写的决策钩子
        table_action = await self._decide_table_action(payload)

        arena_logger.info(
            f"[RING] 玩家 {self.name} 桌位决策: {table_action.action_type.value} "
            f"amount={table_action.amount} | {table_action.reasoning}"
        )

        return Message(
            msg_type=MessageType.TABLE_ACTION,
            payload=table_action.to_dict(),
            request_id=msg.request_id,
        )

    async def _decide_table_action(self, payload: Dict[str, Any]) -> TableAction:
        """桌位决策钩子 — 通过 PilotDecider 统一 AI/人类决策"""
        # 如果有 PilotDecider（非 AUTO 模式），走统一决策流程
        if self._pilot_decider:
            choice: ActionChoice = await self._pilot_decider.decide_table(
                payload, prompt_prefix="ring", title="桌位状态",
                context=f"chips={payload.get('my_chips', 0)} bank={payload.get('my_bank', 0)}",
            )
            arena_logger.info(
                f"[PILOT] 玩家 {self.name} 桌位决策: {choice.action} {choice.amount} (来源={choice.source})"
            )
            # ActionChoice → TableAction
            _TABLE_ACTION_MAP = {
                "none": TableActionType.NONE,
                "sit_in": TableActionType.SIT_IN,
                "sit_out": TableActionType.SIT_OUT,
                "leave": TableActionType.LEAVE,
                "add_chips": TableActionType.ADD_CHIPS,
            }
            action_type = _TABLE_ACTION_MAP.get(choice.action, TableActionType.NONE)
            return TableAction(
                action_type=action_type,
                amount=choice.amount if choice.action == "add_chips" else 0,
                reasoning=f"PilotDecider {choice.source}: {choice.reasoning or choice.action}",
            )

        # AUTO 模式：纯 AI 策略决策
        table_state = TableState(
            my_chips=payload.get("my_chips", 0),
            my_bank=payload.get("my_bank", 0),
            is_seated=payload.get("is_seated", False),
            is_playing=payload.get("is_playing", False),
            hands_played=payload.get("hands_played", 0),
            total_profit=payload.get("total_profit", 0),
            current_bb=payload.get("current_bb", 2),
            seat_count=payload.get("seat_count", 0),
            active_count=payload.get("active_count", 0),
            stop_loss_bb=payload.get("stop_loss_bb", 250),
            take_profit_bb=payload.get("take_profit_bb", 300),
            low_chips_bb=payload.get("low_chips_bb", 10),
            max_chips_bb=payload.get("max_chips_bb", 800),
        )

        return self.table_strategy.decide(table_state)

    def _update_state_from_table_state(self, payload: Dict[str, Any]) -> None:
        """从 TABLE_STATE 消息更新本地状态"""
        self.chips_on_table = payload.get("my_chips", self.chips_on_table)
        self.bank = payload.get("my_bank", self.bank)
        self.is_seated = payload.get("is_seated", self.is_seated)
        self.is_playing = payload.get("is_playing", self.is_playing)

    def _handle_hand_result(self, payload: Dict[str, Any]) -> None:
        """处理手牌结果"""
        won = payload.get("won", False)
        profit = payload.get("profit", 0)
        my_chips = payload.get("my_chips", 0)

        arena_logger.info(
            f"[RING] 玩家 {self.name} 手牌结果: "
            f"{'赢' if won else '输'} profit={profit} chips={my_chips} "
            f"bank={self.bank} total={self.total_profit:+d}"
        )

        # 更新桌上筹码（由 Platform 同步）
        if my_chips > 0:
            self.chips_on_table = my_chips

        # 通知手牌策略
        if payload.get("showdown"):
            showdown_data = {
                "user_id": self.player_id,
                "hand_str": payload.get("hand_str", ""),
                "street": payload.get("street", "showdown"),
            }
            self.hand_strategy.handle_event("showdown", showdown_data)

    def _notify_hand_event(
        self, payload: Dict[str, Any], action_type: StrategyActionType, amount: int
    ) -> None:
        """通知手牌策略观察到的动作"""
        action_str = action_type.value.lower()
        if action_str == "all_in":
            action_str = "raise"
        pot = payload.get("pot", 0)
        data = {
            "user_id": self.player_id,
            "action": action_str,
            "pot_ratio": amount / max(1, pot),
        }
        self.hand_strategy.handle_event("action", data)

    def _restore_game_state(self, payload: Dict[str, Any]) -> Optional[GameState]:
        """从 payload 恢复 GameState 对象"""
        try:
            gs = GameState()
            gs.my_seat_id = payload.get("my_seat_id")
            gs.hole_cards = payload.get("hole_cards", [])
            gs.community_cards = payload.get("community_cards", [])
            gs.pot = payload.get("pot", 0)
            gs.to_call = payload.get("to_call", 0)
            gs.min_raise = payload.get("min_raise", 0)
            gs.max_raise = payload.get("max_raise", 0)
            gs.available_actions = payload.get("available_actions", [])
            gs.current_stage = payload.get("current_stage", "preflop")
            gs.total_chips = payload.get("total_chips", 0)
            gs.my_initial_chips = payload.get("my_initial_chips", 0)
            gs.big_blind = payload.get("big_blind", 2)

            # 恢复玩家信息
            players_data = payload.get("players", {})
            for seat_id_str, p_data in players_data.items():
                seat_id = int(seat_id_str)
                sp = StrategyPlayer(
                    seat_id=seat_id,
                    user_id=p_data.get("user_id", ""),
                    name=p_data.get("name", ""),
                    chips=p_data.get("chips", 0),
                    is_active=p_data.get("is_active", True),
                    status=p_data.get("status", "active"),
                    bet=p_data.get("bet", 0),
                )
                # 恢复统计
                sp.hands_played = p_data.get("hands_played", 0)
                sp.vpip_actions = p_data.get("vpip_actions", 0)
                sp.pfr_actions = p_data.get("pfr_actions", 0)
                gs.players[seat_id] = sp

            return gs
        except Exception as e:
            arena_logger.error(f"恢复 GameState 失败: {e}")
            return None

    def update_global_stats(self, seat_id: int, is_vpip: bool, is_pfr: bool) -> None:
        """更新全局画像统计"""
        if seat_id not in self.global_player_stats:
            self.global_player_stats[seat_id] = {
                "hands": 0, "vpip_count": 0, "pfr_count": 0,
            }
        stats = self.global_player_stats[seat_id]
        stats["hands"] += 1
        if is_vpip:
            stats["vpip_count"] += 1
        if is_pfr:
            stats["pfr_count"] += 1


# ─── 统计与报告 ───

@dataclass
class RingPlayerStats:
    """Ring Game 玩家统计"""
    name: str
    strategy: str
    table_strategy_name: str
    final_chips: int = 0
    final_bank: int = 0
    total_profit: int = 0
    hands_played: int = 0
    hands_sat_out: int = 0
    vpip: float = 0.0
    pfr: float = 0.0
    hands_won: int = 0
    rebuy_count: int = 0
    add_chips_total: int = 0
    locked_profit: int = 0


@dataclass
class RingReport:
    """Ring Game 报告"""
    num_hands: int
    duration_sec: float
    player_stats: List[RingPlayerStats]
    hand_log: List[Dict[str, Any]] = field(default_factory=list)


# ─── RingPlatform ───

class RingPlatform:
    """
    Ring Game 平台。

    管理桌位、玩家、通信通道，
    通过 AsyncChannel 与每个 RingPlayer 异步交互。
    """

    def __init__(self, config: RingConfig, event_bus=None):
        self.config = config
        self.event_bus = event_bus or get_event_bus()
        self.table: Optional[RingTable] = None
        self.players: Dict[str, RingPlayer] = {}
        self.channels: Dict[str, AsyncChannel] = {}
        self.player_tasks: List[asyncio.Task] = []

    async def initialize(self) -> None:
        """初始化 Ring Game：创建 table、channel、player"""
        self.table = RingTable(
            table_id="ring_1",
            max_seats=self.config.max_seats,
            sb=self.config.small_blind,
            bb=self.config.big_blind,
        )

        for i, pc in enumerate(self.config.players):
            player_id = f"ring_player_{i}"

            # 创建通信通道
            channel = AsyncChannel(player_id=player_id)
            self.channels[player_id] = channel

            # 创建策略
            hand_strategy = self._create_hand_strategy(pc.hand_strategy)
            table_strategy = self._create_table_strategy(pc.table_strategy)

            # 创建玩家
            player = RingPlayer(
                player_id=player_id,
                name=pc.name,
                table_strategy=table_strategy,
                hand_strategy=hand_strategy,
                channel=channel,
                is_human=pc.is_human,
                pilot_mode=pc.pilot_mode,
            )
            player.bank = pc.initial_bank
            self.players[player_id] = player

        arena_logger.info(
            f"[RING] 初始化完成: {len(self.config.players)} 位玩家, "
            f"盲注 {self.config.small_blind}/{self.config.big_blind}"
        )

    async def run(self) -> RingReport:
        """主循环"""
        start_time = time.time()
        hand_log: List[Dict[str, Any]] = []

        # 1. 初始买入
        await self._initial_buyin()

        # 2. 启动所有 Player 任务
        for player_id, player in self.players.items():
            task = asyncio.create_task(player.run(), name=f"ring_player_{player.name}")
            self.player_tasks.append(task)

        # 3. 主循环
        try:
            for hand_idx in range(1, self.config.max_rounds + 1):
                # 桌位决策阶段
                should_continue = await self._table_decision_phase(hand_idx)
                if not should_continue:
                    break

                # 检查最低人数
                if self.table.active_count < self.config.min_players_to_start:
                    arena_logger.info(
                        f"[RING] 活跃玩家不足 ({self.table.active_count} < {self.config.min_players_to_start})，结束"
                    )
                    break

                # 执行一手牌
                hand_summary = await self._play_hand(hand_idx)
                hand_log.append(hand_summary)

                # 检查终止条件
                if self._check_termination():
                    break

        finally:
            # 通知所有 Player 游戏结束
            for player_id, channel in self.channels.items():
                try:
                    await channel.send_to_player(
                        Message(msg_type=MessageType.GAME_OVER, payload={})
                    )
                except Exception:
                    pass

            # 等待 Player 任务结束
            for task in self.player_tasks:
                task.cancel()
            await asyncio.gather(*self.player_tasks, return_exceptions=True)

        duration = time.time() - start_time
        report = self._build_report(len(hand_log), duration, hand_log)
        return report

    async def _initial_buyin(self) -> None:
        """初始买入"""
        for player_id, player in self.players.items():
            pc = self._get_player_config(player_id)
            if pc is None:
                continue

            buyin = min(pc.buyin_amount, player.bank)
            seat_id = self.table.sit_player(player_id, player.name, buyin)
            player.seat_id = seat_id
            player.chips_on_table = buyin
            player.bank -= buyin
            player.is_seated = True
            player.is_playing = True

            arena_logger.info(
                f"[RING] 玩家 {player.name} 入座 seat={seat_id}，买入 {buyin}"
            )

    async def _table_decision_phase(self, hand_idx: int) -> bool:
        """询问每位玩家的桌位决策"""
        for player_id, player in self.players.items():
            if not player.is_seated:
                continue

            table_state_payload = self._build_table_state(player_id)
            request = Message(
                msg_type=MessageType.REQUEST_TABLE_ACTION,
                payload=table_state_payload,
            )

            try:
                response = await self.channels[player_id].request_response(
                    request, timeout=10.0
                )
                self._apply_table_action(player_id, response.payload)
            except asyncio.TimeoutError:
                arena_logger.warning(f"[RING] 玩家 {player.name} 桌位决策超时")
            except Exception as e:
                arena_logger.error(f"[RING] 玩家 {player.name} 桌位决策错误: {e}")

            # 如果玩家离场，检查是否还有足够玩家
            if not player.is_seated:
                if self.table.active_count < self.config.min_players_to_start:
                    return False

        return True

    async def _play_hand(self, hand_idx: int) -> Dict[str, Any]:
        """执行一手牌"""
        playing = self.table.get_playing_players()
        if len(playing) < 2:
            return {"hand_idx": hand_idx, "skipped": True, "reason": "not enough players"}

        # 构建 players_info 给 GameEngine
        # 只传入 is_playing 且 chips > 0 的玩家
        players_info = [{"name": p.name, "stack": p.chips} for p in playing]
        engine = GameEngine(players_info, self.table.sb, self.table.bb)

        # 构建 seat_id -> engine_idx 映射
        seat_to_engine = {p.seat_id: i for i, p in enumerate(playing)}
        engine_to_seat = {i: p.seat_id for i, p in enumerate(playing)}
        player_id_by_seat = {p.seat_id: p.player_id for p in playing}

        # 选择庄家
        dealer_idx = (hand_idx - 1) % len(playing)

        # 重置并开始
        engine.reset_hand(dealer_idx, hand_idx)
        engine.deal_hole_cards()

        # 统计参与手数
        for p in playing:
            player = self.players.get(player_id_by_seat.get(p.seat_id, ""))
            if player:
                player.hands_played += 1

        # 记录翻牌前 VPIP/PFR 基准
        last_vpip = {pid: p.vpip_count for pid, p in self.players.items()}
        last_pfr = {pid: p.pfr_count for pid, p in self.players.items()}

        # 盲注
        current_idx = engine.post_blinds()

        # 翻牌前下注
        await self._betting_loop(engine, current_idx, playing, seat_to_engine,
                                  engine_to_seat, player_id_by_seat, hand_idx)

        # 后续街道
        while engine.current_street < Street.RIVER and self._count_active(engine) > 1:
            engine.next_street()
            first_actor = (engine.dealer_idx + 1) % len(playing)
            await self._betting_loop(engine, first_actor, playing, seat_to_engine,
                                      engine_to_seat, player_id_by_seat, hand_idx)

        # 摊牌观察
        if self._count_active(engine) > 1:
            curr_street = engine.current_street
            street_name = curr_street.name if isinstance(curr_street, Street) else str(curr_street)
            for p in engine.players:
                if p.is_active:
                    for seat_id, pid in player_id_by_seat.items():
                        player = self.players.get(pid)
                        if player and isinstance(player.hand_strategy, StrategyHandAdapter):
                            from src.strategies.utils import normalize_hand_string
                            hand_str = normalize_hand_string(
                                [Card.int_to_str(c) for c in p.hole_cards]
                            )
                            player.hand_strategy.handle_event("showdown", {
                                "user_id": f"player_{p.seat_id}",
                                "hand_str": hand_str,
                                "street": street_name.lower(),
                            })

        # 结算
        winners = engine.get_winners()
        winner_seat_ids = set()
        for seat_id_in_engine, amount in winners:
            seat_id = engine_to_seat.get(seat_id_in_engine)
            if seat_id is not None:
                engine.players[seat_id_in_engine].stack += amount
                winner_seat_ids.add(seat_id)
        # 每个 seat_id 只计一次胜场
        for seat_id in winner_seat_ids:
            pid = player_id_by_seat.get(seat_id)
            if pid and pid in self.players:
                self.players[pid].hands_won += 1

        # 同步筹码回 RingTable
        for p in engine.players:
            seat_id = engine_to_seat.get(p.seat_id)
            if seat_id is not None:
                seat = self.table.seats[seat_id]
                if seat:
                    seat.chips = p.stack

        # 通知手牌结果
        for pid, player in self.players.items():
            seat = self.table.seats[player.seat_id] if player.seat_id >= 0 else None
            if seat is None:
                continue

            won = player.seat_id in winner_seat_ids
            profit = seat.chips - player.chips_on_table if won else 0

            # 更新桌上筹码
            player.chips_on_table = seat.chips

            result_payload = {
                "hand_idx": hand_idx,
                "won": won,
                "profit": profit,
                "my_chips": seat.chips,
            }

            try:
                await self.channels[pid].send_to_player(
                    Message(msg_type=MessageType.HAND_RESULT, payload=result_payload)
                )
            except Exception:
                pass

        # 更新盈亏统计和全局画像
        for pid, player in self.players.items():
            is_vpip = player.vpip_count > last_vpip.get(pid, 0)
            is_pfr = player.pfr_count > last_pfr.get(pid, 0)

            # 更新所有玩家的全局画像
            for other_pid, other_player in self.players.items():
                other_player.update_global_stats(player.seat_id, is_vpip, is_pfr)

            # 更新总盈亏
            player.total_profit = (
                player.chips_on_table + player.bank + player.locked_profit
                - self._get_initial_total(pid)
            )

        # 发布事件
        self.event_bus.publish(EventType.HAND_END, {
            "hand_idx": hand_idx,
            "pot": engine.pot,
            "winners": [(engine_to_seat.get(sid), amt) for sid, amt in winners],
        })

        return {
            "hand_idx": hand_idx,
            "pot": engine.pot,
            "community_cards": [Card.int_to_str(c) for c in engine.community_cards],
            "winners": [(engine_to_seat.get(sid), amt) for sid, amt in winners],
        }

    async def _betting_loop(
        self,
        engine: GameEngine,
        start_idx: int,
        playing: List[RingSeatState],
        seat_to_engine: Dict[int, int],
        engine_to_seat: Dict[int, int],
        player_id_by_seat: Dict[int, str],
        hand_idx: int,
    ) -> None:
        """异步下注循环：通过 channel 请求决策"""
        num_players = len(playing)
        current_idx = start_idx

        if self._count_can_act(engine) <= 1:
            return

        acted = [False] * num_players

        while True:
            p = engine.players[current_idx]

            # 检查是否所有可以行动的玩家都已行动
            if all(
                not engine.players[i].is_active or engine.players[i].is_all_in or acted[i]
                for i in range(num_players)
            ):
                if not p.is_active or p.is_all_in or p.bet_this_street == engine.current_bet:
                    break

            if p.is_active and not p.is_all_in:
                seat_id = engine_to_seat.get(current_idx)
                pid = player_id_by_seat.get(seat_id)
                player = self.players.get(pid) if pid else None

                if player is None:
                    # 未知玩家，默认弃牌
                    engine.execute_action(current_idx, ArenaActionType.FOLD, 0)
                    acted[current_idx] = True
                    current_idx = (current_idx + 1) % num_players
                    continue

                # 构建手牌状态 payload
                hand_state_payload = self._build_hand_state_payload(
                    engine, current_idx, playing, engine_to_seat, player_id_by_seat
                )

                # 请求手牌决策
                request = Message(
                    msg_type=MessageType.REQUEST_ACTION,
                    payload=hand_state_payload,
                )

                try:
                    response = await self.channels[pid].request_response(
                        request, timeout=30.0
                    )
                    action_str = response.payload.get("action", "FOLD")
                    amount = response.payload.get("amount", 0)

                    # 转换为 ArenaActionType
                    arena_action = self._parse_arena_action(action_str)

                    engine.execute_action(current_idx, arena_action, amount)
                    acted[current_idx] = True

                    # 通知其他玩家
                    for other_pid, other_player in self.players.items():
                        if other_pid != pid:
                            try:
                                await self.channels[other_pid].send_to_player(
                                    Message(msg_type=MessageType.HAND_STATE, payload={
                                        "observed_action": {
                                            "seat_id": seat_id,
                                            "action": action_str,
                                            "amount": amount,
                                            "pot": engine.pot,
                                        }
                                    })
                                )
                            except Exception:
                                pass

                    if arena_action in (ArenaActionType.RAISE, ArenaActionType.ALL_IN):
                        for i in range(num_players):
                            if i != current_idx:
                                acted[i] = False

                except asyncio.TimeoutError:
                    arena_logger.warning(
                        f"[RING] 玩家 {player.name} 决策超时，自动弃牌"
                    )
                    engine.execute_action(current_idx, ArenaActionType.FOLD, 0)
                    acted[current_idx] = True

            if self._count_can_act(engine) <= 1 and engine.current_bet == p.bet_this_street:
                pass

            current_idx = (current_idx + 1) % num_players

            if self._count_active(engine) <= 1:
                break

    def _build_hand_state_payload(
        self,
        engine: GameEngine,
        engine_idx: int,
        playing: List[RingSeatState],
        engine_to_seat: Dict[int, int],
        player_id_by_seat: Dict[int, str],
    ) -> Dict[str, Any]:
        """
        构建 HAND_STATE payload。

        复用 ArenaAgent._translate_state() 的逻辑，
        将 GameEngine 状态翻译为可序列化的 payload。
        """
        p = engine.players[engine_idx]
        seat_id = engine_to_seat.get(engine_idx, -1)
        pid = player_id_by_seat.get(seat_id, "")
        player = self.players.get(pid)

        # 翻译手牌和公共牌
        hole_cards = [Card.int_to_str(c) for c in p.hole_cards]
        community_cards = [Card.int_to_str(c) for c in engine.community_cards]

        # 构建玩家信息
        players_data = {}
        for i, pa in enumerate(engine.players):
            pa_seat_id = engine_to_seat.get(i, -1)
            pa_pid = player_id_by_seat.get(pa_seat_id, "")
            pa_player = self.players.get(pa_pid)

            status = "active" if pa.is_active else "folded"
            if pa.is_all_in:
                status = "all_in"

            p_data = {
                "user_id": f"player_{pa_seat_id}",
                "name": pa.name,
                "chips": pa.stack,
                "is_active": pa.is_active,
                "status": status,
                "bet": pa.total_investment,
                "hands_played": 0,
                "vpip_actions": 0,
                "pfr_actions": 0,
            }

            # 填充全局画像统计
            if pa_player and pa_seat_id in player.global_player_stats:
                s = player.global_player_stats[pa_seat_id]
                p_data["hands_played"] = s["hands"]
                p_data["vpip_actions"] = s["vpip_count"]
                p_data["pfr_actions"] = s["pfr_count"]

            players_data[str(pa_seat_id)] = p_data

        # 确定可用动作
        available_actions = []
        to_call = engine.current_bet - p.bet_this_street
        if to_call == 0:
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

        return {
            "my_seat_id": seat_id,
            "hole_cards": hole_cards,
            "community_cards": community_cards,
            "pot": engine.pot,
            "to_call": to_call,
            "min_raise": engine.min_raise,
            "max_raise": p.stack + p.bet_this_street,
            "available_actions": available_actions,
            "current_stage": current_stage,
            "total_chips": p.stack + (player.bank if player else 0),
            "my_initial_chips": p.stack + p.bet_this_street,
            "big_blind": self.table.bb,
            "players": players_data,
        }

    def _build_table_state(self, player_id: str) -> Dict[str, Any]:
        """构建 TABLE_STATE payload"""
        player = self.players.get(player_id)
        if player is None:
            return {}

        # 从配置读取止盈止损阈值
        pc = self._get_player_config(player_id)
        stop_loss_bb = 250
        take_profit_bb = 300
        low_chips_bb = 10
        max_chips_bb = 800
        if pc:
            # 可从配置扩展
            pass

        return {
            "my_chips": player.chips_on_table,
            "my_bank": player.bank,
            "is_seated": player.is_seated,
            "is_playing": player.is_playing,
            "hands_played": player.hands_played,
            "total_profit": player.total_profit,
            "current_bb": self.config.big_blind,
            "seat_count": len(self.table.get_seated_players()),
            "active_count": self.table.active_count,
            "stop_loss_bb": stop_loss_bb,
            "take_profit_bb": take_profit_bb,
            "low_chips_bb": low_chips_bb,
            "max_chips_bb": max_chips_bb,
        }

    def _apply_table_action(self, player_id: str, action_payload: Dict[str, Any]) -> None:
        """应用桌位动作"""
        player = self.players.get(player_id)
        if player is None:
            return

        action_type_str = action_payload.get("action_type", "none")
        amount = action_payload.get("amount", 0)

        try:
            action_type = TableActionType(action_type_str)
        except ValueError:
            return

        if action_type == TableActionType.SIT_IN:
            if player.is_seated and not player.is_playing:
                self.table.sit_in(player.seat_id)
                player.is_playing = True
                arena_logger.info(f"[RING] 玩家 {player.name} 坐入 (sit in)")

        elif action_type == TableActionType.SIT_OUT:
            if player.is_playing:
                self.table.sit_out(player.seat_id)
                player.is_playing = False
                # 锁定利润：将超出初始买入的筹码移到银行
                seat = self.table.seats[player.seat_id]
                if seat and seat.chips > 0:
                    lock_amount = seat.chips
                    player.bank += lock_amount
                    player.locked_profit += lock_amount
                    seat.chips = 0
                    player.chips_on_table = 0
                arena_logger.info(f"[RING] 玩家 {player.name} 站起 (sit out)")

        elif action_type == TableActionType.ADD_CHIPS:
            if player.is_seated and player.is_playing:
                add_amount = min(amount, player.bank)
                if add_amount > 0:
                    self.table.add_chips(player.seat_id, add_amount)
                    player.bank -= add_amount
                    player.chips_on_table += add_amount
                    player.add_chips_total += add_amount
                    arena_logger.info(
                        f"[RING] 玩家 {player.name} 补筹 +{add_amount}"
                    )

        elif action_type == TableActionType.LEAVE:
            if player.is_seated:
                seat = self.table.seats[player.seat_id]
                if seat and seat.chips > 0:
                    player.bank += seat.chips
                self.table.remove_player(player.seat_id)
                player.is_seated = False
                player.is_playing = False
                player.chips_on_table = 0
                arena_logger.info(f"[RING] 玩家 {player.name} 离场 (leave)")

        # 发布桌位事件
        self.event_bus.publish(EventType.TABLE_ACTION, {
            "player_id": player_id,
            "action": action_type_str,
            "amount": amount,
        })

    def _check_termination(self) -> bool:
        """检查是否应该终止游戏"""
        active_players = [
            p for p in self.players.values() if p.is_seated
        ]
        if len(active_players) < self.config.min_players_to_start:
            return True
        return False

    def _build_report(
        self, num_hands: int, duration: float, hand_log: List[Dict[str, Any]]
    ) -> RingReport:
        """构建 Ring Game 报告"""
        player_stats = []
        for pid, player in self.players.items():
            pc = self._get_player_config(pid)
            vpip = (player.vpip_count / player.hands_played * 100) if player.hands_played > 0 else 0
            pfr = (player.pfr_count / player.hands_played * 100) if player.hands_played > 0 else 0

            stats = RingPlayerStats(
                name=player.name,
                strategy=pc.hand_strategy if pc else "unknown",
                table_strategy_name=player.table_strategy.strategy_name,
                final_chips=player.chips_on_table,
                final_bank=player.bank,
                total_profit=player.total_profit,
                hands_played=player.hands_played,
                hands_sat_out=player.hands_sat_out,
                vpip=vpip,
                pfr=pfr,
                hands_won=player.hands_won,
                rebuy_count=player.rebuy_count,
                add_chips_total=player.add_chips_total,
                locked_profit=player.locked_profit,
            )
            player_stats.append(stats)

        return RingReport(
            num_hands=num_hands,
            duration_sec=duration,
            player_stats=player_stats,
            hand_log=hand_log,
        )

    # ─── 工具方法 ───

    @staticmethod
    def _count_active(engine: GameEngine) -> int:
        return sum(1 for p in engine.players if p.is_active)

    @staticmethod
    def _count_can_act(engine: GameEngine) -> int:
        return sum(1 for p in engine.players if p.is_active and not p.is_all_in)

    @staticmethod
    def _parse_arena_action(action_str: str) -> ArenaActionType:
        mapping = {
            "FOLD": ArenaActionType.FOLD,
            "CHECK": ArenaActionType.CHECK,
            "CALL": ArenaActionType.CALL,
            "RAISE": ArenaActionType.RAISE,
            "ALL_IN": ArenaActionType.ALL_IN,
        }
        return mapping.get(action_str.upper(), ArenaActionType.FOLD)

    def _get_player_config(self, player_id: str) -> Optional[RingPlayerConfig]:
        """根据 player_id 获取配置"""
        try:
            idx = int(player_id.split("_")[-1])
            if 0 <= idx < len(self.config.players):
                return self.config.players[idx]
        except (ValueError, IndexError):
            pass
        return None

    def _get_initial_total(self, player_id: str) -> int:
        """获取玩家初始总资产"""
        pc = self._get_player_config(player_id)
        return pc.initial_bank if pc else 0

    def _create_hand_strategy(self, strategy_type: str) -> HandStrategy:
        """创建手牌策略"""
        strategy_type = strategy_type.lower()
        strategy = self._create_strategy_instance(strategy_type)
        return StrategyHandAdapter(strategy)

    @staticmethod
    def _create_strategy_instance(strategy_type: str):
        """创建 Strategy 实例"""
        strategy_type = strategy_type.lower()
        if strategy_type == "balanced":
            from src.strategies.strategies.balanced import BalancedStrategy
            return BalancedStrategy(thinking_timeout=2.0)
        elif strategy_type in ("gto", "gto_solver"):
            from src.strategies.strategies.gto_solver import GtoSolverStrategy
            return GtoSolverStrategy()
        elif strategy_type == "exploitative":
            from src.strategies.strategies.exploitative import ExploitativeStrategy
            return ExploitativeStrategy(thinking_timeout=2.0)
        elif strategy_type == "neural":
            from src.strategies.strategies.neural import NeuralStrategy
            return NeuralStrategy(thinking_timeout=2.0)
        elif strategy_type == "checkorfold":
            from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
            return CheckOrFoldStrategy()
        elif strategy_type == "aggressive":
            from src.strategies.strategies.aggressive import AggressiveStrategy
            return AggressiveStrategy(thinking_timeout=2.0)
        elif strategy_type == "icm":
            from src.strategies.strategies.icm import ICMStrategy
            return ICMStrategy(thinking_timeout=2.0)
        else:
            from src.strategies.strategies.range import RangeStrategy
            return RangeStrategy()

    @staticmethod
    def _create_table_strategy(strategy_type: str) -> TableStrategy:
        """创建桌位策略"""
        strategy_type = strategy_type.lower()
        if strategy_type == "conservative":
            return ConservativeTableStrategy()
        elif strategy_type == "aggressive":
            return AggressiveTableStrategy()
        else:
            return DefaultTableStrategy()

    async def shutdown(self) -> None:
        """关闭平台"""
        for task in self.player_tasks:
            if not task.done():
                task.cancel()
        if self.player_tasks:
            await asyncio.gather(*self.player_tasks, return_exceptions=True)

        for channel in self.channels.values():
            channel.close()

        arena_logger.info("[RING] 平台已关闭")
