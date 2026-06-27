"""
双通道状态管理器
结合 WebSocket 和 DOM 两种数据源，相互校验提高可靠性
这是 src/platforms/browser 的核心组件，供所有上层调用（包括 CLI 测试和未来的 src/core）
"""
import asyncio
import time
from typing import Dict, Any, Optional
from playwright.async_api import Page
from .websocket_listener import WebSocketListener
from .adapters.replay_poker import ReplayPokerAdapter
from .snapshot import save_anomaly_snapshot
from src.utils.logger import bot_logger, dom_logger, state_logger


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
        
        # 快照防抖：同一原因 60 秒内不重复保存
        self._last_snapshot_time: Dict[str, float] = {}  # reason -> timestamp
        self._snapshot_cooldown = 60.0  # 秒

        # 合并后的状态
        self.merged_state: Dict[str, Any] = {
            "pot": 0,
            "pot_rake": 0,
            "rake": 0,
            "community_cards": [],
            "hole_cards": [],
            "my_seat_id": None,
            "is_my_turn": False,
            "to_call": 0,
            "min_raise": 0,
            "available_actions": [],
            "players": {},
        }

        # 上一轮合并状态（用于去重日志，避免轮询时重复输出）
        self._prev_merged: Optional[Dict[str, Any]] = None
        # 上一轮字段差异（用于去重，同一差异不重复输出）
        self._prev_diffs: Dict[str, Any] = {}
        
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

        # 保存上一轮状态用于去重日志
        self._prev_merged = self.merged_state.copy()
        self.merged_state = merged
        return merged
    
    async def _extract_dom_state(self) -> Dict[str, Any]:
        """从 DOM 提取补充状态"""
        state = {
            "available_actions": [],
            "to_call": 0,
            "min_raise": 0,
            "pot_from_dom": 0,
            "pot_rake_from_dom": 0,
            "rake_from_dom": 0,
            "community_cards_from_dom": [],
            "my_seat_id_from_dom": None,
            "is_my_turn_from_dom": False,
            "is_seated_from_dom": True,
        }

        try:
            # 提取公共牌（从社区牌区域或聊天消息）
            # 注意：不能使用 .Cards .Card--withValue，因为会匹配手牌的 Card--0/Card--1
            community_cards = []
            import re

            # 方法1: 从社区牌区域提取（仅 Cards__communityCards 内的牌）
            comm_card_elems = self.page.locator(".Cards__communityCards .Card--withValue")
            # 注意: Locator.count() 不支持 timeout 参数，直接调用
            comm_count = await comm_card_elems.count()
            for i in range(comm_count):
                card_class = await comm_card_elems.nth(i).get_attribute("class") or ""
                card_match = re.search(r'Card--([A-Z][a-z])', card_class)
                if card_match:
                    community_cards.append(card_match.group(1))

            # 方法2: 从聊天消息中提取——需要收集最近一手牌的所有 "Dealt to board" 消息
            # 因为 flop 是 [ 6c 3h 4h ]，turn/river 是逐张 [ 6h ], [ 4s ]
            if not community_cards:
                chat_messages = self.page.locator(".ChatMessage--dealer")
                chat_count = await chat_messages.count()
                for i in range(chat_count - 1, -1, -1):
                    msg_text = await chat_messages.nth(i).text_content()
                    if not msg_text:
                        continue
                    # 遇到新手牌开始，停止收集
                    if "Hand [" in msg_text and "started" in msg_text:
                        break
                    if "Dealt to board:" in msg_text:
                        board_match = re.search(r'\[\s*([^\]]+)\s*\]', msg_text)
                        if board_match:
                            cards_in_msg = board_match.group(1).split()
                            # 从后往前追加（因为倒序遍历）
                            community_cards = cards_in_msg + community_cards

            state["community_cards_from_dom"] = community_cards

            # 提取我的座位ID（.Seat--currentUser + Position--N）
            my_seat_elem = self.page.locator(".Seat--currentUser").first
            if await my_seat_elem.count() > 0:
                seat_class = await my_seat_elem.get_attribute("class") or ""
                position_match = re.search(r'Position--(\d+)', seat_class)
                if position_match:
                    state["my_seat_id_from_dom"] = int(position_match.group(1))

            # 判断是否已入座（没有买入弹窗）
            buyin_modal = self.page.locator(".BuyInModal, .BuyinModal")
            is_seated = await buyin_modal.count() == 0
            state["is_seated_from_dom"] = is_seated

            # 判断是否轮到我（已入座 + CurrentPlayerSpotlight--active 在我的座位上）
            if state["my_seat_id_from_dom"] is not None and is_seated:
                active_spotlight = self.page.locator(
                    f".CurrentPlayerSpotlight--active.Position--{state['my_seat_id_from_dom']}"
                )
                if await active_spotlight.count() > 0:
                    state["is_my_turn_from_dom"] = True

            # 提取可用按钮（有超时保护，不再阻塞30秒）
            try:
                buttons = await asyncio.wait_for(
                    self.dom_adapter.get_available_actions(self.page),
                    timeout=5.0
                )
                state["available_actions"] = buttons.get("available", [])
                state["to_call"] = buttons.get("to_call", 0)
                state["min_raise"] = buttons.get("min_raise", 0)
            except asyncio.TimeoutError:
                bot_logger.debug("DOM get_available_actions 超时(5s)，跳过")

            # 提取原始底池（.Pot__value，在页面上方）
            pot_elem = self.page.locator(".Pot__value span").first
            if await pot_elem.count() > 0:
                pot_text = await pot_elem.text_content()
                if pot_text:
                    m = re.search(r'([\d,]+)', pot_text)
                    if m:
                        state["pot_from_dom"] = int(m.group(1).replace(",", ""))

            # 提取抽税后底池（.Stack--pot，在公共牌下方）
            pot_rake_elem = self.page.locator(".Stack--pot .Stack__value span").first
            if await pot_rake_elem.count() > 0:
                pot_rake_text = await pot_rake_elem.text_content()
                if pot_rake_text:
                    m = re.search(r'([\d,]+)', pot_rake_text)
                    if m:
                        state["pot_rake_from_dom"] = int(m.group(1).replace(",", ""))

            # 提取抽税金额（.Stack--rake）
            rake_elem = self.page.locator(".Stack--rake .Stack__value").first
            if await rake_elem.count() > 0:
                rake_text = await rake_elem.text_content()
                if rake_text:
                    m = re.search(r'([\d,]+)', rake_text)
                    if m:
                        state["rake_from_dom"] = int(m.group(1).replace(",", ""))

        except Exception as e:
            bot_logger.debug(f"DOM extraction error: {e}")
            # DOM 提取异常时保存快照（带防抖）
            self._save_snapshot_debounced("dom_extraction_error", {"error": str(e)})

        dom_logger.debug(
            f"[DOM-EXTRACT] actions={state['available_actions']}, "
            f"to_call={state['to_call']}, min_raise={state['min_raise']}, "
            f"pot_from_dom={state['pot_from_dom']}"
        )
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
            # 抽税后底池和抽税金额（仅 DOM 有此信息）
            "pot_rake": dom_state.get("pot_rake_from_dom", 0),
            "rake": dom_state.get("rake_from_dom", 0),
        }

        # --- 字段级差异检测与日志 ---
        self._log_field_diffs(ws_state, dom_state, merged)

        # community_cards 回退：WS 没有公共牌时，用 DOM 的 Cards 区域或聊天消息
        if not merged["community_cards"]:
            dom_cards = dom_state.get("community_cards_from_dom", [])
            if dom_cards:
                merged["community_cards"] = dom_cards
                self._log_once("community_cards_dom", f"Using community_cards from DOM: {dom_cards}")

        # my_seat_id 回退：WS 没识别出座位时，用 DOM 的 Seat--currentUser
        if merged["my_seat_id"] is None:
            dom_my_seat = dom_state.get("my_seat_id_from_dom")
            if dom_my_seat is not None:
                merged["my_seat_id"] = dom_my_seat
                self._log_once("my_seat_id", f"Using my_seat_id from DOM: {dom_my_seat}")

        # is_my_turn 回退：WS 没判断时，用 DOM 的 CurrentPlayerSpotlight--active
        if not merged["is_my_turn"]:
            dom_is_my_turn = dom_state.get("is_my_turn_from_dom", False)
            if dom_is_my_turn:
                merged["is_my_turn"] = True
                self._log_once("is_my_turn_dom", "Using is_my_turn from DOM (CurrentPlayerSpotlight)")

        # 校验底池：WS 的 pot 字段可能只是当前轮下注，DOM 显示的是真实累计底池
        # 底池只会增长，所以取较大值更准确
        # （POT-MISMATCH 日志已移至 _log_field_diffs 统一去重输出）
        pot_ws = ws_state.get("pot", 0)
        pot_dom = dom_state.get("pot_from_dom", 0)

        if pot_ws > 0 and pot_dom > 0 and pot_dom > pot_ws:
            merged["pot"] = pot_dom
            self._log_once("pot_dom_override", f"Using pot from DOM ({pot_dom}), WS pot incomplete ({pot_ws})")

        if merged["pot"] == 0 and pot_dom > 0:
            merged["pot"] = pot_dom
            self._log_once("pot_dom", "Using pot from DOM (WS has no data)")

        # is_my_turn 最终推论：WS 和 DOM 都没判断时，用可用按钮作为最后回退
        # 前提：已入座 + my_seat_id 已知 + 有 DOM 按钮 + WS 没有明确说不是我的回合
        if not merged["is_my_turn"] and merged["available_actions"]:
            is_seated = dom_state.get("is_seated_from_dom", True)
            ws_active_seat = ws_state.get("active_seat")
            if not is_seated:
                # 买入弹窗还在 → 按钮不可信
                pass
            elif ws_active_seat is not None:
                # WS 知道谁是行动者但不是我 → 不是我的回合
                pass
            elif merged["my_seat_id"] is not None:
                # my_seat_id 已知且已入座但无 active_seat 信息 → DOM 按钮作为回退
                merged["is_my_turn"] = True
                self._log_once("is_my_turn_infer", "Inferred is_my_turn=True from available actions")
                state_logger.debug(
                    f"[INFER] is_my_turn=True (from available_actions={merged['available_actions']})"
                )

        # --- 变化时输出合并结果摘要 ---
        self._log_merged_summary(merged)

        return merged

    def _log_once(self, key: str, message: str):
        """仅当状态变化时输出 debug 日志，避免轮询时重复刷屏"""
        prev = self._prev_merged or {}
        current = self.merged_state
        # 简单判断：key 对应的状态值是否变化
        changed = False
        if key in ("pot_dom", "pot_dom_override"):
            changed = prev.get("pot") != current.get("pot")
        elif key == "my_seat_id":
            changed = prev.get("my_seat_id") != current.get("my_seat_id")
        elif key.startswith("is_my_turn"):
            changed = prev.get("is_my_turn") != current.get("is_my_turn")
        else:
            changed = True  # 未知 key 总是输出

        if changed:
            bot_logger.debug(message)

    def _save_snapshot_debounced(self, reason: str, extra: Optional[Dict[str, Any]] = None):
        """带防抖的快照保存：同一原因 60 秒内不重复"""
        now = time.time()
        last = self._last_snapshot_time.get(reason, 0)
        if now - last < self._snapshot_cooldown:
            return
        self._last_snapshot_time[reason] = now
        if self.page and not self.page.is_closed():
            try:
                asyncio.get_event_loop().create_task(
                    save_anomaly_snapshot(self.page, reason, extra=extra)
                )
            except Exception:
                pass

    def _log_field_diffs(self, ws_state: Dict, dom_state: Dict, merged: Dict):
        """检测 WS 和 DOM 之间的关键字段差异，只在差异值变化时输出"""
        diffs = {}

        # my_seat_id 差异
        ws_seat = ws_state.get("my_seat_id")
        dom_seat = dom_state.get("my_seat_id_from_dom")
        if ws_seat is not None and dom_seat is not None and ws_seat != dom_seat:
            diffs["seat"] = (ws_seat, dom_seat)

        # is_my_turn 差异
        ws_my_turn = ws_state.get("is_my_turn", False)
        dom_my_turn = dom_state.get("is_my_turn_from_dom", False)
        if ws_my_turn != dom_my_turn and (ws_my_turn or dom_my_turn):
            diffs["turn"] = (ws_my_turn, dom_my_turn)

        # community_cards 差异
        ws_cards = ws_state.get("community_cards", [])
        dom_cards = dom_state.get("community_cards_from_dom", [])
        if ws_cards and dom_cards and ws_cards != dom_cards:
            diffs["cards"] = (tuple(ws_cards), tuple(dom_cards))

        # to_call 差异
        ws_to_call = ws_state.get("to_call", 0)
        dom_to_call = dom_state.get("to_call", 0)
        if ws_to_call > 0 and dom_to_call > 0 and ws_to_call != dom_to_call:
            diffs["to_call"] = (ws_to_call, dom_to_call)

        # min_raise 差异
        ws_min_raise = ws_state.get("min_raise", 0)
        dom_min_raise = dom_state.get("min_raise", 0)
        if ws_min_raise > 0 and dom_min_raise > 0 and ws_min_raise != dom_min_raise:
            diffs["min_raise"] = (ws_min_raise, dom_min_raise)

        # pot 差异（提前计算，合并逻辑也需要）
        pot_ws = ws_state.get("pot", 0)
        pot_dom = dom_state.get("pot_from_dom", 0)
        if pot_ws > 0 and pot_dom > 0 and pot_dom != pot_ws:
            diffs["pot"] = (pot_ws, pot_dom)

        # 只在差异值变化时输出
        if diffs != self._prev_diffs:
            self._prev_diffs = diffs
            if "seat" in diffs:
                state_logger.warning(
                    f"[SEAT-MISMATCH] WS seat={diffs['seat'][0]}, DOM seat={diffs['seat'][1]} — using WS"
                )
            if "turn" in diffs:
                state_logger.debug(
                    f"[TURN-MISMATCH] WS is_my_turn={diffs['turn'][0]}, DOM={diffs['turn'][1]}"
                )
            if "cards" in diffs:
                state_logger.debug(
                    f"[CARDS-MISMATCH] WS cards={list(diffs['cards'][0])}, DOM={list(diffs['cards'][1])}"
                )
            if "to_call" in diffs:
                state_logger.debug(
                    f"[TOCALL-MISMATCH] WS to_call={diffs['to_call'][0]}, DOM={diffs['to_call'][1]}"
                )
            if "min_raise" in diffs:
                state_logger.debug(
                    f"[MINRAISE-MISMATCH] WS min_raise={diffs['min_raise'][0]}, DOM={diffs['min_raise'][1]}"
                )
            if "pot" in diffs:
                diff_val = abs(diffs["pot"][0] - diffs["pot"][1])
                if diffs["pot"][1] > diffs["pot"][0]:
                    state_logger.warning(
                        f"[POT-MISMATCH] ws={diffs['pot'][0]}, dom={diffs['pot'][1]}, diff={diff_val} — using DOM"
                    )
                else:
                    state_logger.warning(
                        f"[POT-MISMATCH] ws={diffs['pot'][0]}, dom={diffs['pot'][1]}, diff={diff_val} — using WS"
                    )

    def _log_merged_summary(self, merged: Dict):
        """合并结果变化时输出摘要（只在关键字段变化时输出，避免刷屏）"""
        prev = self._prev_merged or {}

        # 只在以下字段变化时输出
        watch_keys = ["pot", "community_cards", "hole_cards", "my_seat_id",
                      "is_my_turn", "to_call", "min_raise", "current_stage"]
        changed = any(merged.get(k) != prev.get(k) for k in watch_keys)

        if not changed:
            return

        state_logger.debug(
            f"[MERGED] pot={merged.get('pot', 0)} "
            f"cards={merged.get('community_cards', [])} "
            f"hole={merged.get('hole_cards', [])} "
            f"seat={merged.get('my_seat_id')} "
            f"my_turn={merged.get('is_my_turn')} "
            f"to_call={merged.get('to_call', 0)} "
            f"min_raise={merged.get('min_raise', 0)} "
            f"stage={merged.get('current_stage', '')} "
            f"actions={merged.get('available_actions', [])}"
        )

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
