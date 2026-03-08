"""
tests/explore/explore_table.py

自动探索牌桌，等待行动并捕获 DOM 快照。

使用方法:
    python tests/explore/explore_table.py           # 自动连接/启动浏览器
    python tests/explore/explore_table.py <url>     # 直接进入指定桌子
    python tests/explore/explore_table.py --manual  # 手动模式，每5秒截图
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright

USER_DATA_DIR = "./data/browser_data"
OUTPUT_DIR = Path(__file__).parent / "data"
DEBUG_PORT = 9222


async def capture_snapshot(page, name: str) -> dict:
    """捕获 DOM 快照"""
    snapshot = {
        "name": name,
        "timestamp": time.time(),
        "url": page.url,
        "data": {}
    }

    data = snapshot["data"]

    # 底池
    pot = page.locator(".Pot__value").first
    if await pot.count() > 0:
        data["pot"] = await pot.text_content()

    # 盲注
    for sel in [".TableInfo__stakes", ".TableInfo__blinds"]:
        el = page.locator(sel).first
        if await el.count() > 0:
            data["stakes"] = await el.text_content()
            break

    # 座位
    data["seats"] = []
    seats = page.locator(".Seat")
    for i in range(await seats.count()):
        seat = seats.nth(i)
        seat_data = {"index": i}

        if await seat.locator(".Seat__name").count() > 0:
            seat_data["name"] = await seat.locator(".Seat__name").first.text_content()
        if await seat.locator(".Stack__value").count() > 0:
            seat_data["stack"] = await seat.locator(".Stack__value").first.text_content()
        if await seat.locator(".DealerButton").count() > 0:
            seat_data["is_dealer"] = True

        cards = seat.locator(".Card")
        if await cards.count() > 0:
            seat_data["cards"] = [await cards.nth(j).get_attribute("class") for j in range(await cards.count())]

        seat_class = await seat.get_attribute("class") or ""
        if "Seat--active" in seat_class:
            seat_data["is_active"] = True

        data["seats"].append(seat_data)

    # 公共牌
    data["community_cards"] = []
    community = page.locator(".CommunityCard")
    for i in range(await community.count()):
        data["community_cards"].append(await community.nth(i).get_attribute("class"))

    # 按钮
    data["buttons"] = {}
    for btn_name in ["Fold", "Call", "Check", "Raise", "Bet", "All In"]:
        btn = page.get_by_role("button", name=btn_name)
        if await btn.count() > 0:
            data["buttons"][btn_name.lower()] = {
                "text": await btn.first.text_content(),
                "visible": await btn.first.is_visible()
            }

    # 我的座位
    for seat in data["seats"]:
        if "cards" in seat and len(seat["cards"]) == 2:
            data["my_seat_index"] = seat["index"]
            break

    return snapshot


async def save_snapshot(page, snapshot: dict):
    """
    保存快照：JSON + 截图 + HTML
    
    生成文件:
        - {name}_{timestamp}.json   # 数据快照
        - {name}_{timestamp}.png    # 截图
        - {name}_{timestamp}.html   # 完整 DOM
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    ts = int(snapshot["timestamp"])
    name = snapshot["name"]
    base_filename = f"{name}_{ts}"
    
    # 1. 保存 JSON
    json_path = OUTPUT_DIR / f"{base_filename}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    
    # 2. 保存截图
    screenshot_path = OUTPUT_DIR / f"{base_filename}.png"
    await page.screenshot(path=str(screenshot_path))
    
    # 3. 保存 HTML DOM
    html_path = OUTPUT_DIR / f"{base_filename}.html"
    html_content = await page.content()
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"  ✓ JSON: {json_path}")
    print(f"  ✓ PNG:  {screenshot_path}")
    print(f"  ✓ HTML: {html_path}")


async def find_best_table_url(page) -> str | None:
    """
    从大厅找最佳桌子 URL。
    复用 LobbyManager 的逻辑。
    """
    try:
        await page.wait_for_selector("a[href*='/table/'], a[href*='/play/table/']", timeout=10000)

        # 优先选择有更多玩家的桌子
        for seat_class in ["seats-yellow", "seats-green"]:
            rows = page.locator(f".lobby-game:has(.{seat_class})")
            count = await rows.count()
            if count > 0:
                link = rows.first.locator("a[href*='/table/'], a[href*='/play/table/']").first
                href = await link.get_attribute("href")
                if href:
                    if href.startswith("/"):
                        href = f"https://www.casino.org{href}"
                    print(f"  找到桌子 ({seat_class}): {href}")
                    return href

        # 备用：任意桌子
        link = page.locator("a[href*='/table/'], a[href*='/play/table/']").first
        href = await link.get_attribute("href")
        if href:
            if href.startswith("/"):
                href = f"https://www.casino.org{href}"
            return href
    except Exception as e:
        print(f"  找桌子失败: {e}")

    return None


