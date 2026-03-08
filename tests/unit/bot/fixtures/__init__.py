"""
tests/unit/bot/fixtures/__init__.py

测试辅助函数：使用真实 DOM 进行测试。
"""
from pathlib import Path
from bs4 import BeautifulSoup
from unittest.mock import AsyncMock, MagicMock

FIXTURE_DIR = Path(__file__).parent


def load_html_fixture(filename: str):
    """加载 HTML 快照文件，返回 BeautifulSoup 对象。"""
    path = FIXTURE_DIR / filename
    with open(path, encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser")


def make_mock_page_from_html(html_path: str):
    """从 HTML 文件创建一个模拟的 Playwright Page 对象。"""
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")

    page = MagicMock()
    page.url = "https://www.casino.org/replaypoker/play/table/12345"

    def mock_locator(selector):
        """模拟 locator。"""
        elements = soup.select(selector)

        loc = AsyncMock()
        loc.count = AsyncMock(return_value=len(elements))
        loc.is_visible = AsyncMock(return_value=len(elements) > 0)
        loc.first = loc
        loc.nth = lambda i: loc if i < len(elements) else AsyncMock(count=AsyncMock(return_value=0))
        loc.locator = lambda s: mock_locator(s)

        if elements:
            loc.text_content = AsyncMock(return_value=elements[0].get_text().strip())
            loc.get_attribute = AsyncMock(side_effect=lambda name: elements[0].get(name))

        return loc

    page.locator = mock_locator
    page.get_by_role = MagicMock(return_value=mock_locator("button"))

    return page


def get_fixture_names():
    """获取所有可用的 fixture 文件名。"""
    return [f.name for f in FIXTURE_DIR.glob("*.html")]
