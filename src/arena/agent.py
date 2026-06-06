import logging
from typing import List, Optional, Tuple
from treys import Card
from src.strategies.game_state import GameState, Player as StrategyPlayer
from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionType as StrategyActionType
from src.arena.game import PlayerState, Street, ActionType as ArenaActionType

arena_logger = logging.getLogger("arena")


class ArenaAgent:
    """策略适配层：连接模拟器与 Strategy 策略"""
    def __init__(self, seat_id: int, strategy: Strategy):
        self.seat_id = seat_id
        self.strategy = strategy
        self.name = f"{strategy.strategy_name.capitalize()}_{seat_id}"
        # 维护场上所有玩家的全局画像统计（在 Arena 模式下模拟历史记忆）
        self.global_player_stats = {} # {seat_id: {hands: 0, vpip: 0, pfr: 0}}
        
    def get_action(self, arena_state: 'GameEngine') -> Tuple[ArenaActionType, int]:
        """根据当前竞技场状态，调用 Strategy 获取动作"""
        # 1. 构造 GameState
        game_state = self._translate_state(arena_state)
        
        # 2. 调用 Strategy 决策 (使用最新的统一接口)
        plan = self.strategy.make_decision(game_state)
        
        # 3. 记录思考日志
        arena_logger.info(f"[THINK] 玩家 {self.name} (座:{self.seat_id}): {plan.reasoning}")
        
        # 4. 解析决策
        to_call = arena_state.current_bet - arena_state.players[self.seat_id].bet_this_street
        action_type, amount = plan.get_action_for_bet(to_call, arena_state.pot)
        
        # 5. 转换为 Arena 内部动作
        arena_action = self._translate_action(action_type)
        
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