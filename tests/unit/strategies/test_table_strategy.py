"""
桌位策略测试

覆盖 DefaultTableStrategy 在各场景下的决策：
- 正常打牌
- 短码补筹
- 筹码过厚 sit out
- 【关键】已坐下 + sit_out + 0 筹码 → ADD_CHIPS（不再死循环 sit_in）
- 已坐下 + sit_out + 筹码充足 → SIT_IN
- 止损/止盈离场
"""
from src.strategies.table_strategy import (
    DefaultTableStrategy,
    TableActionType,
    TableState,
)


# ── 关键场景：sit_out + 0 筹码死循环修复 ──────────────────────────────────

class TestSeatedSitOutNoChips:
    """覆盖"已坐下 + sit_out + 0/低筹码"场景的修复"""

    def test_seated_sitout_zero_chips_triggers_add_chips(self):
        """坐下了 + sit_out + 0 筹码 → 必须返回 ADD_CHIPS，不能 SIT_IN"""
        state = TableState(
            my_chips=0,
            is_seated=True,
            is_playing=False,  # sit_out
            current_bb=10,
            low_chips_bb=10,
        )
        action = DefaultTableStrategy().decide(state)
        assert action.action_type == TableActionType.ADD_CHIPS, (
            f"sit_out + 0 筹码应该补筹，实际返回 {action.action_type} "
            f"(reasoning={action.reasoning})"
        )
        # 0 筹码场景：至少补到 low_chips_bb * BB = 10 * 10 = 100
        assert action.amount == 100
        assert "sit_out" in action.reasoning
        assert "0" in action.reasoning or "不足" in action.reasoning

    def test_seated_sitout_low_chips_triggers_add_chips(self):
        """坐下了 + sit_out + 5 BB（< 10 BB 阈值）→ ADD_CHIPS"""
        state = TableState(
            my_chips=50,  # 5 BB
            is_seated=True,
            is_playing=False,
            current_bb=10,
            low_chips_bb=10,
        )
        action = DefaultTableStrategy().decide(state)
        assert action.action_type == TableActionType.ADD_CHIPS
        # 补到 100 BB：100*10 - 50 = 950
        assert action.amount == 950

    def test_seated_sitout_above_threshold_triggers_sit_in(self):
        """坐下了 + sit_out + 20 BB（> 10 BB 阈值）→ SIT_IN（筹码够不需要补）"""
        state = TableState(
            my_chips=200,  # 20 BB
            is_seated=True,
            is_playing=False,
            current_bb=10,
            low_chips_bb=10,
        )
        action = DefaultTableStrategy().decide(state)
        assert action.action_type == TableActionType.SIT_IN
        assert action.amount == 0

    def test_seated_playing_low_chips_triggers_add_chips(self):
        """坐下了 + 正在打 + 短码 → ADD_CHIPS（原有逻辑未受影响）"""
        state = TableState(
            my_chips=80,  # 8 BB
            is_seated=True,
            is_playing=True,
            current_bb=10,
            low_chips_bb=10,
        )
        action = DefaultTableStrategy().decide(state)
        assert action.action_type == TableActionType.ADD_CHIPS
        # 补到 100 BB：100*10 - 80 = 920
        assert action.amount == 920

    def test_seated_playing_above_threshold_no_action(self):
        """坐下了 + 正在打 + 50 BB（正常码）→ 无需操作"""
        state = TableState(
            my_chips=500,
            is_seated=True,
            is_playing=True,
            current_bb=10,
            low_chips_bb=10,
            max_chips_bb=800,
        )
        action = DefaultTableStrategy().decide(state)
        assert action.action_type == TableActionType.NONE


# ── 边界场景 ──────────────────────────────────────────────────────────────

class TestTableStrategyEdgeCases:
    def test_stop_loss_triggers_leave(self):
        state = TableState(
            my_chips=0,
            is_seated=True,
            is_playing=False,
            current_bb=10,
            total_profit=-2500,  # -250 BB
            stop_loss_bb=250,
        )
        action = DefaultTableStrategy().decide(state)
        assert action.action_type == TableActionType.LEAVE
        # 优先级：止损 > 补筹 > sit_in

    def test_take_profit_triggers_leave(self):
        state = TableState(
            my_chips=3000,
            is_seated=True,
            is_playing=True,
            current_bb=10,
            total_profit=3000,  # +300 BB
            take_profit_bb=300,
        )
        action = DefaultTableStrategy().decide(state)
        assert action.action_type == TableActionType.LEAVE

    def test_chips_too_thick_triggers_sit_out(self):
        """正在打 + 900 BB（> max_chips_bb 800）→ SIT_OUT 锁利"""
        state = TableState(
            my_chips=9000,
            is_seated=True,
            is_playing=True,
            current_bb=10,
            low_chips_bb=10,
            max_chips_bb=800,
        )
        action = DefaultTableStrategy().decide(state)
        assert action.action_type == TableActionType.SIT_OUT
