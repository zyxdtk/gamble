"""
tests/bot/test_browser_manager.py

测试 BrowserManager 的纯逻辑部分（不需要浏览器）：
- Table ID 提取与去重
- 策略类型获取
- 配置加载与环境变量覆盖
"""
import os
import pytest
from unittest.mock import patch


class TestExtractTableId:
    """BrowserManager._extract_table_id 的各种 URL 格式测试。"""

    def test_play_table_url(self):
        url = "https://www.casino.org/replaypoker/play/table/16477257"
        from src.bot.browser_manager import BrowserManager
        assert BrowserManager._extract_table_id(url) == "16477257"

    def test_play_table_url_with_querystring(self):
        url = "https://www.casino.org/replaypoker/play/table/16477257?playNow=true"
        from src.bot.browser_manager import BrowserManager
        assert BrowserManager._extract_table_id(url) == "16477257"

    def test_play_table_url_bare_question_mark(self):
        url = "https://www.casino.org/replaypoker/play/table/16477257?"
        from src.bot.browser_manager import BrowserManager
        assert BrowserManager._extract_table_id(url) == "16477257"

    def test_legacy_table_url(self):
        url = "https://www.replaypoker.com/table/99999"
        from src.bot.browser_manager import BrowserManager
        assert BrowserManager._extract_table_id(url) == "99999"

    def test_lobby_url_returns_none(self):
        url = "https://www.casino.org/replaypoker/lobby/rings"
        from src.bot.browser_manager import BrowserManager
        assert BrowserManager._extract_table_id(url) is None

    def test_empty_url_returns_none(self):
        from src.bot.browser_manager import BrowserManager
        assert BrowserManager._extract_table_id("") is None

    def test_about_blank_returns_none(self):
        from src.bot.browser_manager import BrowserManager
        assert BrowserManager._extract_table_id("about:blank") is None

    def test_different_table_ids_are_distinct(self):
        from src.bot.browser_manager import BrowserManager
        id1 = BrowserManager._extract_table_id(
            "https://www.casino.org/replaypoker/play/table/111?playNow=true"
        )
        id2 = BrowserManager._extract_table_id(
            "https://www.casino.org/replaypoker/play/table/222?"
        )
        assert id1 != id2
        assert id1 == "111"
        assert id2 == "222"

    def test_same_table_different_querystring_same_id(self):
        from src.bot.browser_manager import BrowserManager
        url_a = "https://www.casino.org/replaypoker/play/table/16477257?playNow=true"
        url_b = "https://www.casino.org/replaypoker/play/table/16477257?"
        assert BrowserManager._extract_table_id(url_a) == BrowserManager._extract_table_id(url_b)


class TestGetStrategyType:
    """BrowserManager.get_strategy_type 的策略类型测试。"""

    def _make_manager(self, **kwargs):
        from src.bot.browser_manager import BrowserManager
        with patch.object(BrowserManager, 'load_config'):
            m = BrowserManager(**kwargs)
        return m

    def test_apprentice_mode_returns_checkorfold(self):
        m = self._make_manager(apprentice_mode=True)
        assert m.get_strategy_type() == "checkorfold"

    def test_default_returns_gto(self):
        m = self._make_manager()
        m.preferred_strategy = "gto"
        assert m.get_strategy_type() == "gto"

    def test_exploitative_strategy(self):
        m = self._make_manager()
        m.preferred_strategy = "exploitative"
        assert m.get_strategy_type() == "exploitative"

    def test_checkorfold_strategy(self):
        m = self._make_manager()
        m.preferred_strategy = "checkorfold"
        assert m.get_strategy_type() == "checkorfold"

    def test_apprentice_mode_overrides_preferred_strategy(self):
        m = self._make_manager(apprentice_mode=True)
        m.preferred_strategy = "gto"
        assert m.get_strategy_type() == "checkorfold"


class TestStrategyEnvOverride:
    """POKER_STRATEGY 环境变量应覆盖配置文件的策略设置。"""

    def test_env_overrides_config(self, tmp_path):
        cfg = tmp_path / "settings.yaml"
        cfg.write_text("strategy:\n  type: exploitative\ngame:\n  max_tables: 1\n")
        with patch.dict(os.environ, {"POKER_STRATEGY": "gto"}):
            with patch("builtins.open", side_effect=lambda p, *a, **kw: open(str(cfg), *a, **kw) if "settings" in str(p) else open(p, *a, **kw)):
                from src.bot.browser_manager import BrowserManager
                m = BrowserManager()
        assert m.preferred_strategy == "gto"
