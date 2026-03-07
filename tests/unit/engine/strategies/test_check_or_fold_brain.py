import pytest
from src.engine.strategies import CheckOrFoldBrain
from src.engine.action_plan import ActionType

class TestCheckOrFoldBrain:
    def test_returns_active_flag(self, preflop_state):
        brain = CheckOrFoldBrain()
        decision = brain.make_decision(preflop_state)
        
        assert decision["strategy_name"] == "checkorfold"

    def test_returns_decision_structure(self, preflop_state):
        brain = CheckOrFoldBrain()
        decision = brain.make_decision(preflop_state)
        
        assert "action" in decision
        assert "plan" in decision

        assert decision is not None

    def test_prefers_check_over_fold(self, preflop_state):
        brain = CheckOrFoldBrain()
        preflop_state.to_call = 0
        
        decision = brain.make_decision(preflop_state)
        
        if decision.get("decision"):
            action = decision["decision"].get("action")
            assert action in ["CHECK", "WAIT"]

    def test_handles_large_bet(self, preflop_state):
        brain = CheckOrFoldBrain()
        preflop_state.to_call = 1000
        
        decision = brain.make_decision(preflop_state)
        assert decision is not None

    def test_create_initial_plan(self, preflop_state):
        brain = CheckOrFoldBrain()
        plan = brain.create_initial_plan(preflop_state)
        
        assert plan is not None
        assert plan.primary_action in [ActionType.CHECK, ActionType.FOLD, ActionType.CALL]
