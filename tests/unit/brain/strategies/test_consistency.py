import pytest
from src.brain.strategies import (
    CheckOrFoldBrain,
    BalancedBrain,
    ExploitativeBrain,
    RangeBrain,
)

class TestBrainConsistency:
    def test_all_brains_return_required_fields(self, preflop_state):
        from src.brain.action_plan import ActionPlan
        brains = [
            CheckOrFoldBrain(),
            BalancedBrain(),
            ExploitativeBrain(),
            RangeBrain(),
        ]
        
        for brain in brains:
            plan = brain.make_decision(preflop_state)
            assert isinstance(plan, ActionPlan)
            assert plan.primary_action is not None
            assert brain.strategy_name is not None

    def test_brain_names_are_unique(self):
        brains = [
            CheckOrFoldBrain(),
            BalancedBrain(),
            ExploitativeBrain(),
            RangeBrain(),
        ]
        
        names = [b.strategy_name for b in brains]
        assert len(names) == len(set(names)), f"Brain names should be unique: {names}"

    def test_all_brains_handle_empty_state(self, empty_state):
        brains = [
            CheckOrFoldBrain(),
            BalancedBrain(),
            ExploitativeBrain(),
        ]
        
        for brain in brains:
            plan = brain.make_decision(empty_state)
            assert plan is not None
            assert plan.primary_action is not None
