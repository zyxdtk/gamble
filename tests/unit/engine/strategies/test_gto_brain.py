import pytest
from src.engine.strategies import GTOBrain

class TestGTOBrain:
    def test_returns_correct_strategy_name(self, preflop_state):
        brain = GTOBrain()
        decision = brain.make_decision(preflop_state)
        
        assert decision["strategy_name"] == "gto"

    def test_includes_status_and_action(self, preflop_state):
        brain = GTOBrain()
        decision = brain.make_decision(preflop_state)
        
        assert "status" in decision
        assert "action" in decision
        assert decision["status"] == "DECIDING"

    def test_postflop_decision(self, postflop_state):
        brain = GTOBrain()
        decision = brain.make_decision(postflop_state)
        
        assert decision["strategy_name"] == "gto"
        assert decision["status"] == "DECIDING"
        assert "action" in decision

    def test_handles_empty_state_gracefully(self, empty_state):
        brain = GTOBrain()
        decision = brain.make_decision(empty_state)
        
        # 应该触发 WAIT 逻辑，此时不应有 action
        assert decision["status"] == "WAITING"
        assert "action" not in decision
        assert decision["strategy_name"] == "gto"

    def test_decision_has_valid_action(self, preflop_state):
        brain = GTOBrain()
        decision = brain.make_decision(preflop_state)
        
        valid_actions = ["CHECK", "CALL", "RAISE", "FOLD", "ALL_IN", "WAIT"]
        assert decision["action"] in valid_actions

    def test_strong_hand_raises(self, strong_hand_state):
        brain = GTOBrain()
        decision = brain.make_decision(strong_hand_state)
        
        assert decision["action"] in ["RAISE", "CALL", "ALL_IN"]

    def test_create_initial_plan(self, preflop_state):
        brain = GTOBrain()
        plan = brain.create_initial_plan(preflop_state)
        
        assert plan is not None
        assert plan.confidence >= 0

    def test_update_plan(self, preflop_state):
        brain = GTOBrain()
        brain.receive_table_update(preflop_state)
        
        preflop_state.pot = 50
        preflop_state.to_call = 30
        
        plan = brain.update_plan(preflop_state)
        assert plan is not None
