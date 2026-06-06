import asyncio
import json
import os
import traceback
import yaml
from ..brain.game_state import GameState
from ..ui.hud import HUD
from .lifecycle_manager import LifecycleManager
from .play_manager import PlayManager
from ..utils.logger import ws_logger, table_logger


class TableManager:
    """
    Handles gameplay and lifecycle for a single poker table.
    Now acts as a Coordinator routing logical segments to `PlayManager` & `LifecycleManager`.
    """
    def __init__(self, page, strategy_type: str = "gto"):
        self.page = page
        self.strategy_type = strategy_type
        self.state = GameState()
        self.hud = HUD()
        self._processed_msg_ids = set() # 用于去重
        self._max_msg_cache = 100

        self.lifecycle_mgr = LifecycleManager(self)
        self.play_mgr = PlayManager(self)
        # 引擎管理现在由 play_mgr 负责

        self.is_sitting = False
        self.is_closed = False
        self.exit_requested = False
        self.starting_stack = None  # 入场时的起始筹码量
        self.added_buyin = 0       # 中途追加的买入金额
        self._full_table_ticks = 0
        self.my_user_id = None  # 用于识别自己的userId
        self._FULL_TABLE_LIMIT = 5

        self._last_log_turn = None
        self._last_action_time = 0 # 记录上次点击的时间戳

        self.hands_played = 0
        self.dealer_cycle_count = 0
        self._last_dealer_seat = None
        self._unique_seats_this_cycle = set()

        # 运行限制（可从外部设置）
        self.max_hands_limit = None  # 最大手数限制
        self.max_cycles = 10         # 最大圈数限制 (默认调高)

        self.stop_loss_bb = 100
        self.take_profit_bb = 300
        self.low_chips_bb = 10
        self.max_chips_bb = 500
        self.big_blind = 0
        self.apprentice_mode = False
        self.settings = {}
        self._last_ws_time = asyncio.get_event_loop().time()

        self._load_settings()

    def _load_settings(self):
        try:
            with open("config/settings.yaml", 'r') as f:
                config = yaml.safe_load(f)
                if config is None:
                    config = {}
                self.settings = config

                exit_cfg = config.get("game", {}).get("exit_thresholds", {})
                self.stop_loss_bb = exit_cfg.get("stop_loss_bb", 100)
                self.take_profit_bb = exit_cfg.get("take_profit_bb", 300)
                self.low_chips_bb = exit_cfg.get("low_chips_bb", 10)
                self.max_chips_bb = exit_cfg.get("max_chips_bb", 500)

                limits = config.get("auto_mode", {}).get("limits", {})
                self.max_cycles = limits.get("max_cycles", 1)

                stakes_str = config.get("game", {}).get("preferred_stakes", "1/2")
                self.big_blind = self.play_mgr._parse_stakes_string(stakes_str)

                # 只有当没有传入策略时才从配置读取
                env_strategy = os.environ.get("POKER_STRATEGY", "").strip()
                if env_strategy:
                    self.strategy_type = env_strategy
                    table_logger.info(f"Using strategy from environment: {self.strategy_type}")
                # 否则保留构造函数传入的 strategy_type
        except Exception as e:
            table_logger.error(f"Setting parse error: {e}")

    async def initialize(self):
        if self.is_closed:
            return
        await self.attach_listeners()
        
        self.play_mgr.ensure_brain_exists(self.strategy_type)
        table_logger.info(f"Created brain with strategy: {self.strategy_type}")
        
        if "/table/" in self.page.url:
            table_logger.info(f"Reloading {self.page.url} to guarantee WebSocket hook...")
            await self.page.reload()
            await self.page.wait_for_load_state("networkidle", timeout=15000)

    async def attach_listeners(self):
        self._registered_ws_ids = set()  # 用于追踪已注册的 WS，防止重复绑定
        self.page.on("websocket", self.on_websocket)
        self.page.on("close", self.on_close)
        
    def on_close(self, _):
        table_logger.info(f"Connection closed for {self.page.url}")
        self.is_closed = True
        self.play_mgr.remove_brain()

    def on_websocket(self, ws):
        ws_id = id(ws)
        if ws_id in self._registered_ws_ids:
            return  # 已注册过，跳过，防止重复 handler
        self._registered_ws_ids.add(ws_id)
        ws.on("framereceived", self.handle_ws_frame)

    async def handle_ws_frame(self, frame):
        try:
            self._last_ws_time = asyncio.get_event_loop().time()
            payload = frame.text if hasattr(frame, 'text') else str(frame)
            if payload.startswith("["):
                data = json.loads(payload)
                if len(data) >= 5 and data[3] == "output":
                    await self.process_game_message(data[4])
        except Exception:
            pass

    async def check_websocket_health(self):
        if self.is_closed or self.exit_requested:
            return True
        
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_ws_time
        
        if "/table/" in self.page.url and elapsed > 45:
            table_logger.warning(f"WebSocket watchdog triggered: {elapsed:.1f}s since last frame. Reloading...")
            await self.page.reload()
            await self.page.wait_for_load_state("networkidle", timeout=15000)
            self._last_ws_time = asyncio.get_event_loop().time()
            return False
        return True

    async def process_game_message(self, data):
        if not isinstance(data, dict):
            return
            
        # [FIX] 彻底移除对 ID 的信任，改用全量内容哈希。
        # ReplayPoker 的多个独立包（Action 不同）可能共用同一个 ID 或 at。
        # 只有物理内容完全一致的消息才应被去重。
        data_str = json.dumps(data, sort_keys=True)
        msg_hash = hash(data_str)
        
        if msg_hash in self._processed_msg_ids:
            return
        self._processed_msg_ids.add(msg_hash)
        
        if len(self._processed_msg_ids) > self._max_msg_cache:
            # 清理：集合不支持 pop，切片清空
            self._processed_msg_ids = set(list(self._processed_msg_ids)[-self._max_msg_cache//2:])
        
        updates = data.get("updates", [])
        
        # [CRITICAL] 优先级处理：确保在一个 Batch 内，startHand 始终先于 dealHoleCards 执行。
        # 否则 startHand 的重置逻辑会抹掉刚收到的底牌。
        def get_priority(u):
            act = u.get("action", "")
            if act == "startHand": return 0
            if act == "dealHoleCards": return 1
            return 2
        
        sorted_updates = sorted(updates, key=get_priority)
        
        for update in sorted_updates:
            # --- 1. 全量状态同步 (无视是否有 action 字段) ---
            if "players" in update:
                self._update_players_from_data(update.get("players", []))
            
            if "communityCards" in update:
                c_cards = update.get("communityCards", [])
                if isinstance(c_cards, list) and len(c_cards) >= len(self.state.community_cards):
                    if c_cards != self.state.community_cards:
                        self.state.community_cards = c_cards
                        ws_logger.info(f"Synced Community Cards (full): {self.state.community_cards}")
            
            if "pot" in update:
                new_pot = update.get("pot")
                if new_pot is not None:
                    self.state.pot = new_pot

            # --- 2. 行为动作逻辑 (依赖 action 字段) ---
            action = update.get("action")
            if not action:
                continue

            # 精简输出关键信息
            essential = {k: v for k, v in update.items() if k not in ["time", "sequence", "action"]}
            # 如果列表太长（如 players, seats, pots），只保留长度信息或精简项
            for k in ["players", "seats", "pots"]:
                if k in essential and isinstance(essential[k], list):
                    if len(essential[k]) > 3:
                        essential[k] = f"[{len(essential[k])} items]"
            
            # 减少高频/元数据消息（如 tick, seat, extendedConnections）的冗余日志
            if action in ["tick", "seat", "extendedConnections"]:
                ws_logger.debug(f"{action}: {essential}")
            else:
                ws_logger.info(f"{action}: {essential}")
            
            if action in ["deal", "dealCards", "dealHoldCards", "dealHoleCards"]:
                cards = update.get("cards", [])
                ws_logger.debug(f"dealHoleCards: my_seat_id={self.state.my_seat_id}, my_user_id={self.my_user_id}, cards_in_update={cards}")
                for p in update.get("players", []):
                    p_cards = p.get("cards")
                    seat = p.get("seat") or p.get("seatId")
                    user_id = p.get("userId")
                    
                    if p_cards and len(p_cards) == 2:
                        is_my_cards = False
                        # 启发式识别：如果看到非 'X' 的底牌，那一定是我们的位置
                        if "X" not in p_cards:
                            is_my_cards = True
                            if self.state.my_seat_id != seat:
                                self.state.my_seat_id = seat
                                self.my_user_id = user_id
                                ws_logger.info(f"🎯 Auto-detected identity from cards: seat={seat}, userId={user_id}")
                        elif self.my_user_id and str(user_id) == str(self.my_user_id):
                            is_my_cards = True
                            self.state.my_seat_id = seat
                        elif seat == self.state.my_seat_id:
                            is_my_cards = True
                        
                        if is_my_cards:
                            self.state.hole_cards = p_cards
                            self.is_sitting = True # 确认入座
                            ws_logger.info(f"My Hole Cards synchronized: {p_cards} (Seat: {seat})")
                            
                            # [FIX] 强制同步资产
                            if "chips" in p or "stack" in p:
                                self.state.total_chips = p.get("chips", p.get("stack", self.state.total_chips))
                                ws_logger.info(f"Sync total_chips from dealHoleCards: {self.state.total_chips}")
                            
                            # 自动补全身份
                            if self.state.my_seat_id is None:
                                self.state.my_seat_id = seat
                                ws_logger.info(f"🎯 Auto-filled missing my_seat_id to {seat}")
                        
                        if seat is not None:
                            if seat not in self.state.players:
                                from ..brain.game_state import Player
                                self.state.players[seat] = Player(seat_id=seat)
                            self.state.players[seat].cards = p_cards
            elif action == "dealCommunityCards":
                cards = update.get("cards")
                if isinstance(cards, list) and len(cards) > 0:
                    self.state.community_cards = cards
                    ws_logger.info(f"Received Community Cards: {self.state.community_cards}")
            
            if action == "updatePots":
                self.state.pot = sum(p.get("chips", 0) for p in update.get("pots", []))
            elif action == "awardPot":
                self.state.reset_round() # 仅清空公共牌和底池
                self.hands_played += 1
                self.play_mgr.reset_brain()
            elif action == "startHand":
                self.state.reset_for_new_hand() # 新手牌真正开始，清理旧底牌
                if "dealerSeat" in update:
                    self.state.current_dealer_seat = update.get("dealerSeat")
                # 记录 Hand ID 并在全局增加所有选手的 hands_played
                self.state.hand_id = update.get("id", 0)
                for seat, player in self.state.players.items():
                    if player.status != "sit_out":
                        player.hands_played += 1
            elif action == "blinds":
                self.big_blind = update.get("minimumRaise", self.big_blind)
            elif action == "tick":
                current_player = update.get("currentPlayer")
                self.big_blind = update.get("minimumRaise", self.big_blind)
                # [FIX] 保存 WebSocket 提供的游戏阶段
                ws_state = update.get("state")
                if ws_state:
                    self.state.current_stage = ws_state
                if current_player:
                    seat = current_player.get("seatId")
                    self.state.active_seat = seat
                    for s, p in self.state.players.items():
                        p.is_acting = (s == seat)
            elif action == "setActivePlayer":
                seat = update.get("seat")
                self.state.active_seat = seat
                for s, p in self.state.players.items():
                    p.is_acting = (s == seat)
            elif action == "seat":
                # 仅记录收到的座位信息，不再盲目假设是自己
                seat_data = update.get("seat", {})
                if seat_data.get("state") == "playing":
                    user_id = seat_data.get("userId")
                    seat_id = seat_data.get("id")
                    if user_id and seat_id is not None:
                        # 仅做记录，不直接设置为 my_seat_id
                        ws_logger.debug(f"Seat update detected: userId={user_id}, seat={seat_id}")
            
            # --- 统计 VPIP 和 PFR 行为 ---
            if action in ["bet", "call", "raise"]:
                seat = update.get("seatId")
                if seat in self.state.players:
                    player = self.state.players[seat]
                    hand_id = getattr(self.state, "hand_id", 0)
                    # 标记参与了本局 (VPIP)
                    if not hasattr(player, "_vpip_counted_hand"): player._vpip_counted_hand = -1
                    if player._vpip_counted_hand != hand_id:
                        player.vpip_actions += 1
                        player._vpip_counted_hand = hand_id
                    
                    # 标记加注 (PFR)
                    if action == "raise" or action == "bet":
                        if not hasattr(player, "_pfr_counted_hand"): player._pfr_counted_hand = -1
                        if player._pfr_counted_hand != hand_id:
                            player.pfr_actions += 1
                            player._pfr_counted_hand = hand_id

        # 更新游戏状态到引擎（PlayManager 负责引擎交互）
        self.play_mgr.update_brain_state()

    def _update_players_from_data(self, players_data):
        for p_data in players_data:
            seat = p_data.get("seat") or p_data.get("seatId")
            if seat is None:
                continue
            if seat not in self.state.players:
                from ..brain.game_state import Player
                self.state.players[seat] = Player(seat_id=seat)
            p = self.state.players[seat]

            if "name" in p_data:
                p.name = p_data["name"]
            if "chips" in p_data or "stack" in p_data:
                p.chips = p_data.get("chips", p_data.get("stack", p.chips))
                if seat == self.state.my_seat_id:
                    self.state.total_chips = p.chips
                    # 统计同步：初始化起始筹码
                    if p.starting_stack is None:
                        p.starting_stack = p.chips
                        ws_logger.debug(f"Initialized stats: starting_stack={p.chips}")

            raw_status = p_data.get("status") or p_data.get("state", "")
            if raw_status:
                if raw_status in ["sitOut", "sit_out"]:
                    p.status = "sit_out"
                    p.is_active = False
                elif raw_status in ["fold", "folded"]:
                    p.status = "folded"
                    p.is_active = False
                else:
                    p.status = "active"
                    p.is_active = True

            # 使用userId匹配自己的座位（如果已知）
            user_id = p_data.get("userId")
            if self.my_user_id and str(user_id) == str(self.my_user_id):
                if self.state.my_seat_id != seat:
                    self.state.my_seat_id = seat
                    self.state.total_chips = p.chips
                    # 同时在这里也做一次统计初始化检查
                    if p.starting_stack is None:
                        p.starting_stack = p.chips
                        ws_logger.debug(f"Initialized stats (userId match): starting_stack={p.starting_stack}")
                    self.state.my_seat_id = seat
                    ws_logger.info(f"Updated my_seat_id to {seat} (matched userId)")
                    if not self.my_user_id:
                        self.my_user_id = user_id
                        ws_logger.info(f"Sync my_user_id to {user_id} from my_seat_id={seat}")
            elif seat == self.state.my_seat_id:
                if self.my_user_id is None and user_id:
                    self.my_user_id = user_id
                    ws_logger.info(f"Sync my_user_id to {user_id} from my_seat_id={seat}")

    async def update_dealer_cycle(self):
        return await self.play_mgr._update_dealer_cycle()

    async def perform_click(self, action_text: str):
        return await self.play_mgr.perform_click(action_text)

    async def leave_table(self):
        return await self.lifecycle_mgr.leave_table()

    def _should_leave_table(self, exit_status: dict) -> bool:
        """根据统计信息和退出条件决定是否切桌。
        TableManager 负责做决策。
        """
        if not exit_status.get("should_exit", False):
            return False
        
        # 桌子满了，必须离开
        if exit_status.get("table_full", False):
            table_logger.info("Decision: Leaving - Table is full.")
            return True
        
        # 止损触发
        if exit_status.get("stop_loss_triggered", False):
            table_logger.info(f"Decision: Leaving - Stop loss triggered: {exit_status.get('profit', 0)}")
            return True
        
        # 止盈触发
        if exit_status.get("take_profit_triggered", False):
            table_logger.info(f"Decision: Leaving - Take profit triggered: +{exit_status.get('profit', 0)}")
            return True
        
        # 筹码不足
        if exit_status.get("low_chips", False):
            table_logger.info(f"Decision: Leaving - Low chips: {exit_status.get('current_chips', 0)}")
            return True

        # 筹码超过上限
        if exit_status.get("max_chips", False):
            table_logger.info(f"Decision: Leaving - Max chips exceeded: {exit_status.get('current_chips', 0)}")
            return True

        # 没有其他玩家
        if exit_status.get("no_other_players", False):
            table_logger.info(f"Decision: Leaving - No other players for {exit_status.get('empty_table_elapsed', 0.0):.1f}s")
            return True
        
        # 达到最大圈数
        if exit_status.get("max_cycles_reached", False):
            table_logger.info(f"Decision: Leaving - Max cycles reached: {self.dealer_cycle_count}")
            return True
        
        return False

    async def execute_turn(self):
        try:
            if self.is_closed or self.exit_requested:
                return
            
            if not await self.check_websocket_health():
                return

            await self.play_mgr.update_state_from_dom()

            # TableManager 负责决定是否离开桌子
            # 优先检查退出条件（即使还没入座，如果识别到筹码超标也要走）
            exit_status = self.lifecycle_mgr.get_exit_status()
            if not self.apprentice_mode and self._should_leave_table(exit_status):
                await self.lifecycle_mgr.leave_table()
                return

            if not self.is_sitting and not self.apprentice_mode:
                sat = await self.lifecycle_mgr.try_sit_and_buyin()
                if not sat:
                    self._full_table_ticks += 1
                    if self._full_table_ticks >= self._FULL_TABLE_LIMIT:
                        table_logger.info(f"Cannot sit after {self._FULL_TABLE_LIMIT} attempts. Leaving...")
                        await self.lifecycle_mgr.leave_table()
                    return
                else:
                    self._full_table_ticks = 0
            
            await self.lifecycle_mgr.check_overlays()

            # 只有轮到我操作时才执行决策
            if not self.state.is_my_turn:
                if self.is_sitting:
                    # 等待轮次，包含 Pot 状态以免误判
                    turn_key = f"waiting-{self.state.hole_cards}-{self.state.community_cards}-{self.state.to_call}-{self.state.pot}"
                    if self._last_log_turn != turn_key:
                        table_logger.info(f"In Play Mode. Waiting for turn... (Pot: {self.state.pot}, Chips: {self.state.total_chips}, Hole: {self.state.hole_cards})")
                        self._last_log_turn = turn_key
                return

            # [FIX] 时序优化：检查底牌是否已通过 WS 同步
            if not self.state.hole_cards and not self.state.community_cards:
                wait_count = 0
                max_waits = 4 # 2s
                while not self.state.hole_cards and wait_count < max_waits:
                    table_logger.warning(f"Detected turn but hole_cards empty. Waiting for WebSocket... ({wait_count+1}/{max_waits})")
                    await asyncio.sleep(0.5)
                    wait_count += 1
                if not self.state.hole_cards:
                    table_logger.error("Hole cards still empty after waiting 2s. Deciding with unknown state.")

            # 获取引擎决策
            plan = self.play_mgr.request_decision()
            if plan is None:
                return

            strategy_name = getattr(plan, "strategy_name", "Unknown")
            action_type, amount = plan.get_action_for_bet(self.state.to_call, self.state.pot)
            action = action_type.value
            
            # 阶段追踪 - 优先使用 WebSocket 提供的阶段
            ws_stage = getattr(self.state, 'current_stage', '').lower()
            if ws_stage in ['preflop', 'flop', 'turn', 'river']:
                stage = ws_stage.upper()
            else:
                # 回退到基于公共牌数量的判定
                num_board = len(self.state.community_cards)
                if num_board == 0:
                    stage = "PREFLOP"
                elif num_board == 3:
                    stage = "FLOP"
                elif num_board == 4:
                    stage = "TURN"
                elif num_board == 5:
                    stage = "RIVER"
                elif num_board == 1 or num_board == 2:
                    stage = "FLOP-INCOMPLETE"
                    table_logger.warning(f"公共牌数量异常: {num_board}张，等待完整数据...")
                else:
                    stage = f"BOARD-{num_board}"

            # 增强型 turn_key：必须包含 pot 和 to_call，否则同一街多次博弈会被去重杀掉
            turn_key = f"{stage}-{self.state.to_call}-{self.state.pot}"
            
            import time
            now = time.time()

            # --- A. 状态变更：日志与 HUD 刷新 (单状态仅发生一次) ---
            if self._last_log_turn != turn_key:
                hand = self.state.hole_cards if self.state.hole_cards else "Unknown"
                equity = getattr(plan, "my_equity", 0)
                pot_odds = getattr(plan, "pot_odds", 0)
                ev = getattr(plan, "ev", 0)
                # [IMPROVE] 日志显示底池(Pot)、需跟注(ToCall)、总筹码(Chips)、赔率(PO)和期望收益(EV)
                table_logger.info(f"[{strategy_name.upper()} {stage}] Hand: {hand}, Action: {action}, Amount: {amount}, Pot: {self.state.pot}, ToCall: {self.state.to_call}, Chips: {self.state.total_chips}, Eq: {equity * 100:.1f}%, PO: {pot_odds * 100:.1f}%, EV: {ev:.1f}, Plan: {plan.reasoning}")

                h_data = plan.to_dict()
                h_data["stage"] = stage
                if self.hud:
                    await self.hud.update_content(self.page, h_data)
                
                # [CRITICAL] 状态锁立即生效，防止 5s 冷却期间日志刷屏
                self._last_log_turn = turn_key
                self._last_action_time = 0 # 状态变更，重置执行计时，允许立即物理操作

            # --- B. 统计模式/预览模式处理 ---
            if self.apprentice_mode:
                if self._last_action_time == 0:
                    table_logger.info(f"[APPRENTICE] Suggestion: {action}. Pot: {self.state.pot}. Call: {self.state.to_call}")
                    self.log_snapshot(plan)
                    self._last_action_time = now
                return

            # --- C. 自动模式：动作物理执行 (具备 5s 间隔重试机制) ---
            if action:
                if now - self._last_action_time > 5:
                    bet_size_hint = plan.bet_size_hint
                    table_logger.info(f"[EXECUTE] Street: {stage}, Action: {action}, Amount: {amount}")
                    success = await self.play_mgr.perform_click(action, amount=amount, bet_size_hint=bet_size_hint)
                    
                    if success:
                        self._last_action_time = now
                        # 降低轮询竞争，清空临时状态并休眠
                        self.state.available_actions = []
                        await asyncio.sleep(2)
                    else:
                        # [FIX] 点击失败时不更新 _last_action_time，允许下次循环重试
                        table_logger.warning(f"[EXECUTE FAILED] Action: {action}, will retry...")
                else:
                    # 无需操作的状态也要跳过
                    self._last_log_turn = turn_key

        except Exception as e:
            table_logger.error(f"Error in execute_turn: {e}")
            table_logger.exception(e)

    def log_snapshot(self, decision_data):
        log_file = "./data/apprentice_logs.jsonl"
        
        # 统一转换为字典处理
        if hasattr(decision_data, "to_dict"):
            data = decision_data.to_dict()
        elif isinstance(decision_data, dict):
            data = decision_data
        else:
            data = {"action": str(decision_data)}
            
        snap = {
            "pot": self.state.pot,
            "hole_cards": self.state.hole_cards,
            "community_cards": self.state.community_cards,
            "chips": self.state.total_chips,
            "suggestion": data.get("action", ""),
            "reasoning": data.get("reasoning", ""),
            "strategy": data.get("strategy_name", "Unknown"),
            "action_space": {
                "available": self.state.available_actions,
                "to_call": self.state.to_call,
                "min_raise": self.state.min_raise
            }
        }
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(snap, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def should_exit(self) -> bool:
        """
        检查是否应该退出当前牌桌。

        Returns:
            True 如果达到任何退出条件
        """
        # 检查手数限制
        if self.max_hands_limit and self.hands_played >= self.max_hands_limit:
            table_logger.info(f"Max hands limit ({self.max_hands_limit}) reached. Should exit.")
            return True

        # 检查圈数限制
        if self.dealer_cycle_count >= self.max_cycles:
            table_logger.info(f"Max cycles ({self.max_cycles}) reached. Should exit.")
            return True

        # 检查是否已经请求退出
        if self.exit_requested:
            return True

        return False
