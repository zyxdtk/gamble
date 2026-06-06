"""
tests/explore/explore_bet_controls.py

复用已有浏览器（参照 explore_table.py 方式），自动导航到牌桌坐下，
等待 Raise/Bet 按钮出现后捕获加注控件的真实 DOM 结构。

用法:
    uv run python tests/explore/explore_bet_controls.py
"""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright

USER_DATA_DIR = "./data/browser_data"
OUTPUT_DIR = Path(__file__).parent / "data"
DEBUG_PORT = 9222
LOBBY_URL = "https://www.casino.org/replaypoker/lobby/rings"


async def find_table_url(page) -> str | None:
    """从大厅找一个有空位的桌子"""
    try:
        await page.wait_for_selector("a[href*='/table/'], a[href*='/play/table/']", timeout=8000)
        for seat_cls in ["seats-green", "seats-yellow", ""]:
            if seat_cls:
                rows = page.locator(f".lobby-game:has(.{seat_cls})")
            else:
                rows = page.locator(".lobby-game")
            if await rows.count() > 0:
                link = rows.first.locator("a[href*='/table/'], a[href*='/play/table/']").first
                href = await link.get_attribute("href")
                if href:
                    return f"https://www.casino.org{href}" if href.startswith("/") else href
    except Exception as e:
        print(f"  找桌子失败: {e}")
    return None


async def capture_bet_controls(page) -> dict:
    """捕获所有与加注相关的 DOM 元素"""
    return await page.evaluate("""
        () => ({
            inputs: Array.from(document.querySelectorAll('input'))
                .filter(el => el.offsetParent !== null)
                .map(el => ({
                    type: el.type,
                    class: el.className,
                    id: el.id,
                    name: el.name,
                    value: el.value,
                    pattern: el.getAttribute('pattern'),
                    inputmode: el.getAttribute('inputmode'),
                    parentClass: el.parentElement?.className,
                    grandParentClass: el.parentElement?.parentElement?.className,
                })),
            action_buttons: Array.from(document.querySelectorAll('button'))
                .filter(el => el.offsetParent !== null && /fold|call|check|raise|bet|allin|all.in|min|max|pot|half|[0-9]/i.test(el.textContent))
                .map(el => ({
                    text: el.textContent.trim().slice(0, 80),
                    class: el.className,
                    id: el.id,
                    parentClass: el.parentElement?.className,
                })),
            bet_containers: Array.from(document.querySelectorAll('[class]'))
                .filter(el => {
                    const cls = el.className;
                    return typeof cls === 'string' &&
                           /bet|raise|amount|slider|range|preset/i.test(cls) &&
                           el.offsetParent !== null;
                })
                .map(el => ({
                    tag: el.tagName,
                    class: el.className,
                    innerHTML: el.innerHTML.slice(0, 500),
                }))
        })
    """)


async def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    need_close = False

    async with async_playwright() as p:
        browser = None
        context = None

        # 1. 优先连接已有浏览器（同 explore_table.py）
        print(f"\n尝试连接已有浏览器 (端口 {DEBUG_PORT})...")
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
                args=["--disable-blink-features=AutomationControlled"],
            )
            need_close = True

        page = None
        for p_candidate in context.pages:
            if "replaypoker" in p_candidate.url or "casino.org" in p_candidate.url:
                page = p_candidate
                print(f"✓ 找到活跃页面: {page.url}")
                break
        if page is None:
            page = context.pages[0] if context.pages else await context.new_page()
        print(f"当前页面: {page.url}")


        # 2. 如果不在牌桌页面，自动导航
        if "table" not in page.url:
            print("导航到大厅...")
            await page.goto(LOBBY_URL, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            print("寻找桌子...")
            table_url = await find_table_url(page)
            if table_url:
                print(f"进入桌子: {table_url}")
                await page.goto(table_url, wait_until="domcontentloaded")
                await asyncio.sleep(4)
            else:
                print("未找到桌子！退出。")
                if need_close:
                    await context.close()
                return

        # 3. 尝试坐下
        if "table" in page.url:
            seat_any = page.get_by_role("button", name="Seat me anywhere")
            if await seat_any.count() > 0 and await seat_any.is_visible():
                print("点击 'Seat me anywhere'...")
                await seat_any.click()
                await asyncio.sleep(2)
                # 点击买入弹窗的 Ok
                ok_btn = page.locator(".BuyInModal__button--submit").first
                if await ok_btn.count() > 0 and await ok_btn.is_visible():
                    print("点击买入 Ok...")
                    await ok_btn.click()
                    await asyncio.sleep(2)

        # 4. 等待 Raise/Bet 按钮出现
        print("\n等待 Raise/Bet 按钮出现并点击（最多 3 分钟）...\n")
        captured = False
        for i in range(90):
            try:
                raise_btn = page.get_by_role("button", name="Raise").first
                bet_btn = page.get_by_role("button", name="Bet").first

                clicked_btn_name = None
                if await raise_btn.count() > 0 and await raise_btn.is_visible():
                    print(f"🎯 [{i*2}s] 发现 Raise 按钮！点击它以触发金额输入控件...")
                    await raise_btn.click()
                    clicked_btn_name = "Raise"
                elif await bet_btn.count() > 0 and await bet_btn.is_visible():
                    print(f"🎯 [{i*2}s] 发现 Bet 按钮！点击它以触发金额输入控件...")
                    await bet_btn.click()
                    clicked_btn_name = "Bet"

                if clicked_btn_name:
                    # 等待金额选择 UI 出现
                    await asyncio.sleep(1)
                    await page.screenshot(path=str(OUTPUT_DIR / "action_state.png"))

                    data = await capture_bet_controls(page)

                    print(f"\n=== INPUT 控件（点击 {clicked_btn_name} 后）===")
                    for inp in data.get("inputs", []):
                        if "Chat" not in inp.get("class", ""):
                            print(f"  type={inp['type']!r}  class={inp['class']!r}")
                            print(f"    parent: {inp['parentClass']!r}")
                            print(f"    grandparent: {inp['grandParentClass']!r}")

                    print(f"\n=== 行动相关按钮（点击 {clicked_btn_name} 后）===")
                    for btn in data.get("action_buttons", []):
                        if "Seat" not in btn.get("class", "") and "Header" not in btn.get("class", ""):
                            print(f"  [{btn['text']!r}]  class={btn['class']!r}")
                            print(f"    parent: {btn['parentClass']!r}")

                    print(f"\n=== 加注相关容器（点击 {clicked_btn_name} 后）===")
                    for cont in data.get("bet_containers", []):
                        if "Volume" not in cont.get("class", "") and "rangeslider" not in cont.get("class", ""):
                            print(f"  <{cont['tag']}> class={cont['class']!r}")
                            print(f"    {cont['innerHTML'][:400]}")
                            print()

                    out_path = OUTPUT_DIR / "bet_controls.json"
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"\n✓ 完整数据: {out_path}")
                    print(f"✓ 截图:     {OUTPUT_DIR / 'action_state.png'}")
                    captured = True
                    break

                if i % 10 == 0:
                    print(f"  等待中... {i*2}s")
            except Exception as e:
                if "closed" in str(e).lower():
                    print("  浏览器已关闭，退出")
                    break
                print(f"  [警告] {e}")

            await asyncio.sleep(2)

        if not captured:
            print("超时，未能捕获行动状态。")


        if need_close:
            await context.close()
        elif browser:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
