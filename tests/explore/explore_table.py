"""
explore_table.py — 牌桌页面探索工具

用途：
    打开一个已知的牌桌 URL，截图并保存 HTML，便于离线分析页面结构。
    用于开发阶段探索以下元素的定位方式：
      - 玩家列表与座位（含自己的名字）
      - 手牌 / 公共牌区域
      - 底池、盲注信息
      - 行动按钮（Fold / Check / Call / Raise）
      - 入座按钮（Seat Me Anywhere / 空座位）
      - Buy-in 弹窗
      - 满员提示（Join Waiting List 按钮）

运行方式：
    cd /path/to/gamble
    source .venv/bin/activate
    python tests/explore_table.py [table_url]

    若不传 table_url，脚本会打开大厅，等待你手动进入牌桌后再抓取。
"""

import asyncio
import os
import sys
from playwright.async_api import async_playwright

# ─── 配置区 ───────────────────────────────────────────────────────────────────
USER_DATA_DIR = "./data/browser_data"
OUTPUT_HTML   = "data/table_explore.html"
OUTPUT_SHOT   = "data/table_screenshot.png"
WAIT_SECONDS  = 30   # 等待你手动导航/登录的时间（秒）


async def explore(table_url: str | None = None):
    async with async_playwright() as p:
        os.makedirs(USER_DATA_DIR, exist_ok=True)

        print("🚀 启动浏览器...")
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # ── 导航 ──────────────────────────────────────────────────────────────
        if table_url:
            print(f"📍 直接导航到牌桌: {table_url}")
            await page.goto(table_url)
            print(f"⏳ 等待 {WAIT_SECONDS} 秒，让页面完全加载...")
            await asyncio.sleep(WAIT_SECONDS)
        else:
            print("📍 未指定牌桌 URL，打开大厅，请手动进入一个牌桌...")
            await page.goto("https://www.replaypoker.com/lobby")
            print(f"⏳ 等待 {WAIT_SECONDS} 秒，请在浏览器中手动进入牌桌...")
            await asyncio.sleep(WAIT_SECONDS)
            print(f"   当前页面 URL: {page.url}")

        # ── 检查是否真正进入了牌桌 ────────────────────────────────────────────
        current_url = page.url
        print(f"   当前页面 URL: {current_url}")
        if "/table/" not in current_url:
            print(f"⚠️  警告: 当前页面不是牌桌页面（URL 中没有 /table/）")
            print(f"   请确认你已手动进入一个牌桌，或通过命令行参数传入牌桌 URL：")
            print(f"   python tests/explore_table.py https://www.replaypoker.com/table/XXXXX")

        # ── 截图 & 保存 HTML ──────────────────────────────────────────────────
        try:
            await page.screenshot(path=OUTPUT_SHOT, full_page=True)
            html = await page.content()
            with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"✅ 截图已保存: {OUTPUT_SHOT}")
            print(f"✅ HTML 已保存: {OUTPUT_HTML}")
        except Exception as e:
            print(f"⚠️  截图/保存失败（页面可能已关闭）: {e}")

        # ── 元素探索 ─────────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("🔍 开始探索页面元素...")
        print("=" * 60)

        # 1. 玩家列表 / 座位
        await _probe(page, "玩家座位区",
            selectors=["[class*='seat']", "[class*='player']", "[data-seat]"])

        # 2. 公共牌 / 手牌
        await _probe(page, "公共牌 / 手牌",
            selectors=["[class*='community']", "[class*='hole']",
                       "[class*='card']", "[class*='board']"])

        # 3. 底池 / 盲注
        await _probe(page, "底池 / 盲注信息",
            selectors=["[class*='pot']", "[class*='blind']", "[class*='chips']"])

        # 4. 行动按钮（真实激活态）
        await _probe(page, "行动按钮 (Fold/Check/Call/Raise)",
            selectors=["button:has-text('Fold')", "button:has-text('Check')",
                       "button:has-text('Call')",  "button:has-text('Raise')",
                       "button:has-text('Bet')",   "button:has-text('All In')"])

        # 5. 入座相关
        await _probe(page, "入座按钮",
            selectors=["button:has-text('Seat Me')", "button:has-text('Sit')",
                       "[class*='empty-seat']", "[class*='open-seat']"])

        # 6. Buy-in 弹窗（触发后才会出现，此时可能不可见）
        await _probe(page, "Buy-in 弹窗",
            selectors=["[class*='buyin']", "[class*='buy-in']",
                       "dialog", "[role='dialog']"])

        # 7. 满员标志
        await _probe(page, "满员标志 (Join Waiting List)",
            selectors=["button:has-text('Join Waiting List')",
                       "button:has-text('Waiting')", "[class*='waiting']"])

        print("\n" + "=" * 60)
        print("🏁 探索完成。请查看以下文件进行离线分析：")
        print(f"   📄 HTML : {OUTPUT_HTML}")
        print(f"   🖼️  截图 : {OUTPUT_SHOT}")
        print("=" * 60)

        await context.close()


async def _probe(page, label: str, selectors: list[str]):
    """尝试多个选择器，打印每个找到的元素的基本信息。"""
    print(f"\n--- {label} ---")
    found_any = False
    for sel in selectors:
        try:
            elements = await page.locator(sel).all()
            if elements:
                found_any = True
                print(f"  [{sel}]  找到 {len(elements)} 个")
                # 打印前 3 个的文本和 class，用于定位参考
                for i, el in enumerate(elements[:3]):
                    try:
                        text  = (await el.inner_text()).strip()[:60]
                        cls   = await el.get_attribute("class") or ""
                        cls   = cls[:80]
                        print(f"    [{i}] text={repr(text)}  class={repr(cls)}")
                    except Exception:
                        print(f"    [{i}] (无法读取属性)")
        except Exception as e:
            print(f"  [{sel}]  查询失败: {e}")

    if not found_any:
        print("  (未找到任何元素，请检查选择器或页面状态)")


if __name__ == "__main__":
    url_arg = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(explore(url_arg))