async def take_seat(page):
    """
    尝试坐下。
    """
    try:
        # 查找空的座位按钮
        sit_buttons = page.locator("button:has-text('Sit'), button:has-text('Join'), .Seat--empty button")
        count = await sit_buttons.count()
        if count > 0:
            print(f"  找到 {count} 个空座位，尝试坐下...")
            await sit_buttons.first.click()
            await asyncio.sleep(2)

            # 检查是否需要买入
            buyin_input = page.locator("input[type='number'], input[class*='buyin']")
            if await buyin_input.count() > 0:
                confirm_btn = page.locator("button:has-text('OK'), button:has-text('Buy'), button:has-text('Confirm')")
                if await confirm_btn.count() > 0:
                    await confirm_btn.first.click()
                    await asyncio.sleep(2)

            print("  ✓ 已坐下")
            return True
    except Exception as e:
        print(f"  坐下失败: {e}")

    return False


async def main(table_url: str = None, manual: bool = False):
    print("=" * 60)
    print("牌桌 DOM 探索工具")
    print("=" * 60)

    browser = None
    context = None
    need_close = False

    async with async_playwright() as p:
        # 优先尝试连接已有浏览器
        print("\n尝试连接已有浏览器 (端口 9222)...")
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}", timeout=3000)
            print("✓ 已连接到已有浏览器")
            context = browser.contexts[0]
        except Exception:
            print("未找到已有浏览器，启动新浏览器...")
            os.makedirs(USER_DATA_DIR, exist_ok=True)
            context = await p.chromium.launch_persistent_context(
                USER_DATA_DIR,
                headless=False,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"]
            )
            need_close = True

        page = context.pages[0] if context.pages else await context.new_page()

        # 导航
        if table_url:
            print(f"导航到: {table_url}")
            await page.goto(table_url, wait_until="domcontentloaded")
        else:
            current_url = page.url
            if "table" in current_url:
                print(f"已在牌桌页面: {current_url}")
            else:
                # 导航到大厅
                print("导航到大厅...")
                await page.goto("https://www.casino.org/replaypoker/lobby/rings", wait_until="domcontentloaded")
                await asyncio.sleep(3)

                # 找桌子
                print("寻找最佳桌子...")
                table_url = await find_best_table_url(page)
                if table_url:
                    print(f"进入桌子: {table_url}")
                    await page.goto(table_url, wait_until="domcontentloaded")
                    await asyncio.sleep(3)

                    # 尝试坐下
                    await take_seat(page)
                else:
                    print("未找到桌子，请手动操作...")

        await asyncio.sleep(3)
        print(f"\n当前 URL: {page.url}")

        # 捕获初始状态
        print("\n[1] 捕获当前状态...")
        snapshot = await capture_snapshot(page, "initial")
        print(f"  底池: {snapshot['data'].get('pot', 'N/A')}")
        print(f"  公共牌: {len(snapshot['data'].get('community_cards', []))} 张")
        print(f"  按钮: {list(snapshot['data'].get('buttons', {}).keys())}")
        await save_snapshot(page, snapshot)

        if manual:
            # 手动模式
            print("\n[手动模式] 每 5 秒自动截图，持续 5 分钟...")
            print("按 Ctrl+C 停止")
            try:
                for tick in range(60):
                    await asyncio.sleep(5)
                    elapsed = (tick + 1) * 5
                    print(f"\n[{elapsed}s] 捕获...")
                    snapshot = await capture_snapshot(page, f"manual_{elapsed}s")
                    await save_snapshot(page, snapshot)
            except KeyboardInterrupt:
                print("\n用户中断")
        else:
            # 自动模式：等待行动
            print("\n[自动模式] 等待行动按钮出现 (最多 3 分钟)...")
            print("按 Ctrl+C 停止")
            captured_actions = set()

            try:
                for i in range(90):
                    # 检查是否有可见的行动按钮
                    for btn_name in ["Fold", "Call", "Check", "Raise", "Bet"]:
                        btn = page.get_by_role("button", name=btn_name)
                        if await btn.count() > 0 and await btn.first.is_visible():
                            if btn_name not in captured_actions:
                                captured_actions.add(btn_name)
                                print(f"\n[发现行动] {btn_name} 按钮可见!")
                                snapshot = await capture_snapshot(page, f"action_{btn_name.lower()}")
                                print(f"  底池: {snapshot['data'].get('pot', 'N/A')}")
                                print(f"  按钮: {snapshot['data'].get('buttons', {})}")
                                await save_snapshot(page, snapshot)

                    if i % 10 == 0:
                        print(f"  等待中... {i * 2}s")
                    await asyncio.sleep(2)
            except KeyboardInterrupt:
                print("\n用户中断")

        print("\n" + "=" * 60)
        print("探索完成!")
        print(f"快照保存在: {OUTPUT_DIR}")
        print("=" * 60)

        if need_close:
            await context.close()
        elif browser:
            await browser.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    manual = "--manual" in args
    if manual:
        args.remove("--manual")
    url = args[0] if args else None
    asyncio.run(main(url, manual))
