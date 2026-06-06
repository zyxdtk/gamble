import pytest
from src.brain.strategies import BalancedBrain
from src.brain.action_plan import ActionType, ActionPlan

class TestBalancedBrain:
    def test_returns_correct_strategy_name(self, preflop_state):
        brain = BalancedBrain()
        assert brain.strategy_name == "balanced"

    def test_make_decision_returns_action_plan(self, preflop_state):
        brain = BalancedBrain()
        plan = brain.make_decision(preflop_state)
        
        assert isinstance(plan, ActionPlan)
        assert plan.primary_action is not None

    def test_postflop_decision(self, postflop_state):
        brain = BalancedBrain()
        plan = brain.make_decision(postflop_state)
        
        assert isinstance(plan, ActionPlan)
        assert plan.primary_action is not None

    def test_handles_empty_state_gracefully(self, empty_state):
        brain = BalancedBrain()
        plan = brain.make_decision(empty_state)
        
        # 对于空状态，BalancedBrain 的 _get_balanced_plan 返回 "等待发牌" 的 CHECK
        assert plan.primary_action == ActionType.CHECK
        assert "等待发牌" in plan.reasoning

    def test_decision_has_valid_action(self, preflop_state):
        brain = BalancedBrain()
        plan = brain.make_decision(preflop_state)
        
        assert isinstance(plan.primary_action, ActionType)

    def test_strong_hand_raises(self, strong_hand_state):
        brain = BalancedBrain()
        plan = brain.make_decision(strong_hand_state)
        
        # 强牌应该加注
        assert plan.primary_action == ActionType.RAISE
