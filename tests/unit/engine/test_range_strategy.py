"""
tests/unit/engine/test_range_strategy.py

测试 RangeBrain 策略的关键决策场景。

重点测试：
1. 翻牌前强牌（AK, QQ+）不应 FOLD
2. 翻牌前中等牌的处理
3. 翻牌后的决策逻辑
"""
import pytest

from src.engine.strategies.range import RangeBrain
from src.engine.action_plan import ActionType
from src.core.game_state import GameState


class TestPreflopDecisions:
    """测试翻牌前决策"""
    
    def _create_state(self, hole_cards: list[str], to_call: int = 2, pot: int = 3,
                      total_chips: int = 250) -> GameState:
        """创建测试用的 GameState"""
        state = GameState()
        state.hole_cards = hole_cards
        state.community_cards = []
        state.to_call = to_call
        state.pot = pot
        state.total_chips = total_chips
        state.min_raise = 4
        state.available_actions = ["fold", "call", "raise"]
        state.players = {}
        return state
    
    def test_ak_offsuit_should_not_fold(self):
        """AK 不同花是顶级强牌，不应 FOLD"""
        brain = RangeBrain()
        state = self._create_state(["Ad", "Ks"], to_call=2, pot=3)
        
        plan = brain.create_initial_plan(state)
        
        # AK 不应该 FOLD
        assert plan.primary_action != ActionType.FOLD, \
            f"AK 不应该 FOLD，但返回了 {plan.primary_action}"
        # 应该是 RAISE 或 CALL
        assert plan.primary_action in [ActionType.RAISE, ActionType.CALL], \
            f"AK 应该 RAISE 或 CALL，但返回了 {plan.primary_action}"
        print(f"AK 决策: {plan.primary_action}, reasoning: {plan.reasoning}")
    
    def test_ak_suited_should_raise(self):
        """AK 同花应该更激进"""
        brain = RangeBrain()
        state = self._create_state(["Ad", "Kd"], to_call=2, pot=3)
        
        plan = brain.create_initial_plan(state)
        
        # AKs 应该 RAISE
        assert plan.primary_action == ActionType.RAISE, \
            f"AKs 应该 RAISE，但返回了 {plan.primary_action}"
        print(f"AKs 决策: {plan.primary_action}, reasoning: {plan.reasoning}")
    
    def test_pocket_aces_should_raise(self):
        """AA 应该 RAISE"""
        brain = RangeBrain()
        state = self._create_state(["Ad", "Ac"], to_call=2, pot=3)
        
        plan = brain.create_initial_plan(state)
        
        assert plan.primary_action == ActionType.RAISE, \
            f"AA 应该 RAISE，但返回了 {plan.primary_action}"
        print(f"AA 决策: {plan.primary_action}, reasoning: {plan.reasoning}")
    
    def test_pocket_kings_should_raise(self):
        """KK 应该 RAISE"""
        brain = RangeBrain()
        state = self._create_state(["Kd", "Kc"], to_call=2, pot=3)
        
        plan = brain.create_initial_plan(state)
        
        assert plan.primary_action == ActionType.RAISE, \
            f"KK 应该 RAISE，但返回了 {plan.primary_action}"
        print(f"KK 决策: {plan.primary_action}, reasoning: {plan.reasoning}")
    
    def test_pocket_queens_should_raise(self):
        """QQ 应该 RAISE"""
        brain = RangeBrain()
        state = self._create_state(["Qd", "Qc"], to_call=2, pot=3)
        
        plan = brain.create_initial_plan(state)
        
        assert plan.primary_action in [ActionType.RAISE, ActionType.CALL], \
            f"QQ 应该 RAISE 或 CALL，但返回了 {plan.primary_action}"
        print(f"QQ 决策: {plan.primary_action}, reasoning: {plan.reasoning}")
    
    def test_medium_pair_should_call(self):
        """中等对子（TT-88）应该 CALL"""
        brain = RangeBrain()
        state = self._create_state(["Td", "Tc"], to_call=2, pot=3)
        
        plan = brain.create_initial_plan(state)
        
        assert plan.primary_action != ActionType.FOLD, \
            f"TT 不应该 FOLD，但返回了 {plan.primary_action}"
        print(f"TT 决策: {plan.primary_action}, reasoning: {plan.reasoning}")
    
    def test_weak_hand_can_fold(self):
        """弱牌可以 FOLD"""
        brain = RangeBrain()
        state = self._create_state(["7d", "2c"], to_call=2, pot=3)
        
        plan = brain.create_initial_plan(state)
        
        # 72o 可以 FOLD
        assert plan.primary_action in [ActionType.FOLD, ActionType.CHECK], \
            f"72o 应该 FOLD/CHECK，但返回了 {plan.primary_action}"
        print(f"72o 决策: {plan.primary_action}, reasoning: {plan.reasoning}")
    
    def test_big_slick_facing_big_raise(self):
        """AK 面对大加注仍不应 FOLD"""
        brain = RangeBrain()
        # 面对大加注（to_call = 20，pot = 30）
        state = self._create_state(["Ad", "Ks"], to_call=20, pot=30)
        
        plan = brain.create_initial_plan(state)
        
        # 即使面对大加注，AK 也不应该 FOLD
        assert plan.primary_action != ActionType.FOLD, \
            f"AK 面对大加注不应该 FOLD，但返回了 {plan.primary_action}"
        print(f"AK 面对大加注决策: {plan.primary_action}, reasoning: {plan.reasoning}")


