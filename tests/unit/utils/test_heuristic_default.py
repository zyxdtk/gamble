"""
heuristic_default / build_default 测试

覆盖 fallback 路径：
- 关键修复：fallback 时 call 必须只在 to_call=0 时，否则 fold（避免盲打送钱）
- diagnostic：fallback 必须打 warning 并带上 hole/street/pot/to_call
- 3 种 fallback 触发原因：策略返回 None / 策略推荐不在 available / payload 缺字段
"""
import logging

import pytest

from src.utils.cli_player import (
    ActionChoice,
    build_default,
    heuristic_default,
)


# ─── heuristic_default 行为 ─────────────────────────────────────────────

class TestHeuristicDefault:
    def test_check_when_available(self):
        """check 可用时优先 check"""
        c = heuristic_default(["check", "call", "raise"], to_call=10)
        assert c.action == "check"
        assert c.source == "fallback"
        assert c.amount == 0

    def test_free_call_when_no_check(self):
        """没 check + 免费 call（to_call=0）→ call"""
        c = heuristic_default(["call", "raise"], to_call=0)
        assert c.action == "call"
        assert c.source == "fallback"
        assert c.amount == 0  # to_call=0 时 amount=0

    def test_paid_call_does_NOT_default_to_call(self):
        """【关键修复】有 check 不可用 + to_call > 0 + 无策略 → fold 而非 call

        旧版会默认 call，导致 J2o 这种弱牌无脑送钱
        """
        c = heuristic_default(["call", "raise"], to_call=10)
        assert c.action == "fold", (
            f"to_call=10 + 无策略时应该 fold，实际 {c.action}"
        )
        assert c.source == "fallback"

    def test_fold_when_only_fold(self):
        c = heuristic_default(["fold"], to_call=10)
        assert c.action == "fold"

    def test_reasoning_includes_context(self):
        """reasoning 必须含 street/pot/to_call/hole，方便 debug"""
        c = heuristic_default(
            ["call", "raise"], to_call=10,
            hole_cards=["Jh", "2c"], pot=100, street="flop",
        )
        assert "Jh" in c.reasoning
        assert "2c" in c.reasoning
        assert "pot=100" in c.reasoning
        assert "to_call=10" in c.reasoning
        assert "flop" in c.reasoning

    def test_action_normalization(self):
        """大写动作也能识别（browser 协议混用）"""
        c = heuristic_default(["CHECK", "CALL", "RAISE"], to_call=0)
        assert c.action == "check"

        c = heuristic_default(["CALL", "RAISE"], to_call=0)
        assert c.action == "call"


# ─── build_default diagnostic ───────────────────────────────────────────

class TestBuildDefaultDiagnostic:
    """build_default 退化时必须打 warning 并带手牌上下文"""

    def _payload(self, **overrides):
        """构造最小可用的 payload"""
        base = {
            "hole_cards": ["Jh", "2c"],
            "community_cards": ["8s", "2h", "Td"],
            "my_seat_id": 0,
            "available_actions": ["call", "raise"],
            "to_call": 5,
            "pot": 50,
            "current_stage": "flop",
        }
        base.update(overrides)
        return base

    def test_missing_hole_cards_logs_warning(self, caplog):
        """无底牌 → fallback + warning"""
        payload = self._payload(hole_cards=[])
        with caplog.at_level(logging.WARNING):
            c = build_default(payload, strategy_name="tag")
        assert c.source == "fallback"
        assert any(
            "[fallback] payload 缺关键字段" in r.message
            for r in caplog.records
        ), f"应有缺字段 warning，实际: {[r.message for r in caplog.records]}"

    def test_missing_seat_logs_warning(self, caplog):
        """无 my_seat_id → fallback + warning"""
        payload = self._payload(my_seat_id=None)
        with caplog.at_level(logging.WARNING):
            c = build_default(payload, strategy_name="tag")
        assert c.source == "fallback"
        assert any("缺关键字段" in r.message for r in caplog.records)

    def test_strategy_unavailable_logs_warning(self, caplog):
        """策略返回 None → fallback + warning 含 hole/street/pot/to_call"""
        payload = self._payload()
        with caplog.at_level(logging.WARNING):
            c = build_default(payload, strategy_name="nonexistent_strategy_xyz")
        assert c.source == "fallback"
        msgs = [r.message for r in caplog.records]
        assert any("[fallback]" in m for m in msgs), f"应打 fallback warning: {msgs}"
        # 关键：warning 必须带手牌上下文
        warning_with_ctx = [m for m in msgs if "Jh" in m and "flop" in m]
        assert warning_with_ctx, (
            f"warning 应含 hole_cards 和 street，实际: {msgs}"
        )

    def test_fallback_reasoning_includes_hand_context(self):
        """fallback ActionChoice 的 reasoning 必须含 hole/street/pot/to_call"""
        payload = self._payload()
        c = build_default(payload, strategy_name="nonexistent_strategy_xyz")
        assert c.source == "fallback"
        assert "Jh" in c.reasoning
        assert "flop" in c.reasoning
        assert "to_call=5" in c.reasoning
        assert "pot=50" in c.reasoning

    def test_j2o_with_to_call_folds_not_calls(self):
        """J2o 极弱牌 + 有跟注 + 无策略 → 必须 fold"""
        payload = self._payload(
            hole_cards=["Jh", "2c"],
            to_call=10,
            available_actions=["call", "raise", "fold"],
        )
        c = build_default(payload, strategy_name="nonexistent_strategy_xyz")
        # 关键：J2o 不会傻 call
        assert c.action != "call" or c.amount == 0, (
            f"J2o + to_call=10 + 无策略不应用 call 送钱，实际: {c}"
        )
