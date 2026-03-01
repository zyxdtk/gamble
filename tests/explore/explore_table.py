"""
explore_table.py — 牌桌页面探索工具 (增强版 v3)

用途：
    打开大厅，自动选择一个桌子进入，等待行动，点击 Raise 截图分析 DOM。

运行方式：
    cd /path/to/gamble && source .venv/bin/activate
    python tests/explore/explore_table.py [table_url]
    python tests/explore/explore_table.py --manual [table_url]
"""

import asyncio
import os
import sys
import re
from playwright.async_api import async_playwright

# ─── 配置区 ───────────────────────────────────────────────────────────────────
USER_DATA_DIR     = "./data/browser_data"
OUTPUT_HTML       = "data/table_explore.html"
OUTPUT_SHOT       = "data/table_screenshot.png"
OUTPUT_RAISE_SHOT = "data/raise_button_screenshot.png"
POLL_INTERVAL     = 2
MAX_WAIT          = 300  # 秒


async def explore(table_url: str | None = None, manual: bool = False):
    async with async_playwright() as p:
        os.makedirs(USER_DATA_DIR, exist_ok=True)

        print("🚀 启动浏览器（使用 data/browser_data 已登录会话）...")
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # ── 导航到牌桌 ────────────────────────────────────────────────────────
        if table_url:
            print(f"📍 直接导航到牌桌: {table_url}")
            await page.goto(table_url, wait_until="domcontentloaded")
            await asyncio.sleep(8)
        else:
            # 自动从大厅找一个桌子
            print("📍 打开大厅，自动找一个有空位的桌子...")
            await page.goto("https://www.replaypoker.com/lobby", wait_until="domcontentloaded")
            await asyncio.sleep(5)

            # 找牌桌链接（<a href="/table/XXXX">）
            table_links = await page.locator("a[href*='/table/']").all()
            if not table_links:
                # 尝试备用选择器
                table_links = await page.locator(
                    "a[href*='table'], [class*='table-row'] a, [class*='lobby-games-list'] a"
                ).all()

            if table_links:
                href = await table_links[0].get_attribute("href")
                if href and not href.startswith("http"):
                    href = "https://www.replaypoker.com" + href
                print(f"✅ 找到牌桌链接：{href}")
                await page.goto(href, wait_until="domcontentloaded")
                await asyncio.sleep(8)
            else:
                print("⚠️  未找到牌桌链接，请手动进入一个牌桌（等待 60 秒）...")
                await asyncio.sleep(60)

        current_url = page.url
        print(f"   当前 URL: {current_url}")
        if "/table/" not in current_url:
            print("⚠️  仍不在牌桌页面！")

        # ── 不坐下，直接进行 DOM 探索（观察者模式）────────────────────────
        print("\n📷 先截图保存当前状态...")
        await _save_snapshot(page, OUTPUT_SHOT, OUTPUT_HTML)

        # ── 探索初始 DOM（行动前）────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("🔍 探索初始 DOM（观察者模式）...")
        print("=" * 60)
        await _probe_all(page, phase="initial")

        if manual:
            print(f"\n⏳ 手动模式：每 5 秒自动截图+分析 DOM，共 {MAX_WAIT}s，请在浏览器里操作...")
            for tick in range(MAX_WAIT // 5):
                await asyncio.sleep(5)
                elapsed = (tick + 1) * 5
                try:
                    shot_path = f"data/raise_explore_{elapsed:04d}s.png"
                    await page.screenshot(path=shot_path, full_page=False)
                    html = await page.content()
                    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"\n📷 [{elapsed}s] 截图: {shot_path}")
                    await _probe_all(page, phase=f"{elapsed}s")
                    await _dump_raise_html(page)
                except Exception as e:
                    print(f"  [{elapsed}s] 截图失败: {e}")
            print("⏱  手动模式探索结束。")
        else:
            # ── 自动模式：等待 Raise/Bet 按钮出现并点击 ─────────────────────
            print(f"\n🤖 自动等待 Raise/Bet 按钮（最多 {MAX_WAIT}s）...")
            raise_clicked = False
            for i in range(int(MAX_WAIT / POLL_INTERVAL)):
                try:
                    for btn_text in ["Raise", "Bet"]:
                        btn = page.get_by_role("button", name=re.compile(f"^{btn_text}", re.I))
                        if await btn.count() > 0 and await btn.first.is_visible():
                            print(f"\n✅ 发现 '{btn_text}' 按钮！点击...")
                            await btn.first.click()
                            await asyncio.sleep(2)
                            raise_clicked = True
                            break
                    if raise_clicked:
                        break
                except Exception:
                    pass

                if i % 10 == 0:
                    print(f"   等待 {i * POLL_INTERVAL}s / {MAX_WAIT}s", flush=True)
                await asyncio.sleep(POLL_INTERVAL)

            if raise_clicked:
                print("📷 点击 Raise 后截图...")
                await _save_snapshot(page, OUTPUT_RAISE_SHOT, OUTPUT_HTML)
                print("\n" + "=" * 60)
                print("🔍 探索 Raise 点击后的 DOM...")
                print("=" * 60)
                await _probe_all(page, phase="after_raise")
                await _dump_raise_html(page)
            else:
                print("⚠️  未自动点到 Raise 按钮，保存当前截图...")
                await _save_snapshot(page, OUTPUT_RAISE_SHOT, OUTPUT_HTML)

        print("\n" + "=" * 60)
        print("🏁 探索完成：")
        print(f"   📄 HTML  : {OUTPUT_HTML}")
        print(f"   🖼  截图  : {OUTPUT_SHOT}")
        print(f"   🖼  Raise截图 : {OUTPUT_RAISE_SHOT}")
        print("=" * 60)
        await context.close()


