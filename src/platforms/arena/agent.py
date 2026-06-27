import logging
from typing import Any, Dict, List, Optional, Tuple
from treys import Card
from src.core.pilot_decider import PilotDecider
from src.strategies.game_state import GameState, Player as StrategyPlayer
from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionType as StrategyActionType
from src.platforms.arena.game import PlayerState, Street, ActionType as ArenaActionType
from src.utils.cli_player import PilotMode

arena_logger = logging.getLogger("arena")


class ArenaAgent:
    """策略适配层：连接模拟器与 Strategy 策略"""
    def __init__(self, seat_id: int, strategy: Strategy, player_id: str = "",
                 pilot_mode: PilotMode = PilotMode.AUTO):
        self.seat_id = seat_id
        self.strategy = strategy
        self.player_id = player_id
        self.name = f"{strategy.strategy_name.capitalize()}_{seat_id}"
        self.is_human = pilot_mode != PilotMode.AUTO
        self.pilot_mode = pilot_mode
        # 维护场上所有玩家的全局画像统计（在 Arena 模式下模拟历史记忆）
        # 索引方式: seat_id (ring game) 或 player_id (MTT)
        self.global_player_stats = {} # {seat_id: {hands: 0, vpip: 0, pfr: 0}}

        # PilotDecider：统一 AI/人类决策编排
        self._pilot_decider: Optional[PilotDecider] = None
        if pilot_mode != PilotMode.AUTO:
            self._pilot_decider = PilotDecider(
                strategy=strategy,
                pilot_mode=pilot_mode,
            )

    async def get_action(self, arena_state: 'GameEngine') -> Tuple[ArenaActionType, int]:
        """根据当前竞技场状态，调用 Strategy 获取动作"""
        # 如果有 PilotDecider（非 AUTO 模式），走统一决策流程
        if self._pilot_decider:
            payload = self._game_state_to_payload(arena_state)
            choice = await self._pilot_decider.decide_hand(
                payload, prompt_prefix="tourney",
                context=f"seat={self.seat_id} pot={arena_state.pot}",
            )
            arena_action = self._choice_to_arena_action(choice)
            amount = choice.amount
            arena_logger.info(
                f"[PILOT] 玩家 {self.name} (座:{self.seat_id}): "
                f"{arena_action.value} {amount} (来源={choice.source})"
            )
            return arena_action, amount

        # AUTO 模式：纯 AI 决策
        game_state = self._translate_state(arena_state)
        plan = self.strategy.make_decision(game_state)
        arena_logger.info(f"[THINK] 玩家 {self.name} (座:{self.seat_id}): {plan.reasoning}")
        to_call = arena_state.current_bet - arena_state.players[self.seat_id].bet_this_street
        action_type, amount = plan.get_action_for_bet(to_call, arena_state.pot)
        arena_action = self._translate_action(action_type)

        # 策略的 primary_amount 语义统一为"加注增量"（额外加多少），
        # GameEngine 期望"总下注额"（本街累计下注总额）。
        # 转换：total_bet = bet_this_street + to_call + raise_increment
        if arena_action == ArenaActionType.RAISE and amount > 0:
            p = arena_state.players[self.seat_id]
            min_required = p.bet_this_street + to_call + arena_state.min_raise
            # 始终按加注增量转换
            total_bet = p.bet_this_street + to_call + amount
            # 保底：不能低于最小加注额
            amount = max(total_bet, min_required)

        return arena_action, amount

    def observe_action(self, seat_id: int, action: ArenaActionType, amount: int, pot: int):
        """观测场上其他玩家的动作，通过 handle_event 分发"""
        action_str = "check"
        if action == ArenaActionType.FOLD: action_str = "fold"
        elif action == ArenaActionType.CALL: action_str = "call"
        elif action == ArenaActionType.RAISE: action_str = "raise"
        elif action == ArenaActionType.ALL_IN: action_str = "raise"
        
        data = {
            "user_id": f"player_{seat_id}",
            "action": action_str,
            "pot_ratio": amount / max(1, pot)
        }
        self.strategy.handle_event("action", data)

    def observe_showdown(self, seat_id: int, hand_cards: List[int], street: str):
        """观测摊牌，通过 handle_event 分发"""
        from src.strategies.utils import normalize_hand_string
        hand_str = normalize_hand_string([Card.int_to_str(c) for c in hand_cards])
        
        data = {
            "user_id": f"player_{seat_id}",
            "hand_str": hand_str,
            "street": street.lower()
        }
        self.strategy.handle_event("showdown", data)

    def update_global_stats(self, seat_id: int, is_vpip: bool, is_pfr: bool):
        """每一手结束，更新全局统计数据"""
        user_id = f"player_{seat_id}"
        self.strategy.player_mgr.record_hand_played(user_id, is_vpip, is_pfr)
        
        # 更新本地缓存，用于填充 GameState
        if seat_id not in self.global_player_stats:
            self.global_player_stats[seat_id] = {"hands": 0, "vpip_count": 0, "pfr_count": 0}
        
        stats = self.global_player_stats[seat_id]
        stats["hands"] += 1
        if is_vpip: stats["vpip_count"] += 1
        if is_pfr: stats["pfr_count"] += 1

    def _translate_state(self, arena: 'GameEngine') -> GameState:
        """从 Arena 内部状态同步到 GameState 模型"""
        p_arena = arena.players[self.seat_id]
        
        gs = GameState()
        gs.my_seat_id = self.seat_id
        gs.hole_cards = [Card.int_to_str(c) for c in p_arena.hole_cards]
        gs.community_cards = [Card.int_to_str(c) for c in arena.community_cards]
        gs.pot = arena.pot
        gs.to_call = arena.current_bet - p_arena.bet_this_street
        gs.min_raise = arena.min_raise
        gs.max_raise = p_arena.stack + p_arena.bet_this_street
        gs.big_blind = arena.big_blind
        
        # 同步所有玩家信息
        for i, pa in enumerate(arena.players):
            user_id = f"player_{i}"
            sp = StrategyPlayer(
                seat_id=pa.seat_id,
                user_id=user_id,
                name=pa.name,
                chips=pa.stack,
                is_active=pa.is_active,
                status="active" if pa.is_active else "folded",
                bet=pa.total_investment
            )
            if pa.is_all_in:
                sp.status = "all_in"
            
            # 使用本地缓存的全局统计数据填充
            if i in self.global_player_stats:
                s = self.global_player_stats[i]
                sp.hands_played = s["hands"]
                sp.vpip_actions = s["vpip_count"]
                sp.pfr_actions = s["pfr_count"]
            else:
                sp.hands_played = 0
            
            gs.players[pa.seat_id] = sp
            
        return gs

    def _translate_action(self, strategy_action: StrategyActionType) -> ArenaActionType:
        mapping = {
            StrategyActionType.FOLD: ArenaActionType.FOLD,
            StrategyActionType.CHECK: ArenaActionType.CHECK,
            StrategyActionType.CALL: ArenaActionType.CALL,
            StrategyActionType.RAISE: ArenaActionType.RAISE,
            StrategyActionType.ALL_IN: ArenaActionType.ALL_IN,
        }
        return mapping.get(strategy_action, ArenaActionType.FOLD)

    def _game_state_to_payload(self, arena: 'GameEngine') -> Dict[str, Any]:
        """从 GameEngine 构建显示 payload（统一 schema，供 PilotDecider 使用）"""
        game_state = self._translate_state(arena)

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
        current_stage = stage_map.get(arena.current_street, "preflop")

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
            "my_chips": game_state.players[game_state.my_seat_id].chips if game_state.my_seat_id in game_state.players else 0,
        }

    @staticmethod
    def _choice_to_arena_action(choice) -> ArenaActionType:
        """将 ActionChoice 转换为 ArenaActionType"""
        _MAP = {
            "fold": ArenaActionType.FOLD,
            "check": ArenaActionType.CHECK,
            "call": ArenaActionType.CALL,
            "raise": ArenaActionType.RAISE,
            "bet": ArenaActionType.RAISE,
            "allin": ArenaActionType.ALL_IN,
        }
        return _MAP.get(choice.action, ArenaActionType.FOLD)