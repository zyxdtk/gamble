"""
诊断工具测试

覆盖 src/utils/diagnostics.py：
- log_exception_with_traceback 必须含 traceback.format_exc() 堆栈 + 业务上下文
- safe_call 异常时返回 default + 打 warning+traceback
- log_exception_with_traceback 支持自定义 level
"""
import logging

from src.utils.diagnostics import (
    log_exception_with_traceback,
    safe_call,
)


class TestLogExceptionWithTraceback:
    def test_contains_traceback(self, caplog):
        """日志必须含 traceback（不只是 str(exc)）"""
        try:
            raise ValueError("boom")
        except ValueError as e:
            with caplog.at_level(logging.WARNING):
                log_exception_with_traceback(
                    logging.getLogger("test"), e,
                    "[test] error",
                )

        all_text = "\n".join(r.getMessage() for r in caplog.records)
        assert "Traceback" in all_text
        assert "ValueError" in all_text
        assert "boom" in all_text
        assert "[test] error" in all_text

    def test_includes_context(self, caplog):
        """业务上下文必须出现在日志里"""
        try:
            raise RuntimeError("explode")
        except RuntimeError as e:
            with caplog.at_level(logging.WARNING):
                log_exception_with_traceback(
                    logging.getLogger("test"), e,
                    "[test] with ctx",
                    hand=["Jh", "2c"], street="flop", to_call=10,
                )

        all_text = "\n".join(r.getMessage() for r in caplog.records)
        assert "hand=['Jh', '2c']" in all_text
        assert "street='flop'" in all_text
        assert "to_call=10" in all_text

    def test_custom_level(self, caplog):
        """支持自定义 level（ERROR/DEBUG）"""
        try:
            raise ValueError("test")
        except ValueError as e:
            with caplog.at_level(logging.DEBUG):
                log_exception_with_traceback(
                    logging.getLogger("test"), e,
                    "[test] debug msg",
                    level=logging.DEBUG,
                )

        assert any(
            r.levelno == logging.DEBUG for r in caplog.records
        ), "必须按指定 level 记录"


class TestSafeCall:
    def test_returns_value_when_no_error(self):
        """正常情况直接返回结果"""
        result = safe_call(lambda: 42, default=None)
        assert result == 42

    def test_returns_default_on_error(self, caplog):
        """异常时返回 default + 打 warning"""
        def bad_func():
            raise ValueError("intentional")

        with caplog.at_level(logging.WARNING):
            result = safe_call(
                bad_func,
                default=-1,
                logger=logging.getLogger("test"),
                op_name="bad_func",
                extra_ctx="abc",
            )

        assert result == -1
        msgs = [r.getMessage() for r in caplog.records]
        assert any("[safe_call] bad_func 异常" in m for m in msgs)
        assert any("Traceback" in m for m in msgs)
        assert any("extra_ctx='abc'" in m for m in msgs)

    def test_passes_args_and_kwargs(self, caplog):
        """args 和 context 都能正确传递"""
        def divide(a, b):
            return a / b

        with caplog.at_level(logging.WARNING):
            result = safe_call(
                divide, 10, 0,
                default="divzero",
                logger=logging.getLogger("test"),
                op_name="divide",
                call="10/0",
            )

        assert result == "divzero"
        msgs = [r.getMessage() for r in caplog.records]
        assert any("call='10/0'" in m for m in msgs)

    def test_none_logger_uses_root(self, caplog):
        """logger=None 时用 root logger"""
        def bad():
            raise RuntimeError("oops")

        with caplog.at_level(logging.WARNING):
            safe_call(bad, default=None, op_name="bad")

        assert any(
            "bad" in r.getMessage() for r in caplog.records
        )

    def test_custom_log_level(self, caplog):
        """支持自定义 log_level（DEBUG 异常）"""
        def bad():
            raise ValueError("x")

        with caplog.at_level(logging.DEBUG):
            safe_call(
                bad, default=None,
                logger=logging.getLogger("test"),
                op_name="bad",
                log_level=logging.DEBUG,
            )

        assert any(r.levelno == logging.DEBUG for r in caplog.records)


class TestIntegration:
    """端到端：诊断工具被实际使用"""

    def test_getattr_failure_includes_context(self, caplog):
        """模拟常见场景：访问不存在的属性 + 业务上下文"""
        class State:
            pass

        state = State()  # 没有 hole_cards

        try:
            _ = state.hole_cards[0]
        except (AttributeError, TypeError) as e:
            with caplog.at_level(logging.WARNING):
                log_exception_with_traceback(
                    logging.getLogger("integration"), e,
                    "[get_state] 读取 hole_cards 失败",
                    state_id=id(state),
                )

        msg = "\n".join(r.getMessage() for r in caplog.records)
        assert "读取 hole_cards 失败" in msg
        assert f"state_id={id(state)}" in msg
        assert "Traceback" in msg
