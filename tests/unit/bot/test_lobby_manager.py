"""
tests/bot/test_lobby_manager.py

测试 LobbyManager 的URL构造逻辑（无浏览器依赖）。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.lobby_manager import LobbyManager


def make_lobby(url="https://www.casino.org/replaypoker/lobby/rings"):
    page = MagicMock()
    page.url = url
    return LobbyManager(page)


class TestGetBestTableUrl:

    @pytest.mark.asyncio
    async def test_prefers_seats_green_over_yellow(self):
        """有 seats-green 时，应优先选 seats-green（空位最多）的桌。"""
        lobby = make_lobby()

        # Mock seats-green 桌的 link
        green_link = AsyncMock()
        green_link.get_attribute = AsyncMock(return_value="/replaypoker/play/table/11111")
        green_rows = AsyncMock()
        green_rows.count = AsyncMock(return_value=1)
        green_rows.first.locator = MagicMock(return_value=MagicMock(
            first=MagicMock(**{"get_attribute": AsyncMock(return_value="/replaypoker/play/table/11111")})
        ))

        yellow_rows = AsyncMock()
        yellow_rows.count = AsyncMock(return_value=1)

        def locator_side_effect(sel):
            if "seats-green" in sel:
                return green_rows
            if "seats-yellow" in sel:
                return yellow_rows
            mock = AsyncMock()
            mock.first.get_attribute = AsyncMock(return_value=None)
            return mock

        lobby.page.locator = MagicMock(side_effect=locator_side_effect)
        lobby.page.wait_for_selector = AsyncMock()

        url = await lobby.get_best_table_url()
        assert url is not None
        assert "11111" in url
        assert url.startswith("https://www.casino.org")

    @pytest.mark.asyncio
    async def test_url_normalization_adds_domain(self):
        """相对路径 href 应被补全为完整 URL。"""
        lobby = make_lobby()

        link_mock = MagicMock()
        link_mock.get_attribute = AsyncMock(return_value="/replaypoker/play/table/22222")

        rows_mock = AsyncMock()
        rows_mock.count = AsyncMock(return_value=1)
        rows_mock.first.locator = MagicMock(return_value=MagicMock(
            first=link_mock
        ))

        def locator_side_effect(sel):
            if "seats-green" in sel:
                return rows_mock
            m = AsyncMock()
            m.count = AsyncMock(return_value=0)
            return m

        lobby.page.locator = MagicMock(side_effect=locator_side_effect)
        lobby.page.wait_for_selector = AsyncMock()

        url = await lobby.get_best_table_url()
        assert url == "https://www.casino.org/replaypoker/play/table/22222"

    @pytest.mark.asyncio
    async def test_navigates_to_lobby_if_not_on_lobby_page(self):
        """当前不在大厅页面时，应先导航到大厅。"""
        lobby = make_lobby(url="https://www.casino.org/replaypoker/play/table/99999")
        lobby.navigate_to_lobby = AsyncMock()

        # 让 wait_for_selector 抛出超时，快速结束
        lobby.page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))

        await lobby.get_best_table_url()
        lobby.navigate_to_lobby.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        """无法找到任何桌时返回 None，不抛出异常。"""
        lobby = make_lobby()
        lobby.page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))
        result = await lobby.get_best_table_url()
        assert result is None


class TestOpenTable:

    @pytest.mark.asyncio
    async def test_uses_quick_play_link(self):
        """优先点击 quick_play 链接（方案 B）。"""
        lobby = make_lobby()
        url = "https://www.casino.org/replaypoker/play/table/33333"

        quick_link = AsyncMock()
        quick_link.count = AsyncMock(return_value=1)
        quick_link.click = AsyncMock()
        quick_link.first = quick_link

        lobby.page.locator = MagicMock(return_value=quick_link)

        result = await lobby.open_table(url)

        assert result is True
        quick_link.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_goto_when_no_quick_play(self):
        """quick_play 链接不存在时，直接 goto URL（方案 A）。"""
        lobby = make_lobby()
        url = "https://www.casino.org/replaypoker/play/table/44444"

        no_link = AsyncMock()
        no_link.count = AsyncMock(return_value=0)
        no_link.first = no_link

        lobby.page.locator = MagicMock(return_value=no_link)
        lobby.page.goto = AsyncMock()

        result = await lobby.open_table(url)

        assert result is True
        lobby.page.goto.assert_called_once_with(url, timeout=20000)

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        """出现异常时返回 False，不抛出。"""
        lobby = make_lobby()
        lobby.page.locator = MagicMock(side_effect=Exception("playwright error"))

        result = await lobby.open_table("https://www.casino.org/replaypoker/play/table/55555")
        assert result is False
