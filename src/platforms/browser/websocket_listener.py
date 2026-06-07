"""
WebSocket 状态监听器
用于从 ReplayPoker 的 WebSocket 消息中提取游戏状态
这是 src/platforms/browser 的核心组件，供所有上层调用
"""
import asyncio
import json
import re
from typing import Dict, Any, Optional, Set
from playwright.async_api import Page
from src.utils.logger import bot_logger, ws_raw_logger


class WebSocketListener:
    """
    轻量级 WebSocket 监听器
    不依赖 TableManager，独立运行
    作为 src/platforms/browser 的标准组件
    """
    
    def __init__(self, page: Page):
        self.page = page
        self.state: Dict[str, Any] = {
            "pot": 0,
            "community_cards": [],
            "hole_cards": [],
            "my_seat_id": None,
            "my_user_id": None,
            "active_seat": None,
            "is_my_turn": False,
            "to_call": 0,
            "min_raise": 0,
            "players": {},
            "current_stage": "",
            "hand_id": 0,
            "big_blind": 0,
        }
        
        self._processed_hashes: Set[int] = set()
        self._max_cache_size = 100
        self._last_ws_time = 0
        self._is_listening = False
        self._registered_ws_ids: Set[int] = set()

        # VPIP/PFR 追踪器
        self.state["vpip_tracker"] = {}  # {user_id: {"hands": N, "vpip_count": N, "pfr_count": N}}
        self._current_stage = ""  # 当前阶段，用于判断 preflop

        # 当前街道每名下注额（seat_id -> total bet on this street）
        # 重置时机：startHand（新手牌）/ dealCommunityCards（新街道）
        self._street_bets: Dict[int, int] = {}
    
    async def start_listening(self):
        """启动 WebSocket 监听"""
        if self._is_listening:
            return
        
        self._is_listening = True
        self.page.on("websocket", self._on_websocket)
        bot_logger.info("✅ WebSocket listener started")
    
    def stop_listening(self):
        """停止 WebSocket 监听"""
        self._is_listening = False
        bot_logger.info("⏹️ WebSocket listener stopped")
    
    def _on_websocket(self, ws):
        """注册 WebSocket 事件处理器"""
        ws_id = id(ws)
        if ws_id in self._registered_ws_ids:
            return
        self._registered_ws_ids.add(ws_id)
        ws.on("framereceived", self._handle_ws_frame)
    
    async def _handle_ws_frame(self, frame):
        """处理 WebSocket 帧"""
        try:
            import time
            self._last_ws_time = time.time()

            payload = frame.text if hasattr(frame, 'text') else str(frame)
            # 记录原始帧（截断防止日志爆炸）
            payload_preview = payload if len(payload) <= 2000 else payload[:2000] + f"...[truncated, total {len(payload)} chars]"
            ws_raw_logger.debug(f"[RAW FRAME] ({len(payload)} chars) {payload_preview}")

            if not payload.startswith("["):
                return

            data = json.loads(payload)
            ws_raw_logger.debug(f"[PARSED ENVELOPE] type={data[3] if len(data) > 3 else '?'}")

            if len(data) < 5 or data[3] != "output":
                return

            await self._process_game_message(data[4])
        except Exception as e:
            bot_logger.debug(f"WS frame processing error: {e}")
            ws_raw_logger.error(f"[PARSE ERROR] {e}")
    
    async def _process_game_message(self, data: Dict):
        """处理游戏状态消息"""
        if not isinstance(data, dict):
            return

        # 去重：使用全量内容哈希
        data_str = json.dumps(data, sort_keys=True)
        msg_hash = hash(data_str)

        if msg_hash in self._processed_hashes:
            return
        self._processed_hashes.add(msg_hash)

        if len(self._processed_hashes) > self._max_cache_size:
            self._processed_hashes = set(list(self._processed_hashes)[-self._max_cache_size//2:])

        updates = data.get("updates", [])
        ws_raw_logger.debug(f"[GAME MSG] updates_count={len(updates)}")

        # 优先级排序：startHand 先于 dealHoleCards
        def get_priority(u):
            act = u.get("action", "")
            if act == "startHand":
                return 0
            if act == "dealHoleCards":
                return 1
            return 2

        sorted_updates = sorted(updates, key=get_priority)

        for update in sorted_updates:
            action = update.get("action", "<no-action>")
            # 记录每个 update 的精简摘要
            update_summary = {
                k: update.get(k) for k in ["action", "seat", "seatId", "userId"]
                if k in update
            }
            if "cards" in update:
                update_summary["cards"] = update["cards"]
            if "pot" in update:
                update_summary["pot"] = update["pot"]
            if "communityCards" in update:
                update_summary["communityCards"] = update["communityCards"]
            ws_raw_logger.debug(f"[UPDATE] {json.dumps(update_summary, ensure_ascii=False)}")
            await self._apply_update(update)
    
    async def _apply_update(self, update: Dict):
        """应用单个更新"""
        action = update.get("action")
        
        # --- 1. 全量状态同步 ---
        if "players" in update:
            self._update_players(update.get("players", []))
        
        if "communityCards" in update:
            c_cards = update.get("communityCards", [])
            if isinstance(c_cards, list) and len(c_cards) >= len(self.state["community_cards"]):
                if c_cards != self.state["community_cards"]:
                    self.state["community_cards"] = c_cards
                    bot_logger.debug(f"WS: Community Cards updated: {c_cards}")
        
        # 注意：update 中的 "pot" 单字段可能只是当前轮下注，不是累计总底池
        # 只有当它大于当前已知值时才更新（底池只会增长）
        # 准确的总底池由 updatePots action 从 pots 数组求和得出
        if "pot" in update:
            new_pot = update.get("pot")
            if isinstance(new_pot, (int, float)) and new_pot > self.state["pot"]:
                self.state["pot"] = int(new_pot)
        
        if not action:
            return
        
        # --- 2. 行为动作逻辑 ---
        bot_logger.debug(f"WS Action: {action}")
        
        # 发底牌 - 关键：自动识别自己的座位
        if action in ["deal", "dealCards", "dealHoldCards", "dealHoleCards"]:
            await self._handle_deal_hole_cards(update)
        
        elif action == "dealCommunityCards":
            cards = update.get("cards")
            if isinstance(cards, list) and len(cards) > 0:
                # 累积追加：flop发3张，turn/river各发1张，WS每轮只发新牌
                existing = self.state["community_cards"]
                for card in cards:
                    if card not in existing:
                        existing.append(card)
                self.state["community_cards"] = existing
                bot_logger.info(f"WS: Community Cards updated: {existing}")
                # 新街道：重置本街下注（flop/turn/river 各自从 0 开始算）
                if len(existing) in (3, 4, 5):
                    self._reset_street_bets()
        
        elif action in ["updatePots", "awardPot"]:
            pots = update.get("pots", [])
            self.state["pot"] = sum(p.get("chips", 0) for p in pots)
            if action == "awardPot":
                # 不在此处清空 community_cards，边池场景下会连续触发多次 awardPot，
                # 之后的 dealCommunityCards 会追加到空列表。改由 startHand/resetTable 重置。
                self.state["pot"] = 0
        
        elif action == "startHand":
            # 新手牌开始，重置公共牌和底池
            self.state["hand_id"] = update.get("id", 0)
            self.state["community_cards"] = []
            self.state["pot"] = 0
            self.state["to_call"] = 0
            self.state["min_raise"] = 0
            self._current_stage = "preflop"
            # 重置本街下注追踪（新一轮从 0 开始）
            self._reset_street_bets()
            if "dealerSeat" in update:
                self.state["dealer_seat"] = update.get("dealerSeat")
            bot_logger.info(f"WS: New hand started (ID: {self.state['hand_id']})")

            # VPIP/PFR: 新手牌开始时递增所有在座玩家的 hands
            for p in update.get("players", []):
                user_id = p.get("userId")
                if user_id is not None and p.get("status") not in ["sitOut", "sit_out"]:
                    self._vpip_ensure(user_id)
                    self.state["vpip_tracker"][user_id]["hands"] += 1
        
        elif action == "blinds":
            self.state["big_blind"] = update.get("minimumRaise", self.state["big_blind"])

        # VPIP/PFR 追踪：bet/call/raise/fold 动作
        elif action in ("bet", "call", "raise", "fold"):
            user_id = update.get("userId")
            if user_id is not None:
                self._vpip_ensure(user_id)
                # preflop 阶段的 bet/call/raise 算 VPIP
                if self._current_stage == "preflop" and action in ("bet", "call", "raise"):
                    self.state["vpip_tracker"][user_id]["vpip_count"] += 1
                # preflop 阶段的 raise 算 PFR
                if self._current_stage == "preflop" and action == "raise":
                    self.state["vpip_tracker"][user_id]["pfr_count"] += 1

            # 追踪本街每名下注额（仅 bet/call/raise，fold 不变）
            if action in ("bet", "call", "raise") and user_id is not None:
                # ReplayPoker 不同 action 用不同字段携带金额；按优先级尝试
                amount = (
                    update.get("amount")
                    or update.get("raiseTo")
                    or update.get("betAmount")
                    or update.get("callAmount")
                    or update.get("chips")
                )
                if isinstance(amount, (int, float)) and amount > 0:
                    self._record_street_bet(user_id, int(amount))
        
        elif action in ["tick", "setActivePlayer"]:
            # 当前行动者
            current_player = update.get("currentPlayer") or update
            seat = current_player.get("seatId") or current_player.get("seat")
            if seat is not None:
                self.state["active_seat"] = seat

                # 判断是否轮到我
                if self.state["my_seat_id"] is not None:
                    self.state["is_my_turn"] = (seat == self.state["my_seat_id"])

                # 更新玩家的 is_acting 标志
                for s, player in self.state["players"].items():
                    player["is_acting"] = (s == seat)

                # 保存游戏阶段
                ws_state = update.get("state", "")
                if ws_state:
                    self.state["current_stage"] = ws_state.lower()
                    self._current_stage = ws_state.lower()

            # 提取跟注/加注金额（WS 结构化数据，比 DOM 更可靠）
            call_amount = update.get("callAmount")
            if call_amount is not None:
                self.state["to_call"] = int(call_amount)

            min_raise = update.get("minimumRaise") or update.get("minRaise")
            if min_raise is not None:
                self.state["min_raise"] = int(min_raise)
    
    async def _handle_deal_hole_cards(self, update: Dict):
        """处理发底牌消息，自动识别自己的座位"""
        cards_in_update = update.get("cards", [])
        bot_logger.debug(f"WS dealHoleCards: my_seat={self.state['my_seat_id']}, cards={cards_in_update}")
        
        for p in update.get("players", []):
            p_cards = p.get("cards")
            seat = p.get("seat") or p.get("seatId")
            user_id = p.get("userId")
            
            if p_cards and len(p_cards) == 2:
                is_my_cards = False
                
                # ⭐ 启发式识别：如果看到非 'X' 的底牌，那一定是我们的位置
                if "X" not in p_cards:
                    is_my_cards = True
                    if self.state["my_seat_id"] != seat:
                        self.state["my_seat_id"] = seat
                        self.state["my_user_id"] = user_id
                        bot_logger.info(f"🎯 WS: Auto-detected identity from cards: seat={seat}, userId={user_id}")
                
                elif self.state["my_user_id"] and str(user_id) == str(self.state["my_user_id"]):
                    is_my_cards = True
                    self.state["my_seat_id"] = seat
                
                elif seat == self.state["my_seat_id"]:
                    is_my_cards = True
                
                if is_my_cards:
                    self.state["hole_cards"] = p_cards
                    bot_logger.info(f"WS: My Hole Cards: {p_cards} (Seat: {seat})")
                
                # 更新玩家卡片
                if seat is not None:
                    if seat not in self.state["players"]:
                        self.state["players"][seat] = {
                            "seat_id": seat,
                            "name": "",
                            "chips": 0,
                            "cards": [],
                            "is_acting": False,
                            "status": "active",
                        }
                    self.state["players"][seat]["cards"] = p_cards
    
    def _update_players(self, players_data: list):
        """更新玩家信息"""
        for p_data in players_data:
            seat = p_data.get("seat") or p_data.get("seatId")
            if seat is None:
                continue
            
            if seat not in self.state["players"]:
                self.state["players"][seat] = {
                    "seat_id": seat,
                    "user_id": p_data.get("userId", ""),
                    "name": "",
                    "chips": 0,
                    "cards": [],
                    "is_acting": False,
                    "status": "active",
                }
            else:
                # 更新 user_id（以防被踢出后重新入座）
                uid = p_data.get("userId")
                if uid is not None:
                    self.state["players"][seat]["user_id"] = uid

            p = self.state["players"][seat]

            if "name" in p_data:
                p["name"] = p_data["name"]
            
            if "chips" in p_data or "stack" in p_data:
                p["chips"] = p_data.get("chips", p_data.get("stack", p["chips"]))
                # 如果是我的座位，同步总筹码
                if seat == self.state["my_seat_id"]:
                    pass  # CLI 可能还没初始化 total_chips
            
            # 更新状态
            raw_status = p_data.get("status") or p_data.get("state", "")
            if raw_status:
                if raw_status in ["sitOut", "sit_out"]:
                    p["status"] = "sit_out"
                elif raw_status in ["fold", "folded"]:
                    p["status"] = "folded"
                else:
                    p["status"] = "active"
            
            # 使用 userId 匹配自己的座位
            user_id = p_data.get("userId")
            if self.state["my_user_id"] and str(user_id) == str(self.state["my_user_id"]):
                if self.state["my_seat_id"] != seat:
                    self.state["my_seat_id"] = seat
                    bot_logger.info(f"WS: Updated my_seat_id to {seat} (matched userId)")
    
    def get_state(self) -> Dict[str, Any]:
        """获取当前状态副本"""
        return self.state.copy()
    
    def is_healthy(self) -> bool:
        """检查 WebSocket 是否健康（最近 45 秒有消息）"""
        import time
        if self._last_ws_time == 0:
            return False
        elapsed = time.time() - self._last_ws_time
        return elapsed < 45
    
    def reset_for_new_hand(self):
        """为新手牌重置状态"""
        self.state["hole_cards"] = []
        self.state["community_cards"] = []
        self.state["pot"] = 0
        self.state["to_call"] = 0
        self.state["min_raise"] = 0
        self.state["is_my_turn"] = False
        self._reset_street_bets()
        bot_logger.debug("WS: State reset for new hand")

    def _vpip_ensure(self, user_id):
        """确保 VPIP 追踪器中有该玩家的记录"""
        if user_id not in self.state["vpip_tracker"]:
            self.state["vpip_tracker"][user_id] = {
                "hands": 0,
                "vpip_count": 0,
                "pfr_count": 0,
            }

    def _record_street_bet(self, user_id, amount: int):
        """记录/更新某玩家本街下注额。

        ReplayPoker 协议下 raise 事件通常带 raise-to 总额（不是增量），
        所以采用 SET 语义（取较大值）以兼容两种约定。
        """
        seat = self._seat_for_user(user_id)
        if seat is None:
            return
        # SET 语义：raise-to 时整街总额；call 时等于 to_call；all-in 同样 SET
        # 使用 max 是为了在 raise-by 协议下也能正确累加
        prev = self._street_bets.get(seat, 0)
        if amount >= prev:
            self._street_bets[seat] = amount
        # 同步到 player dict（方便 get_state() 直接读取）
        if seat in self.state["players"]:
            self.state["players"][seat]["street_bet"] = self._street_bets[seat]

    def _seat_for_user(self, user_id) -> Optional[int]:
        """通过 user_id 反查 seat_id"""
        target = str(user_id) if user_id is not None else None
        if target is None:
            return None
        for seat, pdata in self.state["players"].items():
            if str(pdata.get("user_id", "")) == target:
                return seat
        return None

    def _reset_street_bets(self):
        """重置所有玩家的本街下注额（用于新手牌 / 新街道）"""
        self._street_bets.clear()
        for seat, pdata in self.state["players"].items():
            pdata["street_bet"] = 0

    def get_player_stats(self, user_id) -> Dict[str, float]:
        """
        获取玩家的 VPIP/PFR 统计

        Returns:
            {"vpip": 0.0, "pfr": 0.0} 百分比值
        """
        tracker = self.state.get("vpip_tracker", {})
        entry = tracker.get(user_id)
        if not entry or entry["hands"] == 0:
            return {"vpip": 0.0, "pfr": 0.0}
        return {
            "vpip": entry["vpip_count"] / entry["hands"] * 100,
            "pfr": entry["pfr_count"] / entry["hands"] * 100,
        }
