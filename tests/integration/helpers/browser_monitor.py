# tests/integration/helpers/browser_monitor.py
"""
浏览器状态监听器。

用于在集成测试中监听浏览器状态变化，如：
- 页面加载状态
- WebSocket 连接状态
- 牌桌元素变化
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Dict, Any


@dataclass
class BrowserState:
    """浏览器状态快照。"""
    timestamp: float
    url: str
    is_table_page: bool = False
    table_id: Optional[str] = None
    is_sitting: bool = False
    total_chips: int = 0
    pot: int = 0
    available_actions: List[str] = field(default_factory=list)
    dealer_seat: Optional[int] = None
    my_seat: Optional[int] = None


class BrowserMonitor:
    """
    浏览器状态监听器。

    通过轮询或事件监听的方式，捕获浏览器状态变化。
    """

    def __init__(self, poll_interval: float = 1.0):
        self.poll_interval = poll_interval
        self.state_history: List[BrowserState] = []
        self._callbacks: List[Callable[[BrowserState, BrowserState], None]] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def add_state_change_callback(self, callback: Callable[[BrowserState, BrowserState], None]):
        """
        添加状态变化回调函数。

        Args:
            callback: 接收 (old_state, new_state) 两个参数的函数
        """
        self._callbacks.append(callback)

    async def start_monitoring(self, page_getter: Callable[[], Any]):
        """
        开始监控浏览器状态。

        Args:
            page_getter: 返回当前 page 对象的函数
        """
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop(page_getter))

    async def stop_monitoring(self):
        """停止监控。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self, page_getter: Callable[[], Any]):
        """监控循环。"""
        last_state: Optional[BrowserState] = None

        while self._running:
            try:
                page = page_getter()
                if page:
                    current_state = await self._capture_state(page)
                    self.state_history.append(current_state)

                    # 触发状态变化回调
                    if last_state and self._state_changed(last_state, current_state):
                        for callback in self._callbacks:
                            try:
                                callback(last_state, current_state)
                            except Exception as e:
                                print(f"[Monitor] Callback error: {e}")

                    last_state = current_state

            except Exception as e:
                print(f"[Monitor] Error capturing state: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _capture_state(self, page) -> BrowserState:
        """捕获当前浏览器状态。"""
        state = BrowserState(
            timestamp=time.time(),
            url=page.url if hasattr(page, 'url') else "",
        )

        # 判断是否在牌桌页面
        if "/table/" in state.url:
            state.is_table_page = True
            # 提取 table_id
            import re
            match = re.search(r'/table/(\d+)', state.url)
            if match:
                state.table_id = match.group(1)

            # 尝试获取页面状态（通过 JavaScript 或元素检查）
            try:
                # 检查是否已入座
                seat_indicator = await page.locator(".Seat--active, .Seat__username").count()
                state.is_sitting = seat_indicator > 0

                # 获取筹码数
                chips_elem = page.locator(".Stack__value, .Seat__stack").first
                if await chips_elem.count() > 0:
                    chips_text = await chips_elem.text_content()
                    if chips_text:
                        import re
                        digits = re.sub(r"[^\d]", "", chips_text)
                        if digits:
                            state.total_chips = int(digits)

                # 获取底池
                pot_elem = page.locator(".Pot__value").first
                if await pot_elem.count() > 0:
                    pot_text = await pot_elem.text_content()
                    if pot_text:
                        import re
                        digits = re.sub(r"[^\d]", "", pot_text)
                        if digits:
                            state.pot = int(digits)

                # 获取可用动作
                action_buttons = await page.locator(
                    "button:has-text('Fold'), button:has-text('Check'), "
                    "button:has-text('Call'), button:has-text('Raise'), "
                    "button:has-text('Bet')"
                ).count()
                if action_buttons > 0:
                    state.available_actions = ["has_actions"]  # 简化表示

            except Exception:
                pass  # 元素可能不存在

        return state

    def _state_changed(self, old: BrowserState, new: BrowserState) -> bool:
        """检查状态是否有显著变化。"""
        return (
            old.is_sitting != new.is_sitting or
            old.total_chips != new.total_chips or
            old.pot != new.pot or
            old.dealer_seat != new.dealer_seat or
            old.available_actions != new.available_actions
        )

    def get_state_history(self) -> List[BrowserState]:
        """获取状态历史记录。"""
        return self.state_history.copy()

    def get_latest_state(self) -> Optional[BrowserState]:
        """获取最新状态。"""
        return self.state_history[-1] if self.state_history else None
