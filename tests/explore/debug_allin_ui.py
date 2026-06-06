"""
tests/explore/debug_allin_ui.py

针对特定桌台分析 All-In 阶段的 UI 结构。
用法:
    uv run python tests/explore/debug_allin_ui.py
"""
import asyncio
import json
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright

USER_DATA_DIR = "./data/browser_data"
DEBUG_PORT = 9222
TARGET_URL = "https://www.casino.org/replaypoker/play/table/16644696"
OUTPUT_DIR = Path(__file__).parent / "data"

async def capture_ui(page):
    return await page.evaluate("""
        () => {
            const buttons = Array.from(document.querySelectorAll('button'))
                .filter(el => el.offsetParent !== null)
                .map(el => ({
                    text: el.textContent.trim(),
                    class: el.className,
                    visible: el.offsetParent !== null,
                    rect: el.getBoundingClientRect().toJSON()
                }));
            
            const inputs = Array.from(document.querySelectorAll('input'))
                .filter(el => el.offsetParent !== null)
                .map(el => ({
                    type: el.type,
                    class: el.className,
                    value: el.value,
                    inputmode: el.getAttribute('inputmode')
                }));

            return { buttons, inputs };
        }
    """)

async def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    async with async_playwright() as p:
        print(f"尝试连接到已有浏览器 (端口 {DEBUG_PORT})...")
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
            context = browser.contexts[0]
            print("✓ 已连接")
        except Exception:
            print("连接失败，启动新实例...")
            context = await p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, channel="chrome")

        page = await context.new_page()
        print(f"导航到目标桌台: {TARGET_URL}")
        await page.goto(TARGET_URL)
        
        print("等待 10 秒观察 UI，请准备好让对手 All-In 或自己进入决策...")
        
        for i in range(20):
            await asyncio.sleep(5)
            data = await capture_ui(page)
            
            print(f"\n--- [{i*5}s] 当前按钮 ---")
            for btn in data['buttons']:
                # 过滤掉无关按钮
                if len(btn['text']) > 0 and len(btn['text']) < 30:
                    if re.search(r'fold|call|check|raise|bet|all|min|max|pot', btn['text'], re.I):
                        print(f"  [{btn['text']}] class={btn['class']}")

            # 如果发现 All In 按钮，截图并保存数据
            all_in = [b for b in data['buttons'] if re.search(r'all[ -]?in', b['text'], re.I)]
            if all_in:
                print(f"🎯 发现 ALL IN 按钮！文本: {all_in[0]['text']}")
                await page.screenshot(path=str(OUTPUT_DIR / "allin_detected.png"))
                with open(OUTPUT_DIR / "allin_ui.json", "w") as f:
                    json.dump(data, f, indent=2)
                print(f"✓ 截图与数据已保存到 {OUTPUT_DIR}")
            
            if i % 4 == 0:
                await page.screenshot(path=str(OUTPUT_DIR / f"state_{i}.png"))

if __name__ == "__main__":
    asyncio.run(main())
