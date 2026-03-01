"""
测试 ActionPlan 数据结构
"""
from src.engine.action_plan import ActionPlan, ActionType


class TestActionType:
    def test_action_type_values(self):
        assert ActionType.FOLD.value == "FOLD"
        assert ActionType.CHECK.value == "CHECK"
        assert ActionType.CALL.value == "CALL"
        assert ActionType.RAISE.value == "RAISE"
        assert ActionType.ALL_IN.value == "ALL_IN"


class TestActionPlanDefaults:
    def test_default_values(self):
        plan = ActionPlan()
        
        assert plan.primary_action == ActionType.CHECK
        assert plan.primary_amount == 0
        assert plan.fallback_action == ActionType.FOLD
        assert plan.fallback_amount == 0
        assert plan.call_range_min == 0
        assert plan.call_range_max == 999999999
        assert plan.raise_range_min == 0
        assert plan.raise_range_max == 999999999
        assert plan.fold_threshold == 999999999
        assert plan.confidence == 0.5
        assert plan.reasoning == ""

    def test_custom_values(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=150,
            fallback_action=ActionType.CALL,
            fallback_amount=50,
            call_range_min=0,
            call_range_max=100,
            raise_range_min=0,
            raise_range_max=50,
            fold_threshold=200,
            confidence=0.8,
            reasoning="Strong hand"
        )
        
        assert plan.primary_action == ActionType.RAISE
        assert plan.primary_amount == 150
        assert plan.fallback_action == ActionType.CALL
        assert plan.confidence == 0.8
        assert plan.reasoning == "Strong hand"


class TestActionPlanGetAction:
    def test_get_action_for_zero_bet(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=100
        )
        
        action, amount = plan.get_action_for_bet(0, 100)
        assert action == ActionType.RAISE
        assert amount == 100

    def test_get_action_within_call_range(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=100,
            call_range_min=0,
            call_range_max=50
        )
        
        action, amount = plan.get_action_for_bet(30, 100)
        assert action == ActionType.CALL
        assert amount == 30

    def test_get_action_above_fold_threshold(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=100,
            fold_threshold=200
        )
        
        action, amount = plan.get_action_for_bet(300, 100)
        assert action == ActionType.FOLD
        assert amount == 0

    def test_get_action_fallback_when_above_raise_max(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=200,
            fallback_action=ActionType.CALL,
            fallback_amount=50,
            raise_range_min=0,
            raise_range_max=50
        )
        
        action, amount = plan.get_action_for_bet(80, 200)
        assert action == ActionType.CALL


class TestActionPlanEdgeCases:
    def test_exact_call_range_max(self):
        plan = ActionPlan(
            call_range_min=0,
            call_range_max=50
        )
        
        action, amount = plan.get_action_for_bet(50, 100)
        assert action == ActionType.CALL

    def test_above_fold_threshold(self):
        plan = ActionPlan(
            fold_threshold=200
        )
        
        action, amount = plan.get_action_for_bet(201, 100)
        assert action == ActionType.FOLD

    def test_just_below_fold_threshold(self):
        plan = ActionPlan(
            primary_action=ActionType.CALL,
            fold_threshold=200
        )
        
        action, amount = plan.get_action_for_bet(199, 100)
        assert action == ActionType.CALL

    def test_zero_pot(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=50
        )
        
        action, amount = plan.get_action_for_bet(0, 0)
        assert action == ActionType.RAISE


class TestActionPlanToDict:
    def test_to_dict_returns_correct_structure(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=100,
            confidence=0.8,
            reasoning="Test"
        )
        
        result = plan.to_dict()
        
        assert result["primary_action"] == "RAISE"
        assert result["primary_amount"] == 100
        assert result["confidence"] == 0.8
        assert result["reasoning"] == "Test"
        assert "call_range" in result
        assert "raise_range" in result
