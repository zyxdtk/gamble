import asyncio

class LobbyManager:
    """
    Handles navigating the lobby and selecting tables.
    Does NOT manage the tabs, only returns Table URLs to join.
    """
    def __init__(self, page):
        self.page = page
        self.is_navigating = False

    async def apply_filters(self):
        """Applies filters to the lobby (e.g. 1/2 stakes)."""
        try:
            print("[LOBBY] Applying filters for 1/2 stakes...", flush=True)
            # Example implementation: click the stakes column or use search
            # ReplayPoker lobby has a search/filter box or checkboxes
            # For now, we assume default view or user set it. 
            # In a real implementation, we'd click the specific stake button.
            await asyncio.sleep(1)
        except Exception as e:
            print(f"[LOBBY] Filter application failed: {e}", flush=True)

    async def navigate_to_lobby(self):
        """Forces navigation to the lobby URL."""
        if self.is_navigating: return
        self.is_navigating = True
        try:
            print("[LOBBY] Navigating to ring games lobby...", flush=True)
            # 实际域名为 casino.org/replaypoker（基于 explore_lobby.py 探索结果）
            await self.page.goto("https://www.casino.org/replaypoker/lobby/rings", timeout=30000)
            await asyncio.sleep(3)
            await self.apply_filters()
        except Exception as e:
            print(f"[LOBBY] Navigation failed: {e}", flush=True)
        finally:
            self.is_navigating = False

    async def get_best_table_url(self):
        """
        Scans the visible lobby and returns the URL of the best available table.
        Priority: seats-yellow (more players) > seats-green (fewer players).
        Prefers tables with existing players for faster game start.
        """
        if "/lobby" not in self.page.url:
            await self.navigate_to_lobby()

        try:
            await self.page.wait_for_selector("a[href*='/play/table/']", timeout=10000)

            for seat_class in ["seats-green", "seats-yellow"]:
                rows = self.page.locator(f".lobby-game:has(.{seat_class})")
                count = await rows.count()
                if count > 0:
                    link = rows.first.locator("a[href*='/play/table/']").first
                    href = await link.get_attribute("href")
                    if href:
                        if href.startswith("/"):
                            href = f"https://www.casino.org{href}"
                        print(f"[LOBBY] Found available table ({seat_class}): {href}", flush=True)
                        return href

            link = self.page.locator("a[href*='/play/table/']").first
            href = await link.get_attribute("href")
            if href:
                if href.startswith("/"):
                    href = f"https://www.casino.org{href}"
                return href
        except Exception as e:
            print(f"[LOBBY] get_best_table_url failed: {e}", flush=True)
        return None

    async def open_table(self, url):
        """
        Given a table URL, opens it directly in the current window using page.goto().
        """
        try:
            print(f"[LOBBY] Navigating directly to {url} in current tab", flush=True)
            await self.page.goto(url, timeout=20000)
            await asyncio.sleep(3)
            return True
        except Exception as e:
            print(f"[LOBBY] Error opening table URL: {e}", flush=True)
        return False
