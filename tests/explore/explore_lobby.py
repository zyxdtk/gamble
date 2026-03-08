"""
tests/explore/explore_lobby.py

探索大厅页面 DOM 结构。

使用方法:
    python tests/explore/explore_lobby.py
"""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

USER_DATA_DIR = "./data/browser_data"
OUTPUT_DIR = Path(__file__).parent / "data"


async def main():
    print("=" * 60)
    print("大厅 DOM 探索工具")
    print("=" * 60)

    async with async_playwright() as p:
        os.makedirs(USER_DATA_DIR, exist_ok=True)

        print("\n启动浏览器...")
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()

        print("导航到大厅...")
        await page.goto("https://www.replaypoker.com/lobby", wait_until="domcontentloaded")
        await asyncio.sleep(5)

        print(f"当前 URL: {page.url}")

        # 保存截图和 HTML
        OUTPUT_DIR.mkdir(exist_ok=True)
        screenshot_path = OUTPUT_DIR / "lobby_screenshot.png"
        html_path = OUTPUT_DIR / "lobby.html"

        await page.screenshot(path=str(screenshot_path))
        html = await page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"\n✓ 截图: {screenshot_path}")
        print(f"✓ HTML: {html_path}")

        # 探索元素
        print("\n探索大厅元素...")

        # 桌子链接
        table_links = await page.locator("a[href*='/table/']").all()
        print(f"  桌子链接: {len(table_links)} 个")

        # 过滤按钮
        for sel in ["button", "[class*='filter']", "[class*='Filter']"]:
            elements = await page.locator(sel).all()
            if elements:
                print(f"  {sel}: {len(elements)} 个")

        print("\n按 Enter 关闭浏览器...")
        input()
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
