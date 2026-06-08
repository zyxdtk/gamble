"""
Browser platform implementation.
Implements GamePlatform interface using website adapters.
Supports configuration, login, table selection strategies, and more.
"""
import asyncio
import os
import yaml
from enum import Enum
from typing import Dict, Any, Optional, List, Callable, Set
from dataclasses import dataclass, field
from playwright.async_api import async_playwright, Page, BrowserContext

from ...core.interfaces import GamePlatform, GameState, GameAction
from ...core.events import EventBus
from .adapters import WebsiteAdapter, ReplayPokerAdapter, TableInfo, TableFilter
from .websocket_listener import WebSocketListener
from .state_manager import StateManager
from ...utils.logger import bot_logger


class TableSelectionStrategy(Enum):
    """Strategy for selecting best available table."""
    MOST_PLAYERS = "most_players"  # 选择玩家最多的桌子
    LEAST_PLAYERS = "least_players"  # 选择玩家最少的桌子
    FIFO = "fifo"  # 按列表顺序选择第一个未访问的
    RANDOM = "random"  # 随机选择


@dataclass
class BrowserPlatformConfig:
    """Configuration for BrowserPlatform."""
    
    # 基础配置
    headless: bool = False
    auto_mode: bool = False
    user_data_dir: str = "./data/browser_data"
    
    # 登录配置
    login_requires_manual: bool = True  # 是否需要人工介入
    login_wait_timeout_sec: int = 300  # 登录等待超时时间（秒）
    
    # 牌桌筛选配置
    preferred_stakes: Optional[str] = None  # 优先盲注级别
    min_players: int = 1
    max_players: int = 9
    max_small_blind: Optional[int] = None  # 最大小盲注限制
    max_visited_history: int = 5  # 访问历史记录长度
    
    # 牌桌选择策略
    table_selection_strategy: TableSelectionStrategy = TableSelectionStrategy.FIFO
    
    # 退出阈值（以 BB 为单位）
    stop_loss_bb: Optional[int] = None
    take_profit_bb: Optional[int] = None
    low_chips_bb: Optional[int] = None
    max_chips_bb: Optional[int] = None
    
    # 运行限制
    max_tables: int = 1
    max_hands: Optional[int] = None
    max_cycles: Optional[int] = None
    max_duration_min: Optional[int] = None
    
    # 策略配置
    strategy_type: str = "gto"
    
    @classmethod
    def from_file(cls, config_path: str = "config/settings.yaml") -> 'BrowserPlatformConfig':
        """Load configuration from YAML file."""
        config = cls()
        
        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
            
            # Bot 配置
            bot = data.get("bot", {})
            config.headless = bot.get("headless", False)
            
            # Player 配置
            player = data.get("player", {})
            pass
            
            # Strategy 配置
            strategy = data.get("strategy", {})
            config.strategy_type = strategy.get("type", "gto")
            
            # Game 配置
            game = data.get("game", {})
            config.preferred_stakes = game.get("preferred_stakes")
            config.max_tables = game.get("max_tables", 1)
            config.max_small_blind = game.get("max_small_blind")
            
            # Exit thresholds
            thresholds = game.get("exit_thresholds", {})
            config.stop_loss_bb = thresholds.get("stop_loss_bb")
            config.take_profit_bb = thresholds.get("take_profit_bb")
            config.low_chips_bb = thresholds.get("low_chips_bb")
            config.max_chips_bb = thresholds.get("max_chips_bb")
            
            # Auto mode limits
            auto_mode = data.get("auto_mode", {})
            limits = auto_mode.get("limits", {})
            config.max_hands = limits.get("max_hands")
            config.max_cycles = limits.get("max_cycles")
            config.max_duration_min = limits.get("max_duration_min")
            
        except Exception as e:
            bot_logger.warning(f"Failed to load config from {config_path}: {e}")
        
        # 从环境变量读取（优先级更高）
        config._apply_env_overrides()
        
        return config
    
    def _apply_env_overrides(self):
        """Apply environment variable overrides."""
        env_map = {
            "POKER_STRATEGY": ("strategy_type", str),
            "POKER_MAX_HANDS": ("max_hands", int),
            "POKER_MAX_CYCLES": ("max_cycles", int),
            "POKER_MAX_DURATION_MIN": ("max_duration_min", int),
            "POKER_HEADLESS": ("headless", lambda x: x.lower() in ("true", "1", "yes")),
        }
        
        for env_key, (config_key, converter) in env_map.items():
            env_val = os.environ.get(env_key)
            if env_val is not None:
                try:
                    setattr(self, config_key, converter(env_val))
                except Exception:
                    pass
    
    def to_table_filter(self) -> TableFilter:
        """Convert config to TableFilter."""
        return TableFilter(
            stakes=self.preferred_stakes,
            min_players=self.min_players,
            max_players=self.max_players,
            min_players_waiting=0
        )


