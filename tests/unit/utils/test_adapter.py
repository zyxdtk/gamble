"""
适配器测试：adapt_strategy_to_browser_action

覆盖 src/utils/cli_player.py 的策略→浏览器动作映射：
1. 关键 bug 修复：策略想 raise/bet，但浏览器只 allin → 改为 allin (chips)
2. 关键 bug 修复：策略想 call，但 chips < to_call → 改为 allin
3. 关键 bug 修复：策略想 check，但 to_call > 0 → 改为 call
4. raise/bet 直接可用时，amount 必须 <= chips
5. fold / check 透传
6. 各种 edge cases
"""
import logging

from src.utils.cli_player import (
    ActionChoice,
    adapt_strategy_to_browser_action,
)


# ─── 关键 bug 修复 ─────────────────────────────────────────────────────

class TestRaiseToAllinMapping:
    """用户报告的 bug：策略推荐 raise，但浏览器只 allin 可用"""

    def test_raise_to_allin_when_only_allin(self, caplog):
        """策略想 raise to 200，浏览器只 allin → 改为 allin (chips)"""
        suggestion = ActionChoice("raise", 200, "raise (200)", "策略推荐 raise", "strategy:gto")
        with caplog.at_level(logging.INFO):
            adapted = adapt_strategy_to_browser_action(
                suggestion, ["allin"],
                chips=195, to_call=0, pot=1110,
            )
        assert adapted.action == "allin", f"应改为 allin，实际 {adapted.action}"
        assert adapted.amount == 195, f"amount 应为 chips，实际 {adapted.amount}"
        assert "raise" in adapted.reasoning
        assert "allin" in adapted.reasoning

    def test_bet_to_allin_when_only_allin(self, caplog):
        """策略想 bet 100，浏览器只 allin → 改为 allin (chips)"""
        suggestion = ActionChoice("bet", 100, "bet (100)", "策略 bet", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["allin"],
            chips=80, to_call=0, pot=50,
        )
        assert adapted.action == "allin"
        assert adapted.amount == 80

    def test_raise_to_allin_logs_clarity(self, caplog):
        """必须打 info 日志（含 hole/street/pot/to_call）方便 debug"""
        suggestion = ActionChoice("raise", 200, "raise (200)", "策略", "strategy:gto")
        with caplog.at_level(logging.INFO):
            adapt_strategy_to_browser_action(
                suggestion, ["allin"],
                chips=195, to_call=0, pot=1110,
            )
        msgs = [r.getMessage() for r in caplog.records]
        assert any(
            "[adapter]" in m and "allin" in m and "raise" in m
            for m in msgs
        ), f"应打 adapter info 日志，实际: {msgs}"


class TestCallInsufficientChips:
    """策略想 call，但 chips < to_call → 改 allin"""

    def test_call_with_insufficient_chips_to_allin(self, caplog):
        suggestion = ActionChoice("call", 50, "call (50)", "call 50", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["allin", "fold"],
            chips=30, to_call=50, pot=100,
        )
        assert adapted.action == "allin", f"应改为 allin，实际 {adapted.action}"
        assert adapted.amount == 30, f"amount 应为 chips=30，实际 {adapted.amount}"

    def test_call_with_sufficient_chips_passes_through(self):
        """筹码够 call 时透传"""
        suggestion = ActionChoice("call", 50, "call (50)", "call", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["call", "fold"],
            chips=100, to_call=50, pot=100,
        )
        assert adapted.action == "call"
        assert adapted.amount == 50


# ─── 其他适配场景 ─────────────────────────────────────────────────────

class TestCheckMustPay:
    """策略想 free-check，但必须付钱（to_call > 0）"""

    def test_check_to_call_when_only_call(self, caplog):
        """to_call > 0，浏览器只 call → 改 call"""
        suggestion = ActionChoice("check", 0, "check", "策略 check", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["call", "fold"],
            chips=100, to_call=10, pot=20,
        )
        assert adapted.action == "call", f"应改为 call，实际 {adapted.action}"
        assert adapted.amount == 10

    def test_check_to_call_when_only_allin(self, caplog):
        """to_call > 0 + chips 不够，浏览器只 allin → 改 allin"""
        suggestion = ActionChoice("check", 0, "check", "策略 check", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["allin", "fold"],
            chips=5, to_call=10, pot=20,
        )
        assert adapted.action == "allin"
        assert adapted.amount == 5

    def test_check_to_fold_when_no_other_action(self, caplog):
        """浏览器只有 fold，没有 call/allin → 改 fold"""
        suggestion = ActionChoice("check", 0, "check", "策略 check", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["fold"],
            chips=100, to_call=10, pot=20,
        )
        assert adapted.action == "fold"

    def test_check_passes_through_when_available(self):
        """浏览器有 check 时直接透传"""
        suggestion = ActionChoice("check", 0, "check", "free check", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["check", "raise"],
            chips=100, to_call=0, pot=50,
        )
        assert adapted.action == "check"


