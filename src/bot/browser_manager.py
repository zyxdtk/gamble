from __future__ import annotations
import asyncio
import os
import re
import yaml
from playwright.async_api import async_playwright
from .lobby_manager import LobbyManager
from .table_manager import TableManager


class BrowserManager:
    """
    Coordinates browser lifecycle and limits.
    Manages one Lobby tab and multiple Table tabs.
    """
    def __init__(self, headless=False, apprentice_mode=False, auto_mode=False):
        self.headless = headless
        self.apprentice_mode = apprentice_mode
        self.auto_mode = auto_mode
        self.playwright = None
        self.context = None

        self.lobby_manager = None
        self.table_managers = {}

        self.max_tables = 1
        self.preferred_strategy = "gto"

        # 运行限制（从环境变量读取）
        self.max_hands = self._get_env_int("POKER_MAX_HANDS", None)
        self.max_cycles = self._get_env_int("POKER_MAX_CYCLES", None)
        self.max_duration_min = self._get_env_int("POKER_MAX_DURATION_MIN", None)

        # 已访问的桌子记录（避免重复进入）
        self._visited_tables: set = set()

        # 累计统计（包含已关闭的桌子）
        self._accumulated_stats = {
            "total_hands": 0,
            "total_cycles": 0,
            "total_buyin_added": 0,
            "total_profit": 0,
            "tables_completed": 0,
        }

        self.load_config()

    def _get_env_int(self, key: str, default: int | None) -> int | None:
        """从环境变量读取整数。"""
        try:
            value = os.environ.get(key)
            if value:
                return int(value)
        except (ValueError, TypeError):
            pass
        return default

    def load_config(self):
        try:
            with open("config/settings.yaml", 'r') as f:
                config = yaml.safe_load(f)
                self.max_tables = config.get("game", {}).get("max_tables", 1)
                self.preferred_strategy = config.get("strategy", {}).get("type", "gto")
        except Exception:
            pass
        env_strategy = os.environ.get("POKER_STRATEGY", "").strip()
        if env_strategy:
            self.preferred_strategy = env_strategy

    def get_strategy_type(self) -> str:
        if self.apprentice_mode:
            return "checkorfold"
        # 每次调用时重新读取环境变量，确保获取最新策略设置
        env_strategy = os.environ.get("POKER_STRATEGY", "").strip()
        if env_strategy:
            return env_strategy
        return self.preferred_strategy

    async def start(self):
        print("Starting BrowserManager...", flush=True)
        self.playwright = await async_playwright().start()
        print("[MANAGER] Playwright started.", flush=True)

        user_data_dir = "./data/browser_data"
        os.makedirs(user_data_dir, exist_ok=True)

        print(f"[MANAGER] Launching browser with {user_data_dir}...", flush=True)
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir,
            headless=self.headless,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        print("[MANAGER] Browser context launched.", flush=True)

        self.context.on("page", self.on_page_created)

        lobby_page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.lobby_manager = LobbyManager(lobby_page)

        if lobby_page.url == "about:blank":
            await lobby_page.goto("https://www.casino.org/replaypoker/lobby/rings")

        print(f"BrowserManager initialized. Max tables: {self.max_tables}", flush=True)

    @staticmethod
    def _extract_table_id(url: str) -> str | None:
        m = re.search(r'/(?:play/)?table/([\d]+)', url)
        return m.group(1) if m else None

    async def _get_available_table(self) -> str | None:
        """
        获取可用的桌子 URL（排除已访问过的）。
        
        Returns:
            桌子 URL 或 None
        """
        max_attempts = 5
        for attempt in range(max_attempts):
            table_url = await self.lobby_manager.get_best_table_url()
            if not table_url:
                return None
                
            table_id = self._extract_table_id(table_url)
            if not table_id:
                return table_url  # 无法提取 ID，直接返回
                
            # 检查是否已访问过
            if table_id not in self._visited_tables:
                return table_url
            else:
                print(f"[MANAGER] Table {table_id} already visited, trying another...", flush=True)
                await asyncio.sleep(1)
                
        print(f"[MANAGER] All available tables have been visited ({len(self._visited_tables)} tables)", flush=True)
        return None

    async def on_page_created(self, page):
        try:
            await asyncio.sleep(2)
            url = page.url
            if "/table/" in url:
                self.add_table_manager(page)
        except Exception:
            pass

    def add_table_manager(self, page):
        url = page.url
        table_id = self._extract_table_id(url)
        if not table_id:
            return
        if table_id in self.table_managers:
            return
        print(f"[MANAGER] New table tab detected (id={table_id}): {url}", flush=True)
        strategy_type = self.get_strategy_type()
        manager = TableManager(page, strategy_type=strategy_type)

        # 传递运行限制到 TableManager
        if self.max_hands:
            manager.max_hands_limit = self.max_hands
        if self.max_cycles:
            manager.max_cycles = self.max_cycles

        self.table_managers[table_id] = manager
        asyncio.create_task(manager.initialize())

    def _accumulate_table_stats(self, manager):
        """保存已关闭桌子的统计信息到累计统计中。"""
        self._accumulated_stats["total_hands"] += manager.hands_played
        self._accumulated_stats["total_cycles"] += manager.dealer_cycle_count
        
        # 修正买入和筹码统计
        start_chips = manager.starting_stack or 0
        added_buyin = manager.added_buyin or 0
        current_chips = manager.state.total_chips or 0
        
        # 统计追加买入到全局
        self._accumulated_stats["total_buyin_added"] += added_buyin
        
        # 计算盈利：最终筹码 - (初始筹码 + 追加买入)
        profit = 0
        if start_chips > 0:
            profit = current_chips - (start_chips + added_buyin)
            self._accumulated_stats["total_profit"] += profit
        
        self._accumulated_stats["tables_completed"] += 1
        
        # 提取正确的 Table ID
        table_url = manager.page.url
        table_id = BrowserManager._extract_table_id(table_url) or "unknown"
        
        print(
            f"[MANAGER] 🏁 Table Closed Statistics:\n"
            f"   - Table ID: {table_id}\n"
            f"   - Hands: {manager.hands_played}, Cycles: {manager.dealer_cycle_count}\n"
            f"   - Start Stack: {start_chips}, Added Buy-in: {added_buyin}, Final Chips: {current_chips}\n"
            f"   - This Table Profit: {profit:+d}\n"
            f"   - Total Accumulated Profit: {self._accumulated_stats['total_profit']:+d}",
            flush=True
        )

    async def run_tick(self) -> bool:
        """
        执行一个 tick。
        
        Returns:
            True 如果成功执行，False 如果没有可用桌子且任务应该结束
        """
        # 找出已关闭的桌子并保存统计
        closed_tables = {
            tid: m for tid, m in self.table_managers.items()
            if m.is_closed or m.exit_requested
        }
        for tid, m in closed_tables.items():
            self._accumulate_table_stats(m)
            print(f"[MANAGER] Table {tid} closed. Stats accumulated.", flush=True)
        
        # 移除已关闭的桌子
        self.table_managers = {
            tid: m for tid, m in self.table_managers.items()
            if not m.is_closed and not m.exit_requested
        }

        for p in self.context.pages:
            try:
                if "/table/" in p.url:
                    table_id = self._extract_table_id(p.url)
                    if table_id and table_id not in self.table_managers:
                        self.add_table_manager(p)
            except Exception:
                pass

        if len(self.table_managers) < self.max_tables:
            if self.auto_mode and not self.apprentice_mode:
                # 获取可用桌子（排除已访问的）
                table_url = await self._get_available_table()
                if table_url:
                    table_id = self._extract_table_id(table_url)
                    if table_id and table_id not in self.table_managers:
                        print(f"[MANAGER] Capacity for more tables. Attempting to join: {table_url}", flush=True)
                        # 记录为已访问
                        self._visited_tables.add(table_id)
                        await self.lobby_manager.open_table(table_url)
                else:
                    # 没有可用桌子
                    if len(self.table_managers) == 0:
                        print("[MANAGER] No available tables and no active tables. Task should end.", flush=True)
                        return False

        await asyncio.sleep(5)

        for p in self.context.pages:
            try:
                if "/table/" in p.url:
                    tid = self._extract_table_id(p.url)
                    if tid and tid not in self.table_managers:
                        self.add_table_manager(p)
            except Exception:
                pass

        for m in list(self.table_managers.values()):
            try:
                await m.execute_turn()
            except Exception as e:
                print(f"[MANAGER] Error in table tick: {e}", flush=True)

        return True

    async def should_stop(self) -> bool:
        """
        检查是否应该停止运行。

        Returns:
            True 如果达到任何退出条件
        """
        if not self.table_managers:
            return False

        # 检查所有牌桌的退出条件
        all_should_exit = True
        for table_id, manager in self.table_managers.items():
            if manager.should_exit():
                print(f"[MANAGER] Table {table_id} reached exit condition.", flush=True)
            else:
                all_should_exit = False

        # 如果所有牌桌都应该退出，则停止
        return all_should_exit and len(self.table_managers) > 0

    def get_statistics(self) -> dict:
        """
        获取运行统计信息（包含已关闭桌子的累计统计）。

        Returns:
            包含统计信息的字典
        """
        stats = {
            "tables_played": self._accumulated_stats["tables_completed"] + len(self.table_managers),
            "strategy": self.preferred_strategy,
            "mode": "auto" if self.auto_mode else ("apprentice" if self.apprentice_mode else "assist"),
        }

        # 从累计统计开始
        total_hands = self._accumulated_stats["total_hands"]
        total_cycles = self._accumulated_stats["total_cycles"]
        total_buyin_added = self._accumulated_stats["total_buyin_added"]
        total_chips = 0
        total_profit = self._accumulated_stats["total_profit"]

        # 加上当前活跃桌子的统计
        for table_id, manager in self.table_managers.items():
            total_hands += manager.hands_played
            total_cycles += manager.dealer_cycle_count
            
            start = manager.starting_stack or 0
            added = manager.added_buyin or 0
            chips = manager.state.total_chips or 0
            
            total_buyin_added += added
            
            if start > 0:
                profit = chips - (start + added)
                total_chips += chips
                total_profit += profit

        stats["total_hands_played"] = total_hands
        stats["total_dealer_cycles"] = total_cycles
        stats["total_buyin_added"] = total_buyin_added
        stats["total_profit"] = total_profit
        stats["total_chips"] = total_chips

        return stats

    async def stop(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
