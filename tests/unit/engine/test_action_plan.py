"""
测试 ActionPlan 数据结构
"""
from unittest.mock import patch
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
        assert plan.secondary_action is None
        assert plan.secondary_probability == 0.0
        assert plan.limit_amount == 0
        assert plan.fallback_action == ActionType.FOLD
        assert plan.confidence == 1.0
        assert plan.reasoning == "默认免费看牌"


class TestActionPlanDecision:
    def test_get_action_basic_primary(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=100,
            limit_amount=200
        )
        
        # 正常范围内，返回 primary
        action, amount = plan.get_action_for_bet(50, 100)
        assert action == ActionType.RAISE
        assert amount == 100

    def test_get_action_above_limit_triggers_fallback(self):
        plan = ActionPlan(
            primary_action=ActionType.CALL,
            limit_amount=100,
            fallback_action=ActionType.FOLD
        )
        
        # 超过限制，返回 fallback
        action, amount = plan.get_action_for_bet(150, 100)
        assert action == ActionType.FOLD
        assert amount == 0

    def test_get_action_mixed_strategy_primary_win(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=100,
            secondary_action=ActionType.CALL,
            secondary_amount=30,
            secondary_probability=0.3,
            limit_amount=100
        )
        
        # 模拟模拟随机数 > 0.3，应返回 primary
        with patch('random.random', return_value=0.5):
            action, amount = plan.get_action_for_bet(30, 100)
            assert action == ActionType.RAISE
            assert amount == 100

    def test_get_action_mixed_strategy_secondary_win(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=100,
            secondary_action=ActionType.CALL,
            secondary_amount=30,
            secondary_probability=0.3,
            limit_amount=100
        )
        
        # 模拟随机数 < 0.3，应返回 secondary
        with patch('random.random', return_value=0.1):
            action, amount = plan.get_action_for_bet(30, 100)
            assert action == ActionType.CALL
            # 注意：在 CALL 场景下 get_action_for_bet 会根据 to_call 返回
            # 但如果 secondary_amount 显式指定，逻辑应保证一致。
            # 当前逻辑返回 chosen_amount (secondary_amount)
            assert amount == 30

    def test_fallback_on_forced_call_without_plan(self):
        plan = ActionPlan(
            primary_action=ActionType.CHECK,
            fallback_action=ActionType.FOLD
        )
        
        # 如果计划是 CHECK 但有下注且没进跟注区间（此处已精简），应 FOLD
        action, amount = plan.get_action_for_bet(10, 100)
        assert action == ActionType.FOLD


class TestActionPlanToDict:
    def test_to_dict_conversion(self):
        plan = ActionPlan(
            primary_action=ActionType.RAISE,
            primary_amount=500,
            secondary_action=ActionType.CALL,
            secondary_probability=0.2,
            bet_size_hint="pot",
            reasoning="Strong"
        )
        
        d = plan.to_dict()
        assert d["primary_action"] == "RAISE"
        assert d["secondary_action"] == "CALL"
        assert d["secondary_probability"] == 0.2
        assert d["bet_size_hint"] == "pot"
        assert d["reasoning"] == "Strong"
