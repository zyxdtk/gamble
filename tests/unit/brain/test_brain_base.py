"""
测试 Brain 基类功能
"""
from src.brain.game_state import GameState, Player
from src.brain.brain_base import Brain
from src.brain.action_plan import ActionPlan, ActionType


class MockBrain(Brain):
    strategy_name = "mock"
    
    def make_decision(self, state: GameState) -> ActionPlan:
        """实现决策逻辑"""
        if not state.hole_cards:
            return ActionPlan(ActionType.CHECK, reasoning="Wait for cards")
            
        return ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=50,
            confidence=0.9,
            reasoning="Mock decision"
        )


class TestBrainInit:
    def test_default_thinking_timeout(self):
        brain = MockBrain()
        assert brain.thinking_timeout == 10.0

    def test_custom_thinking_timeout(self):
        brain = MockBrain(thinking_timeout=5.0)
        assert brain.thinking_timeout == 5.0


class TestBrainHandleEvent:
    def test_handle_action_event(self):
        brain = MockBrain()
        data = {"user_id": "player1", "action": "RAISE", "pot_ratio": 0.5}
        
        # 验证是否能处理事件而不报错
        brain.handle_event("action", data)


class TestBrainMakeDecision:
    def test_make_decision_returns_action_plan(self):
        brain = MockBrain()
        
        state = GameState()
        state.hole_cards = ["As", "Kh"]
        state.pot = 30
        state.to_call = 20
        
        plan = brain.make_decision(state)
        
        assert isinstance(plan, ActionPlan)
        assert plan.primary_action == ActionType.RAISE
        assert plan.primary_amount == 50
        assert plan.reasoning == "Mock decision"

    def test_make_decision_with_empty_state(self):
        brain = MockBrain()
        
        state = GameState()
        plan = brain.make_decision(state)
        
        assert plan is not None
        assert plan.primary_action == ActionType.CHECK
        assert "Wait for cards" in plan.reasoning


class TestBrainReset:
    def test_reset_callable(self):
        brain = MockBrain()
        brain.reset()


class TestBrainShutdown:
    def test_shutdown_callable(self):
        brain = MockBrain()
        brain.shutdown()


class TestBrainStrategyName:
    def test_strategy_name_attribute(self):
        brain = MockBrain()
        assert brain.strategy_name == "mock"