async def _save_snapshot(page, shot_path, html_path):
    try:
        await page.screenshot(path=shot_path, full_page=False)
        html = await page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  ✅ 截图: {shot_path} | HTML: {html_path}")
    except Exception as e:
        print(f"  ⚠️  保存失败: {e}")


async def _probe_all(page, phase=""):
    label_prefix = f"[{phase}] " if phase else ""
    probes = [
        ("行动按钮", ["button:has-text('Fold')", "button:has-text('Check')",
                      "button:has-text('Call')", "button:has-text('Raise')",
                      "button:has-text('Bet')", "button:has-text('All In')"]),
        ("Raise/Bet 金额输入框", ["input[type='number']", "input[type='range']",
                                   "input[class*='amount']", "input[class*='Amount']",
                                   "[class*='BetInput']", "[class*='RaiseInput']"]),
        ("Raise 滑块", ["input[type='range']", "[role='slider']",
                        "[class*='Slider']", "[class*='slider']"]),
        ("Raise +/- 按钮", ["button:has-text('+')", "button:has-text('-')",
                             "button[class*='plus']", "button[class*='minus']",
                             "button[class*='increment']", "button[class*='decrement']"]),
        ("Raise 金额容器", ["[class*='BetControls']", "[class*='RaiseControls']",
                            "[class*='BetAmount']", "[class*='RaiseAmount']",
                            "[class*='ActionControls']", "[class*='BetsPanel']"]),
    ]
    for label, selectors in probes:
        await _probe(page, label_prefix + label, selectors)


async def _dump_raise_html(page):
    """尝试打印 Raise 控件区域的完整 HTML"""
    print("\n� 尝试输出 Raise 控件完整 HTML...")
    candidates = [
        "input[type='range']",
        "input[type='number']",
        "[class*='BetControls']",
        "[class*='ActionControls']",
        "[class*='RaiseControls']",
    ]
    for sel in candidates:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                # 获取其最近有意义的父容器
                html_snippet = await el.evaluate("""el => {
                    let p = el;
                    for (let i = 0; i < 4; i++) {
                        if (p.parentElement) p = p.parentElement;
                    }
                    return p.outerHTML.substring(0, 3000);
                }""")
                print(f"\n🔑 [{sel}] 父容器 outerHTML (截断至3000字符):\n{html_snippet}")
        except Exception as e:
            pass


async def _probe(page, label: str, selectors: list[str]):
    print(f"\n--- {label} ---")
    found_any = False
    for sel in selectors:
        try:
            elements = await page.locator(sel).all()
            if elements:
                found_any = True
                print(f"  [{sel}]  找到 {len(elements)} 个")
                for i, el in enumerate(elements[:3]):
                    try:
                        text    = (await el.inner_text()).strip()[:60]
                        cls     = (await el.get_attribute("class") or "")[:80]
                        el_type = await el.get_attribute("type") or ""
                        el_min  = await el.get_attribute("min") or ""
                        el_max  = await el.get_attribute("max") or ""
                        el_val  = await el.get_attribute("value") or ""
                        extra = ""
                        if el_type: extra += f" type={repr(el_type)}"
                        if el_min or el_max: extra += f" min={el_min} max={el_max} val={el_val}"
                        print(f"    [{i}] text={repr(text)}  class={repr(cls)}{extra}")
                    except Exception:
                        print(f"    [{i}] (无法读取属性)")
        except Exception as e:
            print(f"  [{sel}]  查询失败: {e}")
    if not found_any:
        print("  (未找到任何元素)")


if __name__ == "__main__":
    args = sys.argv[1:]
    manual_mode = "--manual" in args
    if manual_mode:
        args.remove("--manual")
    url_arg = args[0] if args else None
    asyncio.run(explore(url_arg, manual=manual_mode))
