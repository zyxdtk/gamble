import pytest
from src.brain.strategies import CheckOrFoldBrain
from src.brain.action_plan import ActionType

class TestCheckOrFoldBrain:
    def test_returns_correct_strategy(self, preflop_state):
        brain = CheckOrFoldBrain()
        assert brain.strategy_name == "check_or_fold"

    def test_returns_plan_structure(self, preflop_state):
        from src.brain.action_plan import ActionPlan
        brain = CheckOrFoldBrain()
        plan = brain.make_decision(preflop_state)
        
        assert isinstance(plan, ActionPlan)
        assert plan.primary_action is not None

    def test_prefers_check_over_fold(self, preflop_state):
        brain = CheckOrFoldBrain()
        preflop_state.to_call = 0
        
        plan = brain.make_decision(preflop_state)
        # CheckOrFold 在 to_call=0 时应优先 CHECK
        assert plan.primary_action == ActionType.CHECK

    def test_folds_to_large_bet(self, preflop_state):
        brain = CheckOrFoldBrain()
        preflop_state.to_call = 1000
        
        plan = brain.make_decision(preflop_state)
        assert plan.primary_action == ActionType.FOLD
