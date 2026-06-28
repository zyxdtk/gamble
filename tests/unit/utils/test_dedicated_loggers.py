"""
专用 logger 文件分流测试

覆盖 src.utils.logger 中 DEDICATED_LOGGERS 的配置：
- ws_raw → logs/ws_raw.log
- dom    → logs/dom.log

要求：
1. 专用 logger 必须挂上 RotatingFileHandler
2. 同一 logger 多次 get_logger 不会重复添加 handler
3. 日志消息同时写入专用文件 + app.log（propagate 不被破坏）
4. 非专用 logger 不挂专用 handler
"""
import logging
import logging.handlers
import os

import pytest

from src.utils.logger import (
    DEDICATED_LOGGERS,
    LOG_DIR,
    _attach_dedicated_handler,
    dom_logger,
    get_logger,
    ws_raw_logger,
)


@pytest.fixture(autouse=True)
def _reset_logger_handlers():
    """每个测试前后清空 logger 状态，避免上一个测试的 handler 干扰"""
    # 清理前
    for name in list(DEDICATED_LOGGERS.keys()):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            lg.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
    yield
    # 清理后
    for name in list(DEDICATED_LOGGERS.keys()):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            lg.removeHandler(h)


class TestDedicatedLoggerMapping:
    def test_ws_raw_maps_to_ws_raw_log(self):
        assert DEDICATED_LOGGERS["ws_raw"] == "ws_raw.log"

    def test_dom_maps_to_dom_log(self):
        assert DEDICATED_LOGGERS["dom"] == "dom.log"


class TestDedicatedHandlerAttachment:
    def test_ws_raw_gets_rotating_file_handler(self):
        get_logger("ws_raw")
        lg = logging.getLogger("ws_raw")
        assert any(
            isinstance(h, logging.handlers.RotatingFileHandler)
            and os.path.basename(h.baseFilename) == "ws_raw.log"
            for h in lg.handlers
        ), "ws_raw 缺少指向 ws_raw.log 的 RotatingFileHandler"

    def test_dom_gets_rotating_file_handler(self):
        get_logger("dom")
        lg = logging.getLogger("dom")
        assert any(
            isinstance(h, logging.handlers.RotatingFileHandler)
            and os.path.basename(h.baseFilename) == "dom.log"
            for h in lg.handlers
        ), "dom 缺少指向 dom.log 的 RotatingFileHandler"

    def test_non_dedicated_logger_gets_no_file_handler(self):
        """非专用 logger 不应挂上专用 file handler"""
        get_logger("bot")
        bot_lg = logging.getLogger("bot")
        for h in bot_lg.handlers:
            assert not isinstance(h, logging.handlers.RotatingFileHandler), (
                "bot logger 不应挂专用 file handler"
            )


class TestNoDuplicateHandler:
    def test_repeated_get_logger_does_not_duplicate(self):
        """多次 get_logger("ws_raw") 只挂 1 个专用 handler"""
        for _ in range(5):
            get_logger("ws_raw")
        lg = logging.getLogger("ws_raw")
        dedicated = [
            h for h in lg.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
            and getattr(h, "_dedicated_for", None) == "ws_raw.log"
        ]
        assert len(dedicated) == 1, f"挂了 {len(dedicated)} 个专用 handler"

    def test_explicit_attach_does_not_duplicate(self):
        """手动调 _attach_dedicated_handler 多次也不重复"""
        _attach_dedicated_handler("ws_raw")
        _attach_dedicated_handler("ws_raw")
        _attach_dedicated_handler("ws_raw")
        lg = logging.getLogger("ws_raw")
        dedicated = [
            h for h in lg.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
            and getattr(h, "_dedicated_for", None) == "ws_raw.log"
        ]
        assert len(dedicated) == 1


class TestDualWritePropagation:
    """专用 logger 必须 propagate 到根 logger（让消息同时进 app.log）"""

    def test_ws_raw_propagates_to_root(self):
        lg = logging.getLogger("ws_raw")
        # propagate 默认 True
        assert lg.propagate is True, (
            "ws_raw 必须 propagate=True，否则不会写入 app.log"
        )

    def test_dom_propagates_to_root(self):
        lg = logging.getLogger("dom")
        assert lg.propagate is True


class TestHandlerHasDedicatedMarker:
    """专用 handler 必须带 _dedicated_for 标记（去重 + 识别用）"""

    def test_marker_set_on_attach(self):
        _attach_dedicated_handler("ws_raw")
        lg = logging.getLogger("ws_raw")
        dedicated = [
            h for h in lg.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(dedicated) == 1
        assert dedicated[0]._dedicated_for == "ws_raw.log"


class TestDedicatedLoggerWritesToFile:
    """端到端：发消息 → 文件里有内容（不依赖 pytest 的 capsys）"""

    def test_ws_raw_message_lands_in_file(self, tmp_path, monkeypatch):
        """用临时目录验证 ws_raw 写到文件"""
        import src.utils.logger as logger_mod

        # 替换 LOG_DIR 为 tmp_path
        monkeypatch.setattr(logger_mod, "LOG_DIR", tmp_path)
        # 清空之前可能存在的 handler
        for name in ("ws_raw", "dom"):
            lg = logging.getLogger(name)
            for h in list(lg.handlers):
                lg.removeHandler(h)

        _attach_dedicated_handler("ws_raw")
        logger_mod.ws_raw_logger.info("[RAW FRAME] end-to-end test")

        # 强制 flush
        for h in logging.getLogger("ws_raw").handlers:
            h.flush()

        log_file = tmp_path / "ws_raw.log"
        assert log_file.exists(), f"未创建 {log_file}"
        content = log_file.read_text(encoding="utf-8")
        assert "[RAW FRAME] end-to-end test" in content
        assert "ws_raw" in content  # formatter 里带 logger name

    def test_dom_message_lands_in_file(self, tmp_path, monkeypatch):
        import src.utils.logger as logger_mod

        monkeypatch.setattr(logger_mod, "LOG_DIR", tmp_path)
        for name in ("ws_raw", "dom"):
            lg = logging.getLogger(name)
            for h in list(lg.handlers):
                lg.removeHandler(h)

        _attach_dedicated_handler("dom")
        logger_mod.dom_logger.info("[DOM] pot=100, actions=call,raise")

        for h in logging.getLogger("dom").handlers:
            h.flush()

        log_file = tmp_path / "dom.log"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "[DOM] pot=100, actions=call,raise" in content
        assert "dom" in content