class TestPreflopEquityEstimation:
    """测试翻牌前胜率估算"""
    
    def test_preflop_equity_ak_offsuit(self):
        """AK 不同花的翻牌前胜率"""
        from src.engine.utils.equity import EquityCalculator
        
        calc = EquityCalculator()
        equity = calc._estimate_preflop_equity(["Ad", "Ks"])
        
        # AKo 胜率应该在 60-70% 之间
        assert 0.60 <= equity <= 0.70, \
            f"AKo 胜率应该在 60-70%，实际为 {equity:.2%}"
        print(f"AKo 胜率: {equity:.2%}")
    
    def test_preflop_equity_ak_suited(self):
        """AK 同花的翻牌前胜率"""
        from src.engine.utils.equity import EquityCalculator
        
        calc = EquityCalculator()
        equity = calc._estimate_preflop_equity(["Ad", "Kd"])
        
        # AKs 胜率应该在 65-70% 之间
        assert 0.65 <= equity <= 0.70, \
            f"AKs 胜率应该在 65-70%，实际为 {equity:.2%}"
        print(f"AKs 胜率: {equity:.2%}")
    
    def test_preflop_equity_pocket_aces(self):
        """AA 的翻牌前胜率"""
        from src.engine.utils.equity import EquityCalculator
        
        calc = EquityCalculator()
        equity = calc._estimate_preflop_equity(["Ad", "Ac"])
        
        # AA 胜率应该在 80-90% 之间
        assert 0.80 <= equity <= 0.90, \
            f"AA 胜率应该在 80-90%，实际为 {equity:.2%}"
        print(f"AA 胜率: {equity:.2%}")
    
    def test_preflop_equity_weak_hand(self):
        """弱牌的翻牌前胜率"""
        from src.engine.utils.equity import EquityCalculator
        
        calc = EquityCalculator()
        equity = calc._estimate_preflop_equity(["7d", "2c"])
        
        # 72o 胜率应该低于 40%
        assert equity < 0.40, \
            f"72o 胜率应该低于 40%，实际为 {equity:.2%}"
        print(f"72o 胜率: {equity:.2%}")


class TestPostflopDecisions:
    """测试翻牌后决策"""
    
    def _create_state_with_board(self, hole_cards: list[str],
                                 community_cards: list[str],
                                 to_call: int = 2, pot: int = 10) -> GameState:
        """创建带公共牌的测试状态"""
        state = GameState()
        state.hole_cards = hole_cards
        state.community_cards = community_cards
        state.to_call = to_call
        state.pot = pot
        state.total_chips = 250
        state.min_raise = 4
        state.available_actions = ["fold", "call", "raise"]
        state.players = {}
        return state
    
    def test_top_pair_should_not_fold(self):
        """顶对不应该 FOLD"""
        brain = RangeBrain()
        # 翻牌：A-K-7，手牌 AK，顶两对
        state = self._create_state_with_board(
            ["Ad", "Ks"],
            ["Ac", "Kd", "7h"],
            to_call=5, pot=20
        )
        
        plan = brain.create_initial_plan(state)
        
        assert plan.primary_action != ActionType.FOLD, \
            f"顶两对不应该 FOLD，但返回了 {plan.primary_action}"
        print(f"顶两对决策: {plan.primary_action}, reasoning: {plan.reasoning}")
    
    def test_weak_hand_on_scary_board_can_fold(self):
        """在惊悚牌面弱牌可以 FOLD"""
        brain = RangeBrain()
        # 翻牌：A-K-Q，手牌 72
        state = self._create_state_with_board(
            ["7d", "2c"],
            ["Ac", "Kd", "Qh"],
            to_call=10, pot=20
        )
        
        plan = brain.create_initial_plan(state)
        
        assert plan.primary_action in [ActionType.FOLD, ActionType.CHECK], \
            f"弱牌在惊悚牌面应该 FOLD/CHECK，但返回了 {plan.primary_action}"
        print(f"弱牌在惊悚牌面决策: {plan.primary_action}, reasoning: {plan.reasoning}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
