import pytest
from src.engine.strategies import (
    CheckOrFoldBrain,
    GTOBrain,
    ExploitativeBrain,
    RangeBrain,
)

class TestBrainConsistency:
    def test_all_brains_return_required_fields(self, preflop_state):
        brains = [
            CheckOrFoldBrain(),
            GTOBrain(),
            ExploitativeBrain(),
            RangeBrain(),
        ]
        
        for brain in brains:
            decision = brain.make_decision(preflop_state)
            assert "strategy_name" in decision
            assert "status" in decision
            if decision["status"] == "DECIDING":
                assert "action" in decision
                assert "amount" in decision

    def test_brain_names_are_unique(self, preflop_state):
        brains = [
            CheckOrFoldBrain(),
            GTOBrain(),
            ExploitativeBrain(),
            RangeBrain(),
        ]
        
        names = [b.make_decision(preflop_state)["strategy_name"] for b in brains]
        assert len(names) == len(set(names)), "Brain names should be unique"

    def test_all_brains_handle_empty_state(self, empty_state):
        brains = [
            CheckOrFoldBrain(),
            GTOBrain(),
            ExploitativeBrain(),
        ]
        
        for brain in brains:
            decision = brain.make_decision(empty_state)
            assert decision is not None
            assert "strategy_name" in decision
            assert "status" in decision
            assert decision["status"] == "WAITING"
            assert "action" not in decision
