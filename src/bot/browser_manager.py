from __future__ import annotations
import asyncio
import os
import re
import yaml
from playwright.async_api import async_playwright
from .lobby_manager import LobbyManager
from .table_manager import TableManager
from ..utils.logger import bot_logger


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

        # 已访问的桌子记录（仅保留最近 5 张以防锁死，FIFO 队列）
        self._visited_tables: list[str] = []

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
                self.preferred_stakes = config.get("game", {}).get("preferred_stakes", "1/2")
        except Exception:
            self.preferred_stakes = "1/2"
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
        bot_logger.info("你好，同学！正在启动浏览器管理器...")
        self.playwright = await async_playwright().start()
        bot_logger.info("Playwright 引擎已启动。")

        user_data_dir = "./data/browser_data"
        os.makedirs(user_data_dir, exist_ok=True)

        bot_logger.info(f"正在启动浏览器，数据目录: {user_data_dir}")
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir,
            headless=self.headless,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        bot_logger.info("浏览器上下文已就绪。")

        self.context.on("page", self.on_page_created)

        lobby_page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.lobby_manager = LobbyManager(lobby_page, preferred_stakes=self.preferred_stakes)

        if lobby_page.url == "about:blank":
            bot_logger.info("正在导航至 Replay Poker 大厅...")
            await lobby_page.goto("https://www.casino.org/replaypoker/lobby/rings", wait_until="domcontentloaded", timeout=60000)

        bot_logger.info(f"浏览器管理器初始化完成。最大桌数: {self.max_tables}")

    @staticmethod
    def _extract_table_id(url: str) -> str | None:
        m = re.search(r'/(?:play/)?table/([\d]+)', url)
        return m.group(1) if m else None

    async def _get_available_table(self) -> str | None:
        """
        获取可用的桌子 URL（从候选列表中排除最近访问过的）。
        """
        all_urls = await self.lobby_manager.get_all_available_tables()
        if not all_urls:
            return None
            
        for table_url in all_urls:
            table_id = self._extract_table_id(table_url)
            # 如果桌子没访问过，或者是无法提取 ID 的特殊 URL，直接返回
            if not table_id or table_id not in self._visited_tables:
                return table_url
            else:
                bot_logger.info(f"桌子 {table_id} 属于最近访问过的记录，尝试下一个候选...")
                
        bot_logger.warning(f"当前大厅可见的所有桌子 ({len(all_urls)} 张) 都在最近的 5 次访问记录中。")
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
        bot_logger.info(f"检测到新牌桌标签页 (ID={table_id}): {url}")
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
        
        bot_logger.info(
            f"🏁 牌桌统计汇总:\n"
            f"   - 桌子 ID: {table_id}\n"
            f"   - 手数: {manager.hands_played}, 轮次: {manager.dealer_cycle_count}\n"
            f"   - 初始筹码: {start_chips}, 追加买入: {added_buyin}, 最终筹码: {current_chips}\n"
            f"   - 本桌盈利: {profit:+d}\n"
            f"   - 累计总盈利: {self._accumulated_stats['total_profit']:+d}"
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
            bot_logger.info(f"牌桌 {tid} 已关闭，统计数据已归档。")
        
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
                        bot_logger.info(f"当前有空位，尝试加入牌桌: {table_url}")
                        # 记录为已访问 (FIFO 队列，维持 5 条记录)
                        self._visited_tables.append(table_id)
                        if len(self._visited_tables) > 5:
                            self._visited_tables.pop(0)
                        await self.lobby_manager.open_table(table_url)
                else:
                    # 没有可用桌子
                    if len(self.table_managers) == 0:
                        bot_logger.info("当前无可用桌子且无活跃牌桌，任务结束。")
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
                bot_logger.error(f"牌桌执行出错: {e}")

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
