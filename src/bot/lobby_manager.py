import asyncio

class LobbyManager:
    """
    Handles navigating the lobby and selecting tables.
    Does NOT manage the tabs, only returns Table URLs to join.
    """
    def __init__(self, page, preferred_stakes: str = "1/2"):
        self.page = page
        self.is_navigating = False
        self.preferred_stakes = preferred_stakes

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
            await self.page.goto("https://www.casino.org/replaypoker/lobby/rings", wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)
            await self.apply_filters()
        except Exception as e:
            print(f"[LOBBY] Navigation failed: {e}", flush=True)
        finally:
            self.is_navigating = False

    async def get_all_available_tables(self) -> list[str]:
        """
        Scans the visible lobby and returns all available table URLs.
        Priority: seats-yellow (more players) > seats-green (fewer players).
        """
        if "/lobby" not in self.page.url:
            await self.navigate_to_lobby()

        urls = []
        try:
            await self.page.wait_for_selector("a[href*='/play/table/']", timeout=10000)

            # 遍历不同类型的空位桌台
            for seat_class in ["seats-yellow", "seats-green"]:
                rows = self.page.locator(f".lobby-game:has(.{seat_class})")
                count = await rows.count()
                for i in range(count):
                    row = rows.nth(i)
                    
                    # [FEATURE] 硬编码盲注过滤
                    if self.preferred_stakes.strip():
                        # 获取这行的所有文本，去除空格以兼容 "5/10" 或 "5 / 10" 的格式
                        row_text = await row.text_content()
                        if row_text:
                            clean_text = row_text.replace(" ", "")
                            target = self.preferred_stakes.strip().replace(" ", "")
                            if target and target not in clean_text:
                                continue
                                
                    link = row.locator("a[href*='/play/table/']").first
                    href = await link.get_attribute("href")
                    if href:
                        url = f"https://www.casino.org{href}" if href.startswith("/") else href
                        if url not in urls:
                            urls.append(url)

            # 兜底：如果没找到带色的，尝试获取前 5 个任何桌子
            if not urls:
                all_links = self.page.locator("a[href*='/play/table/']")
                count = await all_links.count()
                for i in range(min(count, 5)):
                    href = await all_links.nth(i).get_attribute("href")
                    if href:
                        url = f"https://www.casino.org{href}" if href.startswith("/") else href
                        if url not in urls:
                            urls.append(url)
                            
        except Exception as e:
            print(f"[LOBBY] get_all_available_tables failed: {e}", flush=True)
        return urls

    async def get_best_table_url(self):
        """
        Legacy wrapper. Returns the first available table URL.
        """
        try:
            urls = await self.get_all_available_tables()
            return urls[0] if urls else None
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