class BrowserPlatform(GamePlatform):
    """
    Browser-based poker platform using Playwright and website adapters.
    Supports configuration, login, table selection strategies, and more.
    """
    
    def __init__(
        self,
        adapter: Optional[WebsiteAdapter] = None,
        config: Optional[BrowserPlatformConfig] = None,
    ):
        self.config = config or BrowserPlatformConfig.from_file()
        self.adapter = adapter or ReplayPokerAdapter(
            preferred_stakes=self.config.preferred_stakes or "1/2"
        )
        self.headless = self.config.headless
        self.auto_mode = self.config.auto_mode
        
        # 设置适配器的访问历史长度
        self.adapter._max_visited_history = self.config.max_visited_history
        
        # Playwright 对象
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.lobby_page: Optional[Page] = None
        self.table_pages: Dict[str, Page] = {}  # table_id -> Page
        
        # 事件总线
        self.event_bus = EventBus()
        
        # 双通道状态管理（WebSocket + DOM）
        self._ws_listener: Optional[WebSocketListener] = None
        self._state_manager: Optional[StateManager] = None
        
        # 状态
        self._is_initialized = False
        self._is_logged_in = False
        self._running = False
        self._start_time: Optional[float] = None
        
        # 统计信息
        self._visited_tables: List[str] = []  # FIFO 访问历史
    
    async def initialize(self, **kwargs) -> None:
        """Initialize the browser platform."""
        if self._is_initialized:
            return
        
        bot_logger.info(f"Initializing {self.adapter.get_name()} browser platform...")
        
        # 创建用户数据目录
        os.makedirs(self.config.user_data_dir, exist_ok=True)
        bot_logger.info(f"User data directory: {self.config.user_data_dir}")
        
        # 启动 Playwright
        self.playwright = await async_playwright().start()
        
        # 创建持久化上下文（保持登录状态）
        self.context = await self.playwright.chromium.launch_persistent_context(
            self.config.user_data_dir,
            headless=self.headless,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        # 获取或创建大厅页面
        self.lobby_page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        
        self._is_initialized = True
        bot_logger.info("Browser platform initialized.")
    
    async def ensure_logged_in(
        self,
        on_login_prompt: Optional[Callable] = None
    ) -> bool:
        """Ensure user is logged in.
        
        Args:
            on_login_prompt: Callback when manual login is required.
                If None and login_requires_manual is True, logs a message.
        
        Returns:
            True if logged in (or no login needed)
        """
        if not self._is_initialized:
            await self.initialize()
        
        # 检查是否已经在登录状态（通过检查是否已在大厅或牌桌）
        # 如果用户数据目录有保存的 cookie，可能已经登录了
        if await self.adapter.is_at_lobby(self.lobby_page):
            # 尝试通过页面状态判断是否登录
            if await self._check_logged_in():
                self._is_logged_in = True
                bot_logger.info("Already logged in (session restored).")
                return True
        
        # 导航到大厅
        if not await self.adapter.is_at_lobby(self.lobby_page):
            await self.lobby_page.goto(
                self.adapter.get_lobby_url(),
                wait_until="domcontentloaded",
                timeout=60000
            )
        
        # 检查是否需要手动登录
        if self.config.login_requires_manual:
            if on_login_prompt:
                await on_login_prompt()
            else:
                bot_logger.info("Manual login required. Please log in in the browser.")
            
            # 等待登录完成
            return await self._wait_for_login()
        else:
            # TODO: 实现自动登录（如果支持）
            return await self._check_logged_in()
    
    async def _check_logged_in(self) -> bool:
        """Check if user is logged in (adapter-specific)."""
        # 简单检查：看能否获取可用桌子或有没有登录按钮
        try:
            # 如果能获取桌子，说明已登录
            tables = await self.adapter.get_available_tables(self.lobby_page, self.config.to_table_filter())
            return len(tables) > 0
        except Exception:
            return False
    
    async def _wait_for_login(self) -> bool:
        """Wait for manual login completion."""
        bot_logger.info(f"Waiting for login... (timeout: {self.config.login_wait_timeout_sec}s)")
        
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < self.config.login_wait_timeout_sec:
            if await self._check_logged_in():
                self._is_logged_in = True
                bot_logger.info("Login detected!")
                return True
            await asyncio.sleep(2)
        
        bot_logger.error("Login timeout!")
        return False
    
    async def get_available_tables(self) -> List[TableInfo]:
        """Get list of available tables (filtered by config)."""
        if not self._is_initialized:
            await self.initialize()
        
        return await self.adapter.get_available_tables(
            self.lobby_page,
            self.config.to_table_filter()
        )
    
    async def select_best_table(
        self,
        tables: Optional[List[TableInfo]] = None,
        strategy: Optional[TableSelectionStrategy] = None
    ) -> Optional[TableInfo]:
        """Select the best available table using the configured strategy.
        
        Args:
            tables: List of tables to choose from (gets new list if None)
            strategy: Override strategy (uses config if None)
        
        Returns:
            Best table or None
        """
        if tables is None:
            tables = await self.get_available_tables()
        
        if not tables:
            return None
        
        strategy = strategy or self.config.table_selection_strategy
        
        # 过滤掉已访问的桌子
        available = []
        for table in tables:
            if table.table_id is None or not self.adapter.is_table_visited(table.table_id):
                available.append(table)
        
        if not available:
            bot_logger.warning("All available tables were visited recently.")
            # 返回第一个（不排除已访问）
            return tables[0]
        
        # 根据策略选择
        if strategy == TableSelectionStrategy.MOST_PLAYERS:
            available.sort(key=lambda t: t.players, reverse=True)
        elif strategy == TableSelectionStrategy.LEAST_PLAYERS:
            available.sort(key=lambda t: t.players)
        elif strategy == TableSelectionStrategy.RANDOM:
            import random
            random.shuffle(available)
        # FIFO: 保持原顺序
        
        return available[0]
    
    async def open_table(
        self,
        table_url: Optional[str] = None,
        table_info: Optional[TableInfo] = None
    ) -> Optional[str]:
        """Open a table and return table_id.
        
        Args:
            table_url: Direct URL to open
            table_info: TableInfo object to open
        
        Returns:
            Table ID or None
        """
        if not self._is_initialized:
            await self.initialize()
        
        if table_url is None and table_info is not None:
            table_url = table_info.url
        elif table_url is None:
            # 选择最佳桌子
            best = await self.select_best_table()
            if best:
                table_url = best.url
                table_info = best
            else:
                bot_logger.warning("No table available to open.")
                return None
        
        # 在新标签页中打开牌桌
        table_page = await self.context.new_page()

        # ⚠️ 必须在页面加载前注册 WS 监听器！
        # 页面加载时会建立 WebSocket 连接，如果此时监听器还没注册就会错过
        await self._ensure_state_manager(table_page)

        success = await self.adapter.open_table(table_page, table_url)

        if not success:
            await table_page.close()
            return None

        # 提取桌子 ID 并记录
        table_id = self.adapter.extract_table_id(table_url)

        if table_id:
            self.table_pages[table_id] = table_page
            self.adapter.mark_table_visited(table_id)
            bot_logger.info(f"Opened table: {table_id}")

        return table_id
    
    async def try_sit_down(
        self,
        table_id: Optional[str] = None,
        buyin_amount: Optional[int] = None,
        auto_seat: bool = True
    ) -> bool:
        """Try to sit down at a table.
        
        Args:
            table_id: Table to sit at (uses first active table if None)
            buyin_amount: Buy-in amount
            auto_seat: Try auto-seat
        
        Returns:
            True if successful
        """
        page = self._get_table_page(table_id)
        if not page:
            return False
        
        return await self.adapter.try_sit_down(page, buyin_amount, auto_seat)
    
    async def sit_in(self, table_id: Optional[str] = None) -> bool:
        """Sit in from sitting out state.

        Args:
            table_id: Table to sit in (uses first active table if None)

        Returns:
            True if successful
        """
        page = self._get_table_page(table_id)
        if not page:
            return False

        return await self.adapter.sit_in(page)

    async def sit_out(self, table_id: Optional[str] = None) -> bool:
        """Sit out from the current hand.

        Args:
            table_id: Table to sit out at (uses first active table if None)

        Returns:
            True if successful
        """
        page = self._get_table_page(table_id)
        if not page:
            return False

        return await self.adapter.sit_out(page)

    async def add_chips(
        self,
        amount: Optional[int] = None,
        table_id: Optional[str] = None
    ) -> bool:
        """Add chips while seated at the table.

        Args:
            amount: Amount to add (uses default if None)
            table_id: Table to add chips at (uses first active table if None)

        Returns:
            True if successful
        """
        page = self._get_table_page(table_id)
        if not page:
            return False

        return await self.adapter.add_chips(page, amount)
    
    async def leave_table(
        self,
        table_id: Optional[str] = None,
        close_page: bool = True
    ) -> None:
        """Leave a table.
        
        Args:
            table_id: Table to leave (leaves first if None)
            close_page: Whether to close the page
        """
        page = self._get_table_page(table_id)
        if not page:
            return
        
        if table_id is None:
            # 找到 page 对应的 table_id
            for tid, p in self.table_pages.items():
                if p == page:
                    table_id = tid
                    break
        
        await self.adapter.leave_table(page)
        
        if close_page and table_id and table_id in self.table_pages:
            await self.table_pages[table_id].close()
            del self.table_pages[table_id]
    
    def _get_table_page(self, table_id: Optional[str] = None) -> Optional[Page]:
        """Get page for a specific table (or first page)."""
        if table_id and table_id in self.table_pages:
            return self.table_pages[table_id]
        elif self.table_pages:
            return next(iter(self.table_pages.values()))
        return None
    
    async def _ensure_state_manager(self, page: Page) -> StateManager:
        """确保 StateManager 已初始化且绑定到正确的 page"""
        if self._state_manager is None:
            self._state_manager = StateManager(page)
            await self._state_manager.initialize()
        elif self._state_manager.page != page:
            await self._state_manager.shutdown()
            self._state_manager = StateManager(page)
            await self._state_manager.initialize()
        return self._state_manager

    async def _get_merged_state(self, page: Page) -> Dict[str, Any]:
        """获取双通道合并状态（内部辅助方法）"""
        mgr = await self._ensure_state_manager(page)
        return await mgr.update_state()
    
    def is_healthy(self) -> bool:
        """检查双通道是否健康"""
        if self._state_manager:
            return self._state_manager.is_healthy()
        return False
    
    def get_channel_status(self) -> Dict[str, bool]:
        """获取各通道状态"""
        if self._state_manager:
            return self._state_manager.get_channel_status()
        return {"websocket": False, "dom": False}
    
    async def get_game_state(self, table_id: Optional[str] = None) -> GameState:
        """Get game state for a table (双通道：WebSocket + DOM)."""
        if not self._is_initialized:
            raise RuntimeError("Platform not initialized")

        page = self._get_table_page(table_id)
        if not page:
            from ...strategies.game_state import GameState as PokerGameState
            return PokerGameState()

        # 使用双通道状态管理器
        await self._ensure_state_manager(page)
        merged_state = await self._state_manager.update_state()
        
        from ...strategies.game_state import GameState as PokerGameState
        state = PokerGameState()

        state.pot = merged_state.get("pot", 0)
        state.pot_rake = merged_state.get("pot_rake", 0)
        state.rake = merged_state.get("rake", 0)
        state.community_cards = merged_state.get("community_cards", [])
        state.my_seat_id = merged_state.get("my_seat_id")
        state.to_call = merged_state.get("to_call", 0)
        state.min_raise = merged_state.get("min_raise", 0)
        state.hole_cards = merged_state.get("hole_cards", [])

        # 填充玩家状态
        from ...strategies.game_state import Player
        ws_players = merged_state.get("players", {})
        for seat_id_str, p_data in ws_players.items():
            try:
                seat_id = int(seat_id_str)
            except (ValueError, TypeError):
                continue
            player = Player(
                seat_id=seat_id,
                name=p_data.get("name", ""),
                chips=p_data.get("chips", 0),
                status=p_data.get("status", "active"),
                is_acting=p_data.get("is_acting", False),
            )
            if p_data.get("cards"):
                player.last_action = f"cards={p_data['cards']}"
            state.players[seat_id] = player

        # is_my_turn 由双通道合并决定
        is_my_turn = merged_state.get("is_my_turn", False)
        if is_my_turn and state.my_seat_id is not None:
            if state.my_seat_id not in state.players:
                state.players[state.my_seat_id] = Player(seat_id=state.my_seat_id)
            state.players[state.my_seat_id].is_acting = True
            state.active_seat = state.my_seat_id
        
        return state
    
    async def get_available_actions(self, table_id: Optional[str] = None) -> Dict[str, Any]:
        """Get available actions for a table (双通道校验，WS 优先快速路径)."""
        page = self._get_table_page(table_id)
        if not page:
            return {"available": []}

        # 快速路径：直接从 WS 状态判断是否轮到我（无需完整 DOM 更新）
        ws_state = self._state_manager.ws_listener.get_state() if self._state_manager else {}
        is_my_turn_ws = ws_state.get("is_my_turn", False)

        if not is_my_turn_ws:
            # WS 没说轮到我，再用合并状态确认一次
            merged_state = await self._get_merged_state(page)
            if not merged_state.get("is_my_turn", False):
                return {"available": [], "to_call": 0, "min_raise": 0, "presets": {}}
            ws_state = merged_state

        # 获取 DOM 按钮（现在有超时保护）
        dom_actions = await self.adapter.get_available_actions(page)
        result = self._validate_actions_with_ws(dom_actions, ws_state)

        # 关键回退：如果 DOM 没拿到按钮但 WS 确认轮到我，用 WS 数据构造动作
        if not result.get("available") and is_my_turn_ws:
            result = self._build_actions_from_ws(ws_state)
            bot_logger.debug(f"DOM 按钮为空，使用 WS 回退动作: {result}")

        return result

    async def get_all_visible_actions(self, table_id: Optional[str] = None) -> Dict[str, Any]:
        """Get all visible actions on the page (bypasses turn check, for CLI)."""
        page = self._get_table_page(table_id)
        if not page:
            return {"available": []}

        # 获取 DOM 按钮
        dom_actions = await self.adapter.get_available_actions(page)

        # 用 WS 状态校验金额（即使不是自己的回合也校验）
        try:
            merged_state = await self._get_merged_state(page)
            return self._validate_actions_with_ws(dom_actions, merged_state)
        except Exception:
            return dom_actions

    def _validate_actions_with_ws(
        self, dom_actions: Dict[str, Any], ws_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """用 WS 状态校验 DOM 提取的动作金额"""
        result = dom_actions.copy()

        # WS 的 to_call 更可靠（来自结构化消息），如果 WS 有值则覆盖 DOM 的
        ws_to_call = ws_state.get("to_call", 0)
        dom_to_call = dom_actions.get("to_call", 0)
        if ws_to_call > 0 and dom_to_call != ws_to_call:
            bot_logger.debug(
                f"to_call 校验: WS={ws_to_call}, DOM={dom_to_call}, 使用 WS 值"
            )
            result["to_call"] = ws_to_call
        elif dom_to_call == 0 and ws_to_call > 0:
            # DOM 没提取到但 WS 有值
            result["to_call"] = ws_to_call

        # WS 的 min_raise 更可靠
        ws_min_raise = ws_state.get("min_raise", 0)
        dom_min_raise = dom_actions.get("min_raise", 0)
        if ws_min_raise > 0 and dom_min_raise != ws_min_raise:
            bot_logger.debug(
                f"min_raise 校验: WS={ws_min_raise}, DOM={dom_min_raise}, 使用 WS 值"
            )
            result["min_raise"] = ws_min_raise
        elif dom_min_raise == 0 and ws_min_raise > 0:
            result["min_raise"] = ws_min_raise

        return result

    def _build_actions_from_ws(self, ws_state: Dict[str, Any]) -> Dict[str, Any]:
        """当 DOM 按钮提取失败时，从 WS 状态构造可用动作"""
        actions = {
            "available": [],
            "to_call": 0,
            "min_raise": 0,
            "presets": {},
        }

        to_call = ws_state.get("to_call", 0)
        min_raise = ws_state.get("min_raise", 0)

        # 基本动作：总是可以 fold
        actions["available"].append("fold")

        if to_call == 0:
            # 不需要跟注 → 可以 check
            actions["available"].append("check")
        else:
            # 需要跟注 → 可以 call
            actions["available"].append("call")
            actions["to_call"] = to_call

        if min_raise > 0:
            actions["available"].append("raise")
            actions["min_raise"] = min_raise

        return actions
    
    async def execute_action(
        self,
        action: GameAction,
        table_id: Optional[str] = None
    ) -> bool:
        """Execute a game action."""
        if not self._is_initialized:
            raise RuntimeError("Platform not initialized")
        
        page = self._get_table_page(table_id)
        if not page:
            return False
        
        action_name = action.action_type.value
        amount = getattr(action, "amount", None)
        preset = getattr(action, "bet_size_hint", None)
        
        success = await self.adapter.execute_action(page, action_name, amount, preset)
        
        if success:
            bot_logger.info(f"Executed action: {action_name}")
        
        return success
    
    async def start_game(self, **kwargs) -> bool:
        """Start playing - ensure logged in, get a table, sit down."""
        if not self._is_initialized:
            await self.initialize()
        
        # 确保已登录
        if not self._is_logged_in:
            logged_in = await self.ensure_logged_in()
            if not logged_in:
                return False
        
        # 打开牌桌
        table_id = await self.open_table()
        if not table_id:
            return False
        
        # 尝试入座
        from .human_delay import human_delay
        await human_delay("action")
        await self.try_sit_down(table_id)
        
        return True
    
    async def navigate_to_lobby(self) -> None:
        """Navigate to lobby."""
        if not self._is_initialized:
            await self.initialize()
        
        if not await self.adapter.is_at_lobby(self.lobby_page):
            await self.lobby_page.goto(
                self.adapter.get_lobby_url(),
                wait_until="domcontentloaded"
            )
    
    async def stop(self) -> None:
        """Stop the platform and clean up."""
        await self.shutdown()
    
    async def _dismiss_overlays(self, table_id: Optional[str] = None):
        """检测并关闭常见弹窗/覆盖层（断线重连、满员提示等）"""
        page = self._get_table_page(table_id)
        if not page or page.is_closed():
            return

        try:
            # 处理 "I'm back" / "Sit in" / "Resume" 按钮
            import re
            for btn_text in ["I'm back", "Sit in", "Resume"]:
                btn = page.get_by_role("button", name=re.compile(btn_text, re.I)).first
                if await btn.count() > 0 and await btn.is_visible():
                    bot_logger.info(f"关闭覆盖层: {btn_text}")
                    await btn.click()
                    await asyncio.sleep(1)

            # 处理通用模态框关闭按钮
            for selector in [".Modal__close", ".Button--dismiss"]:
                close_btn = page.locator(selector).first
                if await close_btn.count() > 0 and await close_btn.is_visible():
                    bot_logger.info(f"关闭弹窗: {selector}")
                    await close_btn.click()
                    await asyncio.sleep(0.5)
        except Exception as e:
            bot_logger.debug(f"弹窗处理异常（可忽略）: {e}")

    async def _ensure_ws_alive(self, table_id: Optional[str] = None):
        """确保 WebSocket 连接健康，不健康时刷新页面重连"""
        if not self._state_manager:
            return

        if self._state_manager.ws_listener.is_healthy():
            return

        bot_logger.warning("WS 连接不健康，尝试刷新页面重连...")
        page = self._get_table_page(table_id)
        if not page or page.is_closed():
            return

        try:
            await page.reload(wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # 重新初始化状态管理器
            if self._state_manager:
                await self._state_manager.shutdown()
                self._state_manager = StateManager(page)
                await self._state_manager.initialize()
                bot_logger.info("WS 重连成功")
        except Exception as e:
            bot_logger.error(f"WS 重连失败: {e}")

    async def _auto_sit_in(self, table_id: Optional[str] = None, buyin_amount: Optional[int] = None):
        """检测买入弹窗，选择筹码量，点击确认"""
        page = self._get_table_page(table_id)
        if not page or page.is_closed():
            return False

        try:
            import re
            # 检测买入弹窗
            modal = page.locator(".BuyInModal, .BuyinModal, .ModalOverlay").first
            if await modal.count() == 0 or not await modal.is_visible():
                return False

            bot_logger.info("检测到买入弹窗，执行自动买入...")

            # 设置买入金额（如果有指定）
            if buyin_amount:
                await self.adapter.set_buyin_amount(page, buyin_amount)

            # 确认买入
            confirmed = await self.adapter.confirm_buyin(page)
            if confirmed:
                bot_logger.info("买入确认成功")
                await asyncio.sleep(2)
                return True
            else:
                bot_logger.warning("买入确认失败")
                return False
        except Exception as e:
            bot_logger.error(f"自动入座异常: {e}")
            return False

    async def _check_and_sit_in(self, table_id: Optional[str] = None, buyin_amount: Optional[int] = None):
        """检测是否需要入座/买入，如果是则执行"""
        page = self._get_table_page(table_id)
        if not page or page.is_closed():
            return False

        # 1. 检查买入弹窗
        if await self._auto_sit_in(table_id, buyin_amount):
            return True

        # 2. 检查 "Seat Me Anywhere" 按钮
        try:
            import re
            seat_any = page.get_by_role("button", name=re.compile("Seat me anywhere", re.I)).first
            if await seat_any.count() > 0 and await seat_any.is_visible():
                bot_logger.info("点击 'Seat Me Anywhere'")
                await seat_any.click()
                await asyncio.sleep(1)
                # 点击后再检查买入弹窗
                if await self._auto_sit_in(table_id, buyin_amount):
                    return True
        except Exception:
            pass

        # 3. 检查空座位
        try:
            empty_seat = page.locator(".Seat--empty, .Seat--open").first
            if await empty_seat.count() > 0 and await empty_seat.is_visible():
                bot_logger.info("点击空座位")
                await empty_seat.click()
                await asyncio.sleep(1)
                if await self._auto_sit_in(table_id, buyin_amount):
                    return True
        except Exception:
            pass

        # 4. 检查 Sit in 按钮（从 sit out 状态回来）
        try:
            sit_in_result = await self.adapter.sit_in(page)
            if sit_in_result:
                return True
        except Exception:
            pass

        return False

    async def shutdown(self) -> None:
        """Clean up and shut down the platform."""
        self._running = False
        
        # 关闭双通道状态管理器
        if self._state_manager:
            await self._state_manager.shutdown()
            self._state_manager = None
        
        # 关闭所有牌桌页面
        for page in self.table_pages.values():
            try:
                await page.close()
            except Exception:
                pass
        self.table_pages.clear()
        
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        
        self._is_initialized = False
        self._is_logged_in = False
        bot_logger.info("Browser platform stopped.")
    
    def subscribe_events(self, callback) -> None:
        """Subscribe to game events."""
        self._event_callback = callback
    
    async def wait_for_my_turn(self, timeout: float = 300.0) -> bool:
        """Wait until it's our turn to act. Returns False on timeout."""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                actions = await self.get_available_actions()
                if actions.get("available"):
                    return True
            except Exception:
                pass
            
            await asyncio.sleep(1)
        
        bot_logger.warning("wait_for_my_turn timeout!")
        return False
    
    async def wait_for_hand_start(self, timeout: float = 300.0) -> bool:
        """Wait for a new hand to start. Returns False on timeout."""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                state = await self.get_game_state()
                if state.hole_cards:
                    return True
            except Exception:
                pass
            
            await asyncio.sleep(2)
        
        bot_logger.warning("wait_for_hand_start timeout!")
        return False
