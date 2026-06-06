"""
双通道状态管理器
结合 WebSocket 和 DOM 两种数据源，相互校验提高可靠性
这是 src/platforms/browser 的核心组件，供所有上层调用（包括 CLI 测试和未来的 src/core）
"""
import asyncio
from typing import Dict, Any, Optional
from playwright.async_api import Page
from .websocket_listener import WebSocketListener
from .adapters.replay_poker import ReplayPokerAdapter
from src.utils.logger import bot_logger


class StateManager:
    """
    双通道状态管理器
    
    工作原理：
    1. WebSocket 通道：实时、准确、结构化（主要数据源）
    2. DOM 通道：补充、验证、回退（辅助数据源）
    3. 智能合并：优先使用 WS，用 DOM 补充缺失字段
    
    这是 src/platforms/browser 的标准组件，可被：
    - CLI 测试工具调用
    - 未来的 src/core 直接对接
    """
    
    def __init__(self, page: Page):
        self.page = page
        self.ws_listener = WebSocketListener(page)
        self.dom_adapter = ReplayPokerAdapter()
        
        # 合并后的状态
        self.merged_state: Dict[str, Any] = {
            "pot": 0,
            "community_cards": [],
            "hole_cards": [],
            "my_seat_id": None,
            "is_my_turn": False,
            "to_call": 0,
            "min_raise": 0,
            "available_actions": [],
            "players": {},
        }
        
        self._is_initialized = False
    
    async def initialize(self):
        """初始化双通道"""
        if self._is_initialized:
            return
        
        # 启动 WebSocket 监听
        await self.ws_listener.start_listening()
        
        self._is_initialized = True
        bot_logger.info("✅ State manager initialized (dual-channel)")
    
    async def shutdown(self):
        """关闭双通道"""
        self.ws_listener.stop_listening()
        self._is_initialized = False
        bot_logger.info("⏹️ State manager shutdown")
    
    async def update_state(self) -> Dict[str, Any]:
        """
        更新并返回合并后的状态
        
        策略：
        1. 从 WebSocket 获取基础状态
        2. 从 DOM 提取补充信息（按钮、金额等）
        3. 智能合并，优先使用 WS 的准确数据
        """
        if not self._is_initialized:
            await self.initialize()
        
        # 1. 获取 WebSocket 状态
        ws_state = self.ws_listener.get_state()
        
        # 2. 从 DOM 提取补充信息
        dom_state = await self._extract_dom_state()
        
        # 3. 智能合并
        merged = self._merge_states(ws_state, dom_state)
        
        self.merged_state = merged
        return merged
    
    async def _extract_dom_state(self) -> Dict[str, Any]:
        """从 DOM 提取补充状态"""
        state = {
            "available_actions": [],
            "to_call": 0,
            "min_raise": 0,
            "pot_from_dom": 0,
        }
        
        try:
            # 提取可用按钮
            buttons = await self.dom_adapter.get_available_actions(self.page)
            state["available_actions"] = buttons.get("available", [])
            state["to_call"] = buttons.get("to_call", 0)
            state["min_raise"] = buttons.get("min_raise", 0)
            
            # 提取底池（作为校验）
            pot_elem = self.page.locator(".Stack__value span").first
            if await pot_elem.count() > 0:
                pot_text = await pot_elem.text_content(timeout=500)
                if pot_text:
                    import re
                    val = re.sub(r"[^\d]", "", pot_text)
                    if val:
                        state["pot_from_dom"] = int(val)
        
        except Exception as e:
            bot_logger.debug(f"DOM extraction error: {e}")
        
        return state
    
    def _merge_states(self, ws_state: Dict, dom_state: Dict) -> Dict[str, Any]:
        """
        智能合并 WebSocket 和 DOM 状态
        
        优先级规则：
        - WebSocket: community_cards, hole_cards, my_seat_id, is_my_turn, pot
        - DOM: available_actions, to_call, min_raise（从按钮提取更准确）
        - 校验：如果 WS 和 DOM 的 pot 差异过大，记录警告
        """
        merged = {
            # WebSocket 优先（准确的结构化数据）
            "community_cards": ws_state.get("community_cards", []),
            "hole_cards": ws_state.get("hole_cards", []),
            "my_seat_id": ws_state.get("my_seat_id"),
            "is_my_turn": ws_state.get("is_my_turn", False),
            "players": ws_state.get("players", {}),
            "current_stage": ws_state.get("current_stage", ""),
            
            # DOM 补充（按钮相关）
            "available_actions": dom_state.get("available_actions", []),
            "to_call": dom_state.get("to_call", 0),
            "min_raise": dom_state.get("min_raise", 0),
            
            # 底池：优先使用 WS，但用 DOM 校验
            "pot": ws_state.get("pot", 0),
        }
        
        # 校验底池
        pot_ws = ws_state.get("pot", 0)
        pot_dom = dom_state.get("pot_from_dom", 0)
        
        if pot_ws > 0 and pot_dom > 0:
            diff = abs(pot_ws - pot_dom)
            if diff > max(pot_ws, pot_dom) * 0.1:  # 差异超过 10%
                bot_logger.warning(
                    f"⚠️ Pot mismatch: WS={pot_ws}, DOM={pot_dom}, diff={diff}"
                )
                # 仍然使用 WS 的值，因为它更可靠
        
        # 如果没有 WS 的底池数据，使用 DOM 的
        if merged["pot"] == 0 and pot_dom > 0:
            merged["pot"] = pot_dom
            bot_logger.debug("Using pot from DOM (WS has no data)")
        
        # 如果 WS 没有判断出 is_my_turn，但有可用按钮，则认为轮到我
        if not merged["is_my_turn"] and merged["available_actions"]:
            merged["is_my_turn"] = True
            bot_logger.debug("Inferred is_my_turn=True from available actions")
        
        return merged
    
    def get_state(self) -> Dict[str, Any]:
        """获取当前合并状态"""
        return self.merged_state.copy()
    
    def is_healthy(self) -> bool:
        """检查双通道是否健康"""
        return self.ws_listener.is_healthy()
    
    def get_channel_status(self) -> Dict[str, bool]:
        """获取各通道状态"""
        return {
            "websocket": self.ws_listener.is_healthy(),
            "dom": True,  # DOM 总是可用的
        }
    
    def reset_for_new_hand(self):
        """为新手牌重置状态"""
        self.ws_listener.reset_for_new_hand()
        bot_logger.debug("Dual-channel state reset for new hand")