class TestRaiseDirectPath:
    """raise/bet 直接可用时的 amount 修正"""

    def test_raise_passes_through_when_in_avail(self):
        suggestion = ActionChoice("raise", 50, "raise (50)", "策略", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["raise", "call", "fold"],
            chips=100, to_call=10, pot=20,
        )
        assert adapted.action == "raise"
        assert adapted.amount == 50

    def test_raise_amount_clipped_to_chips(self, caplog):
        """策略想 raise 200 但只有 100 筹码 → 修正为 raise 100"""
        suggestion = ActionChoice("raise", 200, "raise (200)", "策略", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["raise", "call", "fold"],
            chips=100, to_call=10, pot=20,
        )
        assert adapted.action == "raise"
        assert adapted.amount == 100, f"amount 应被修正为 chips=100，实际 {adapted.amount}"

    def test_raise_to_call_when_only_call(self, caplog):
        """raise 不可用但 call 可用 → 降级 call"""
        suggestion = ActionChoice("raise", 200, "raise (200)", "策略", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["call", "fold"],
            chips=100, to_call=50, pot=100,
        )
        assert adapted.action == "call"
        assert adapted.amount == 50

    def test_raise_to_check_when_only_check(self, caplog):
        """raise 不可用 + to_call=0 + 只 check → 降级 check"""
        suggestion = ActionChoice("raise", 200, "raise (200)", "策略", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["check", "fold"],
            chips=100, to_call=0, pot=50,
        )
        assert adapted.action == "check"


class TestFoldAndPassthrough:
    """fold / 不可识别动作透传"""

    def test_fold_passes_through(self):
        suggestion = ActionChoice("fold", 0, "fold", "fold", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["fold", "call", "raise"],
            chips=100, to_call=10, pot=20,
        )
        assert adapted.action == "fold"

    def test_unknown_action_passes_through(self):
        suggestion = ActionChoice("weird_action", 0, "weird", "策略", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["fold", "call"],
            chips=100, to_call=10, pot=20,
        )
        # 未知动作透传（不破坏原 ActionChoice）
        assert adapted.action == "weird_action"


# ─── 真实场景回归测试 ─────────────────────────────────────────────────

class TestUserReportedScenario:
    """用户报告的精确场景"""

    def test_user_log_message_scenario(self, caplog):
        """用户日志: 策略推荐 'raise' 不在可用动作 {'allin'}"""
        suggestion = ActionChoice("raise", 0, "raise", "策略推荐 raise", "strategy:gto")
        with caplog.at_level(logging.INFO):
            adapted = adapt_strategy_to_browser_action(
                suggestion, ["allin"],
                chips=195, to_call=0, pot=1110,
            )
        # 关键：bot 不再 fold，而是 allin
        assert adapted.action == "allin"
        assert adapted.amount == 195
        assert adapted.action in {"allin"}, f"必须能执行，实际 {adapted.action}"
        # reasoning 应保留原 raise 意图 + 标记 allin 适配
        assert "raise" in adapted.reasoning
        assert "allin" in adapted.reasoning

    def test_allin_passthrough_when_in_avail(self):
        """策略直接返回 allin + 浏览器支持 → 透传"""
        suggestion = ActionChoice("allin", 195, "allin (195)", "策略", "strategy:gto")
        adapted = adapt_strategy_to_browser_action(
            suggestion, ["allin", "fold"],
            chips=195, to_call=0, pot=1110,
        )
        assert adapted.action == "allin"
        assert adapted.amount == 195


# ─── DOM 端到端集成测试 ───────────────────────────────────────────────

class TestIntegration:
    """模拟完整 build_default 调用（不是 unit test）"""

    def test_build_default_with_only_allin_available(self, caplog):
        """end-to-end: 策略 raise + 浏览器只 allin → bot allin"""
        from src.utils.cli_player import build_default

        payload = {
            "hole_cards": ["4c", "9d"],
            "community_cards": ["8s", "2h", "Td"],
            "my_seat_id": 4,
            "available_actions": ["allin"],
            "to_call": 0,
            "pot": 1110,
            "current_stage": "turn",
            "my_chips": 195,
        }
        with caplog.at_level(logging.INFO):
            choice = build_default(payload, strategy_name="nonexistent_strategy_xyz")
        # 关键：必须返回 allin（不是 fold）
        assert choice.action in {"allin", "fold", "check", "call"}, (
            f"适配后必须是浏览器可执行动作，实际 {choice.action}"
        )
        # 适配器日志应出现
        msgs = [r.getMessage() for r in caplog.records]
        assert any("[adapter]" in m or "[fallback]" in m for m in msgs)
