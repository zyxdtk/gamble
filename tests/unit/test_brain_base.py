"""
测试 Brain 基类功能
"""
from src.core.game_state import GameState, Player
from src.engine.brain_base import Brain
from src.engine.action_plan import ActionPlan, ActionType


class MockBrain(Brain):
    strategy_name = "mock"
    
    def create_initial_plan(self, state: GameState) -> ActionPlan:
        return ActionPlan(
            primary_action=ActionType.CHECK,
            confidence=0.5,
            reasoning="Mock initial plan"
        )
    
    def update_plan(self, state: GameState) -> ActionPlan:
        return self.current_plan or self.create_initial_plan(state)
    
    def deep_think(self, state: GameState) -> ActionPlan:
        return ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=50,
            confidence=0.9,
            reasoning="Mock deep think"
        )


class TestBrainInit:
    def test_default_thinking_timeout(self):
        brain = MockBrain()
        assert brain.thinking_timeout == 2.0

    def test_custom_thinking_timeout(self):
        brain = MockBrain(thinking_timeout=5.0)
        assert brain.thinking_timeout == 5.0

    def test_initial_plan_is_none(self):
        brain = MockBrain()
        assert brain.current_plan is None


class TestBrainReceiveUpdate:
    def test_receive_table_update(self):
        brain = MockBrain()
        
        state = GameState()
        state.hole_cards = ["As", "Kh"]
        state.pot = 30
        state.to_call = 20
        state.my_seat_id = 1
        state.current_dealer_seat = 5
        state.players = {i: Player(seat_id=i) for i in range(1, 7)}
        
        brain.receive_table_update(state)
        
        assert brain.current_plan is not None
        assert brain.current_plan.reasoning == "Mock initial plan"


class TestBrainMakeDecision:
    def test_make_decision_returns_dict(self):
        brain = MockBrain()
        
        state = GameState()
        state.hole_cards = ["As", "Kh"]
        state.pot = 30
        state.to_call = 20
        state.my_seat_id = 1
        state.current_dealer_seat = 5
        state.players = {i: Player(seat_id=i) for i in range(1, 7)}
        
        decision = brain.make_decision(state)
        
        assert isinstance(decision, dict)
        assert "strategy_name" in decision
        assert "is_passive" in decision
        assert "plan" in decision

    def test_make_decision_with_empty_state(self):
        brain = MockBrain()
        
        state = GameState()
        decision = brain.make_decision(state)
        
        assert decision is not None
        assert decision["strategy_name"] == "mock"


class TestBrainReset:
    def test_reset_clears_plan(self):
        brain = MockBrain()
        
        state = GameState()
        state.hole_cards = ["As", "Kh"]
        brain.receive_table_update(state)
        
        assert brain.current_plan is not None
        
        brain.reset()
        
        assert brain.current_plan is None


class TestBrainShutdown:
    def test_shutdown_no_error(self):
        brain = MockBrain()
        brain.shutdown()


class TestBrainStrategyName:
    def test_strategy_name_attribute(self):
        brain = MockBrain()
        assert brain.strategy_name == "mock"
