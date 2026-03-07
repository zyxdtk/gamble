from src.engine.brain_base import Brain
from src.engine.action_plan import ActionPlan, ActionType
from src.core.game_state import GameState
from src.engine.utils.board_analyzer import BoardAnalyzer
from src.engine.player_analysis import RangeModel, PlayerManager
from src.engine.utils import EquityCalculator, normalize_hand_string, get_position_code

class RangeBrain(Brain):
    """
    基于范围（Range）的深度决策引擎
    实现 range.md 中定义的状态机与决策树逻辑
    """
    strategy_name = "range"

    def __init__(self, thinking_timeout: float = 2.0):
        super().__init__(thinking_timeout)
        self.board_analyzer = BoardAnalyzer()
        self.equity_calc = EquityCalculator()

    def _get_opponent_tightness(self, state: GameState) -> float:
        """
        计算当前行动对手的范围紧凑度系数。
        - 返回值 > 1.0 表示范围比预期更窄（对手行动强度高）
        - 返回值 < 1.0 表示范围比预期更宽（对手可能在诈唬）
        - 默认返回 1.0
        """
        if state.active_seat is None or state.active_seat not in state.players:
            return 1.0
        opponent = state.players[state.active_seat]
        if not getattr(opponent, 'user_id', None):
            return 1.0

        model = self.player_mgr.get_range_model(opponent.user_id)
        combos = model.get_active_combos_count()

        # 基准：无先验时约 169 个组合，权重可能超出此数
        # 计算紧凑度：组合数越少，紧凑度越高
        # 取初始总权重约 169 作为基准
        initial_total = 169.0
        tightness = initial_total / max(1.0, combos)
        # 限制在合理范围内
        return max(0.3, min(4.0, tightness))

    def create_initial_plan(self, state: GameState) -> ActionPlan:
        if not state.hole_cards:
            return ActionPlan(ActionType.CHECK, reasoning="Wait for cards")

        # 1. 环境分析
        board_texture = self.board_analyzer.analyze(state.community_cards)
        spr = state.total_chips / max(1, state.pot)
        
        # 2. 牌力评估 (EHS 模式)
        hand_info = self.equity_calc.get_hand_strength(state.hole_cards, state.community_cards)
        hs = hand_info["points"] / 8000.0 # 简化 HS
        draws = hand_info.get("draws", {})
        
        # 计算潜力 PP (Positive Potential)
        pp = 0.0
        if draws.get("flush_draw"): pp += 0.35
        if draws.get("oesd"): pp += 0.3
        if draws.get("gutshot"): pp += 0.15
        
        # EHS = HS + (1-HS) * PP
        ehs = hs + (1.0 - hs) * pp
        
        # 3. 对手建模 (根据最近动作更新范围)
        tightness = 1.0
        if state.active_seat is not None and state.active_seat in state.players:
            opponent = state.players[state.active_seat]
            if getattr(opponent, 'user_id', None):
                model = self.player_mgr.get_range_model(opponent.user_id)
                if state.to_call > 0:
                    pot_ratio = state.to_call / max(1, state.pot)
                    model.update_range("raise", pot_ratio)
                # 在更新后计算紧凑度
                tightness = self._get_opponent_tightness(state)

        # 4. 基于对手范围紧凑度计算防守余量 (Safety Margin)
        # tightness > 1.0 (对手范围窄) -> 余量正，需要更强的牌才跟注
        # tightness < 1.0 (对手范围宽) -> 余量负，可以用更弱的牌跟注
        safety_margin = (tightness - 1.0) * 0.1
        # 限制余量在 [-0.1, +0.15] 范围内，避免过于激进或消极
        safety_margin = max(-0.10, min(0.15, safety_margin))

        # 5. 决策逻辑
        
        # 情况 A: 坚果/超强牌 或 强 EHS
        if ehs > 0.75:
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=int(state.pot * 0.75),
                bet_size_hint="pot",
                limit_amount=999999,
                reasoning=f"价值提取: EHS={ehs:.2f}, SPR={spr:.1f}, 对手紧凑度={tightness:.2f}"
            )
            
        # 情况 B: 强听牌 + 深筹码 -> 半诈唬 (Semi-bluff)
        if pp >= 0.3 and spr > 8:
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=int(state.pot * 0.8),
                secondary_action=ActionType.CHECK if state.to_call == 0 else ActionType.CALL,
                secondary_probability=0.2, # 20% 概率陷阱式过牌/跟注平衡
                bet_size_hint="pot",
                reasoning=f"半诈唬: 强听牌(PP={pp:.2f}) + 深筹码(SPR={spr:.1f})"
            )

        # 情况 C: 中等成牌面对超额下注 -> FOLD
        if hs > 0.4 and state.to_call > state.pot * (1.5 + safety_margin * 5):
             return ActionPlan(
                primary_action=ActionType.FOLD,
                limit_amount=int(state.pot * (1.5 + safety_margin * 5)),
                reasoning=f"防守性弃牌: 面对超池下注({state.to_call}/{state.pot}), 对手紧凑度={tightness:.2f}"
            )

        # 情况 D: 底池赔率跟注 (加入紧凑度修正)
        pot_odds = state.to_call / (state.pot + state.to_call) if (state.pot + state.to_call) > 0 else 0
        # 对手范围越紧 (tightness > 1.0), 我们的跟注阈值越高
        call_threshold = pot_odds + 0.1 + safety_margin
        if ehs > call_threshold:
            return ActionPlan(
                primary_action=ActionType.CALL if state.to_call > 0 else ActionType.CHECK,
                limit_amount=int(state.pot * 0.5),
                reasoning=f"赔率跟注: EHS={ehs:.2f} > 阈值={call_threshold:.2f} (紧凑度修正={safety_margin:+.2f})"
            )

        return ActionPlan(
            primary_action=ActionType.FOLD if state.to_call > 0 else ActionType.CHECK,
            reasoning=f"弱牌/阈值过高: EHS={ehs:.2f}, 跟注阈值={call_threshold:.2f}"
        )

    def update_plan(self, state: GameState) -> ActionPlan:
        return self.create_initial_plan(state)

    def deep_think(self, state: GameState) -> ActionPlan:
        return self.create_initial_plan(state)
