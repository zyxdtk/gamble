import asyncio
import os
from playwright.async_api import async_playwright

async def explore():
    async with async_playwright() as p:
        user_data_dir = "./data/browser_data"
        os.makedirs(user_data_dir, exist_ok=True)
        
        print(f"Launching browser to explore lobby...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        print("Navigating to ReplayPoker lobby...")
        # ReplayPoker lobby URL usually requires login. 
        # We assume the user is already logged in or will login manually during this explorer run.
        await page.goto("https://www.replaypoker.com/lobby")
        
        print("Waiting 10 seconds for you to login/navigate to the lobby...")
        await asyncio.sleep(10)
        
        # Capture screenshot and HTML
        await page.screenshot(path="data/lobby_screenshot.png")
        html = await page.content()
        with open("data/lobby_explore.html", "w", encoding="utf-8") as f:
            f.write(html)
            
        print("Lobby data captured to data/lobby_explore.html and data/lobby_screenshot.png")
        
        # Try to find common elements
        print("Identifying elements...")
        
        # 1. Filter buttons (Ring Games, Texas Hold'em, Stakes)
        # 2. Table list rows
        # 3. Join/Play buttons
        
        await context.close()

if __name__ == "__main__":
    asyncio.run(explore())
