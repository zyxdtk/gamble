import asyncio
import json
from ..core.game_state import GameState
from ..ui.hud import HUD
from .lifecycle_manager import LifecycleManager
from .play_manager import PlayManager
import yaml


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

        self.lifecycle_mgr = LifecycleManager(self)
        self.play_mgr = PlayManager(self)
        # 引擎管理现在由 play_mgr 负责

        self.is_sitting = False
        self.is_closed = False
        self.exit_requested = False
        self.initial_chips = None
        self.total_buyin = 0
        self._full_table_ticks = 0
        self.my_user_id = None  # 用于识别自己的userId
        self._FULL_TABLE_LIMIT = 5

        self._last_log_turn = None

        self.hands_played = 0
        self.dealer_cycle_count = 0
        self._last_dealer_seat = None
        self._unique_seats_this_cycle = set()

        # 运行限制（可从外部设置）
        self.max_hands_limit = None  # 最大手数限制
        self.max_cycles = 1          # 最大圈数限制

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
                import os
                env_strategy = os.environ.get("POKER_STRATEGY", "").strip()
                if env_strategy:
                    self.strategy_type = env_strategy
                    print(f"[TABLE] Using strategy from environment: {self.strategy_type}", flush=True)
                # 否则保留构造函数传入的 strategy_type
        except Exception as e:
            print(f"[TABLE] Setting parse error: {e}", flush=True)

    async def initialize(self):
        if self.is_closed:
            return
        await self.attach_listeners()
        
        self.play_mgr.ensure_brain_exists(self.strategy_type)
        print(f"[TABLE] Created brain with strategy: {self.strategy_type}", flush=True)
        
        if "/table/" in self.page.url:
            print(f"[TABLE] Reloading {self.page.url} to guarantee WebSocket hook...", flush=True)
            await self.page.reload()
            await self.page.wait_for_load_state("networkidle", timeout=15000)

    async def attach_listeners(self):
        self.page.on("websocket", self.on_websocket)
        self.page.on("close", self.on_close)
        
    def on_close(self, _):
        print(f"[TABLE] Connection closed for {self.page.url}", flush=True)
        self.is_closed = True
        self.play_mgr.remove_brain()

    def on_websocket(self, ws):
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
            print(f"[TABLE] WebSocket watchdog triggered: {elapsed:.1f}s since last frame. Reloading...", flush=True)
            await self.page.reload()
            await self.page.wait_for_load_state("networkidle", timeout=15000)
            self._last_ws_time = asyncio.get_event_loop().time()
            return False
        return True

    async def process_game_message(self, data):
        if not isinstance(data, dict):
            return
        updates = data.get("updates", [])
        for update in updates:
            action = update.get("action")
            if not action:
                continue

            # 精简输出关键信息
            essential = {k: v for k, v in update.items() if k not in ["time", "sequence", "action"]}
            # 如果列表太长（如 players, seats），只保留长度信息或精简项
            for k in ["players", "seats", "pots"]:
                if k in essential and isinstance(essential[k], list):
                    if len(essential[k]) > 3:
                        essential[k] = f"[{len(essential[k])} items]"
            
            print(f"[WS] {action}: {essential}", flush=True)
            
            if "players" in update:
                self._update_players_from_data(update.get("players", []))
            
            if action in ["deal", "dealCards", "dealHoldCards", "dealHoleCards"]:
                cards = update.get("cards", [])
                print(f"[WS] dealHoleCards: my_seat_id={self.state.my_seat_id}, my_user_id={self.my_user_id}, cards_in_update={cards}", flush=True)
                if cards:
                    self.state.hole_cards = cards
                    print(f"[WS] Received Hole Cards directly: {cards}", flush=True)
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
                                print(f"[WS] 🎯 Auto-detected identity from cards: seat={seat}, userId={user_id}", flush=True)
                        elif self.my_user_id and str(user_id) == str(self.my_user_id):
                            is_my_cards = True
                            self.state.my_seat_id = seat
                        elif seat == self.state.my_seat_id:
                            is_my_cards = True

                        if is_my_cards:
                            self.state.hole_cards = p_cards
                            self.is_sitting = True # 确认入座
                            print(f"[WS] My Hole Cards: {p_cards}", flush=True)
                        
                        if seat is not None:
                            if seat not in self.state.players:
                                from ..core.game_state import Player
                                self.state.players[seat] = Player(seat_id=seat)
                            self.state.players[seat].cards = p_cards
            elif action == "dealCommunityCards":
                self.state.community_cards = update.get("cards", [])
                print(f"[WS] Received Community Cards: {self.state.community_cards}", flush=True)
            elif action == "updatePots":
                self.state.pot = sum(p.get("chips", 0) for p in update.get("pots", []))
            elif action == "awardPot":
                self.state.reset_round()
                self.hands_played += 1
                self.play_mgr.reset_brain()
            elif action == "startHand":
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
                        print(f"[WS] Seat update detected: userId={user_id}, seat={seat_id}", flush=True)
            
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
                from ..core.game_state import Player
                self.state.players[seat] = Player(seat_id=seat)
            p = self.state.players[seat]

            if "name" in p_data:
                p.name = p_data["name"]
            if "chips" in p_data or "stack" in p_data:
                p.chips = p_data.get("chips", p_data.get("stack", p.chips))
                if seat == self.state.my_seat_id:
                    self.state.total_chips = p.chips
                    # 统计同步：初始化起始筹码和买入
                    if self.initial_chips is None and p.chips > 0:
                        self.initial_chips = p.chips
                        self.total_buyin = p.chips
                        print(f"[WS] Initialized stats: initial_chips={p.chips}, total_buyin={p.chips}", flush=True)

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
                    if self.initial_chips is None and p.chips > 0:
                        self.initial_chips = p.chips
                        self.total_buyin = p.chips
                        print(f"[WS] Initialized stats (userId match): initial_chips={p.chips}", flush=True)
                    print(f"[WS] Updated my_seat_id to {seat} (matched userId)", flush=True)
            elif seat == self.state.my_seat_id:
                if self.my_user_id is None and user_id:
                    self.my_user_id = user_id
                    print(f"[WS] Sync my_user_id to {user_id} from my_seat_id={seat}", flush=True)

    async def update_dealer_cycle(self):
        return await self.play_mgr._update_dealer_cycle()

    async def perform_click(self, action_text: str):
        return await self.play_mgr.perform_click(action_text)

    async def leave_table(self):
        return await self.lifecycle_mgr.leave_table()

    def _should_leave_table(self, exit_status: dict) -> bool:
        """
        根据 LifecycleManager 提供的状态信息，决定是否离开桌子。
        TableManager 负责做决策。
        """
        if not exit_status["should_exit"]:
            return False
        
        # 桌子满了，必须离开
        if exit_status["table_full"]:
            print("[TABLE] Decision: Leaving - Table is full.", flush=True)
            return True
        
        # 止损触发
        if exit_status["stop_loss_triggered"]:
            print(f"[TABLE] Decision: Leaving - Stop loss triggered: {exit_status['profit']}", flush=True)
            return True
        
        # 止盈触发
        if exit_status["take_profit_triggered"]:
            print(f"[TABLE] Decision: Leaving - Take profit triggered: +{exit_status['profit']}", flush=True)
            return True
        
        # 筹码不足
        if exit_status["low_chips"]:
            print(f"[TABLE] Decision: Leaving - Low chips: {exit_status['current_chips']}", flush=True)
            return True

        # 筹码超过上限
        if exit_status["max_chips"]:
            print(f"[TABLE] Decision: Leaving - Max chips exceeded: {exit_status['current_chips']}", flush=True)
            return True

        # 没有其他玩家
        if exit_status["no_other_players"]:
            print(f"[TABLE] Decision: Leaving - No other players for {exit_status['empty_table_elapsed']:.1f}s", flush=True)
            return True
        
        # 达到最大圈数
        if exit_status["max_cycles_reached"]:
            print(f"[TABLE] Decision: Leaving - Max cycles reached: {self.dealer_cycle_count}", flush=True)
            return True
        
        return False

    async def execute_turn(self):
        try:
            if self.is_closed or self.exit_requested:
                return
            
            if not await self.check_websocket_health():
                return

            await self.play_mgr.update_state_from_dom()

            # 获取决策（PlayManager 负责引擎交互）
            dummy_decision = self.play_mgr.request_decision()
            if dummy_decision is None:
                print("[TABLE] Error: Engine returned None decision.", flush=True)
                return
            is_passive = dummy_decision.get("is_passive", False)

            # TableManager 负责决定是否离开桌子
            # 优先检查退出条件（即使还没入座，如果识别到筹码超标也要走）
            exit_status = self.lifecycle_mgr.get_exit_status()
            if not is_passive and self._should_leave_table(exit_status):
                await self.lifecycle_mgr.leave_table()
                return

            if not self.is_sitting and not is_passive:
                sat = await self.lifecycle_mgr.try_sit_and_buyin()
                if not sat:
                    self._full_table_ticks += 1
                    if self._full_table_ticks >= self._FULL_TABLE_LIMIT:
                        print(f"[TABLE] Cannot sit after {self._FULL_TABLE_LIMIT} attempts. Leaving...", flush=True)
                        await self.lifecycle_mgr.leave_table()
                    return
                else:
                    self._full_table_ticks = 0
            
            await self.lifecycle_mgr.check_overlays()

            if not self.state.available_actions:
                if self.is_sitting:
                    turn_key = f"waiting-{self.state.hole_cards}-{self.state.community_cards}"
                    if self._last_log_turn != turn_key:
                        print(f"[TABLE] In Play Mode. Waiting for turn... (Pot: {self.state.pot}, Chips: {self.state.total_chips}, Hole: {self.state.hole_cards})", flush=True)
                        self._last_log_turn = turn_key
                return

            # 获取最终决策（PlayManager 负责引擎交互）
            decision_data = self.play_mgr.request_decision()
            if decision_data is None:
                return

            strategy_name = decision_data.get("strategy_name", "Unknown")

            # 输出策略思考日志（支持所有策略类型）
            turn_key = f"{strategy_name}-{self.state.hole_cards}-{self.state.community_cards}"
            if self._last_log_turn != turn_key:
                decision_info = decision_data.get("decision") or {}
                action = decision_info.get("action", "WAIT")
                amount = decision_info.get("amount", 0)
                equity = decision_data.get('my_equity', 0)
                hand = self.state.hole_cards if self.state.hole_cards else "Unknown"
                plan_info = decision_data.get("my_action", "")

                # 根据策略类型输出不同格式的日志
                if strategy_name in ["GTO", "gto"]:
                    print(f"[GTO THINKING] Hand: {hand}, Action: {action}", end="")
                    if amount > 0:
                        print(f" (Amount: {amount})", end="")
                    print(f", Equity: {equity * 100:.1f}%", flush=True)
                    if plan_info:
                        print(f"[GTO PLAN] {plan_info}", flush=True)
                elif strategy_name in ["exploitative", "EXPLOITATIVE"]:
                    print(f"[EXPLOITATIVE THINKING] Hand: {hand}, Action: {action}", end="")
                    if amount > 0:
                        print(f" (Amount: {amount})", end="")
                    print(f", Equity: {equity * 100:.1f}%", flush=True)
                    if plan_info:
                        print(f"[EXPLOITATIVE PLAN] {plan_info}", flush=True)
                elif strategy_name in ["checkorfold", "CHECKORFOLD", "check_or_fold"]:
                    print(f"[CHECK/FOLD THINKING] Hand: {hand}, Action: {action}", flush=True)
                    if plan_info:
                        print(f"[CHECK/FOLD PLAN] {plan_info}", flush=True)
                else:
                    print(f"[{strategy_name.upper()} THINKING] Hand: {hand}, Action: {action}", end="")
                    if amount > 0:
                        print(f" (Amount: {amount})", end="")
                    print(f", Equity: {equity * 100:.1f}%", flush=True)
                    if plan_info:
                        print(f"[{strategy_name.upper()} PLAN] {plan_info}", flush=True)

                self._last_log_turn = turn_key

            if is_passive:
                turn_key = f"{self.state.hole_cards}-{self.state.community_cards}"
                if self._last_log_turn != turn_key:
                    print(f"[STRATEGY: {strategy_name}] Action turn. Pot: {self.state.pot}. Call: {self.state.to_call}. MinRaise: {self.state.min_raise}", flush=True)
                    self.log_snapshot(decision_data)
                    self._last_log_turn = turn_key
                return

            decision_obj = decision_data.get("decision") if isinstance(decision_data, dict) else None
            
            if decision_obj and isinstance(decision_obj, dict):
                action = decision_obj.get("action", "")
                amount = decision_obj.get("amount", 0)
                bet_size_hint = decision_data.get("bet_size_hint") if isinstance(decision_data, dict) else None
                
                if action:
                    await self.hud.update_content(self.page, decision_data)
                    print(f"[STRATEGY: {strategy_name}] Executing: {action} (Amount: {amount}, Hint: {bet_size_hint})", flush=True)
                    await self.play_mgr.perform_click(action, amount=amount, bet_size_hint=bet_size_hint)
                    await asyncio.sleep(2)
        except Exception as e:
            import traceback
            print(f"[TABLE] Error in execute_turn: {e}", flush=True)
            traceback.print_exc()

    def log_snapshot(self, decision_data):
        log_file = "./data/apprentice_logs.jsonl"
        snap = {
            "pot": self.state.pot,
            "hole_cards": self.state.hole_cards,
            "community_cards": self.state.community_cards,
            "chips": self.state.total_chips,
            "suggestion": decision_data.get("my_action", "") if isinstance(decision_data, dict) else decision_data,
            "strategy": decision_data.get("strategy_name"),
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
            print(f"[TABLE] Max hands limit ({self.max_hands_limit}) reached. Should exit.", flush=True)
            return True

        # 检查圈数限制
        if self.dealer_cycle_count >= self.max_cycles:
            print(f"[TABLE] Max cycles ({self.max_cycles}) reached. Should exit.", flush=True)
            return True

        # 检查是否已经请求退出
        if self.exit_requested:
            return True

        return False
