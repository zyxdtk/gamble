import asyncio
import re


class LifecycleManager:
    """Manages pre-play states (waiting, sitting out, buying in) and exit conditions."""
    def __init__(self, table_manager):
        self.tm = table_manager
        self._empty_table_since = None
        self._SITOUT_LEAVE_DELAY = 20  # Seconds
        self._table_full = False
        self._SIT_MAX_RETRIES = 10
        self._SIT_RETRY_INTERVAL = 2
        
    async def try_sit_and_buyin(self):
        start_time = asyncio.get_event_loop().time()
        retry_count = 0
        
        while retry_count < self._SIT_MAX_RETRIES:
            retry_count += 1
            try:
                elapsed = asyncio.get_event_loop().time() - start_time
                print(f"[TABLE] try_sit_and_buyin attempt {retry_count}, elapsed {elapsed:.1f}s", flush=True)
                
                my_seat, seat_id = await self._find_my_seat()
                if my_seat:
                    # 检查是否已经有筹码（已买入）
                    if self.tm.state.total_chips and self.tm.state.total_chips > 0:
                        self.tm.is_sitting = True
                        # 设置初始筹码和买入金额（用于统计）
                        if self.tm.initial_chips is None:
                            self.tm.initial_chips = self.tm.state.total_chips
                            self.tm.total_buyin = self.tm.state.total_chips
                            print(f"[TABLE] Already seated at table with {self.tm.state.total_chips} chips. Initial buyin recorded: {self.tm.total_buyin}", flush=True)
                        else:
                            print(f"[TABLE] Already seated at table with {self.tm.state.total_chips} chips.", flush=True)
                        return True
                    else:
                        # 有座位但没有筹码，需要买入
                        print("[TABLE] Seated but no chips, need to buy in...", flush=True)
                        if await self._confirm_buyin_dialog():
                            self.tm.is_sitting = True
                            # 设置初始筹码（用于统计）
                            if self.tm.initial_chips is None and self.tm.state.total_chips:
                                self.tm.initial_chips = self.tm.state.total_chips
                            print("[TABLE] Buy-in confirmed.", flush=True)
                            return True
                    
                if await self._confirm_buyin_dialog():
                    self.tm.is_sitting = True
                    print("[TABLE] Buy-in confirmed.", flush=True)
                    return True
                
                waiting = self.tm.page.locator(".WaitingListControls__action").first
                if await waiting.count() > 0 and await waiting.is_visible():
                    print("[TABLE] Table is full. Will leave to find another table.", flush=True)
                    self._table_full = True
                    return False
                
                seat_any = self.tm.page.get_by_role("button", name=re.compile("Seat me anywhere", re.I)).first
                if await seat_any.count() > 0 and await seat_any.is_visible():
                    print("[TABLE] Clicking 'Seat me anywhere'...", flush=True)
                    await seat_any.click()
                    await asyncio.sleep(1)  # 等待对话框出现
                    # 点击后立即检查买入对话框
                    if await self._confirm_buyin_dialog():
                        self.tm.is_sitting = True
                        # 再次查找座位ID
                        _, seat_id = await self._find_my_seat()
                        print(f"[TABLE] Buy-in confirmed after seating. Seat ID: {seat_id}", flush=True)
                        return True
                    await asyncio.sleep(self._SIT_RETRY_INTERVAL)
                    continue
                
                empty_seat = self.tm.page.locator(".Seat--empty, .Seat--open").first
                if await empty_seat.count() > 0 and await empty_seat.is_visible():
                    print("[TABLE] Clicking empty seat...", flush=True)
                    await empty_seat.click()
                    await asyncio.sleep(1)  # 等待对话框出现
                    # 点击后立即检查买入对话框
                    if await self._confirm_buyin_dialog():
                        self.tm.is_sitting = True
                        # 再次查找座位ID
                        _, seat_id = await self._find_my_seat()
                        print(f"[TABLE] Buy-in confirmed after seating. Seat ID: {seat_id}", flush=True)
                        return True
                    await asyncio.sleep(self._SIT_RETRY_INTERVAL)
                    continue
                    
                print("[TABLE] No action available, waiting...", flush=True)
                await asyncio.sleep(self._SIT_RETRY_INTERVAL)
                
            except Exception as e:
                print(f"[TABLE] Error in try_sit_and_buyin attempt {retry_count}: {e}", flush=True)
                await asyncio.sleep(self._SIT_RETRY_INTERVAL)
        
        raise TimeoutError(f"Failed to sit and buyin after {self._SIT_MAX_RETRIES} attempts")

    async def _confirm_buyin_dialog(self):
        """确认买入对话框。"""
        try:
            # 检查是否有模态框覆盖层
            modal = self.tm.page.locator(".ModalOverlay, .modal-overlay, [class*='modal']").first
            if await modal.count() == 0 or not await modal.is_visible():
                return False

            print("[TABLE] Buy-in dialog detected.", flush=True)
            buyin_amount = 0

            # 读取买入金额输入框
            buyin_input = self.tm.page.locator("input[type='number']").first
            if await buyin_input.count() > 0 and await buyin_input.is_visible():
                try:
                    value = await buyin_input.input_value()
                    if value:
                        buyin_amount = int(float(value))
                        print(f"[TABLE] Buy-in input value: {buyin_amount}", flush=True)
                except Exception as e:
                    print(f"[TABLE] Error reading buyin input: {e}", flush=True)

            # 从显示区域读取买入金额
            if buyin_amount == 0:
                chips_display = self.tm.page.locator(".BuyIn__chips, .chips-display, [class*='buyIn']").first
                if await chips_display.count() > 0 and await chips_display.is_visible():
                    try:
                        text = await chips_display.text_content()
                        match = re.search(r'(\d+)', text)
                        if match:
                            buyin_amount = int(match.group(1))
                            print(f"[TABLE] Buy-in from display: {buyin_amount}", flush=True)
                    except Exception:
                        pass

            # 查找确认按钮 - 尝试多种可能的选择器
            confirm_btn = None

            # 1. 先尝试常见的确认按钮文本
            for btn_text in ["Confirm", "OK", "Buy", "Submit", "确认", "买入"]:
                btn = self.tm.page.get_by_role("button", name=re.compile(btn_text, re.I)).first
                if await btn.count() > 0 and await btn.is_visible():
                    confirm_btn = btn
                    print(f"[TABLE] Found confirm button with text: {btn_text}", flush=True)
                    break

            # 2. 如果没找到，尝试通用的按钮选择器
            if not confirm_btn:
                btn = self.tm.page.locator("button.Button--primary, button[type='submit'], .modal button").first
                if await btn.count() > 0 and await btn.is_visible():
                    confirm_btn = btn
                    print("[TABLE] Found confirm button via selector.", flush=True)

            if confirm_btn:
                print(f"[TABLE] Clicking confirm button (amount: {buyin_amount})...", flush=True)
                await confirm_btn.click()
                await asyncio.sleep(2)
                self.tm.is_sitting = True
                if buyin_amount > 0:
                    self.tm.total_buyin += buyin_amount
                    # 设置初始筹码（如果还未设置）
                    if self.tm.initial_chips is None:
                        self.tm.initial_chips = buyin_amount
                        print(f"[TABLE] Initial chips set: {self.tm.initial_chips}", flush=True)
                    print(f"[TABLE] Total buyin updated: {self.tm.total_buyin}", flush=True)
                return True
            else:
                print("[TABLE] Buy-in dialog found but no confirm button.", flush=True)
        except Exception as e:
            print(f"[TABLE] Error in _confirm_buyin_dialog: {e}", flush=True)
        return False

    async def check_overlays(self):
        try:
            for btn_text in ["I'm back", "Sit in", "Resume"]:
                btn = self.tm.page.get_by_role("button", name=re.compile(btn_text, re.I)).first
                if await btn.count() > 0 and await btn.is_visible():
                    print(f"[TABLE] Handling overlay: {btn_text}", flush=True)
                    await btn.click()
                    await asyncio.sleep(1)
        except Exception:
            pass

    async def _find_my_seat(self):
        """查找自己的座位元素和座位ID。使用WebSocket中捕获的my_seat_id。"""
        try:
            # 优先使用WebSocket中捕获的座位ID
            if self.tm.state.my_seat_id is not None:
                seat_id = self.tm.state.my_seat_id
                # 根据座位ID查找对应的座位元素
                seat_selector = f".Seat--{seat_id}, [data-seat-id='{seat_id}']"
                seat_elem = self.tm.page.locator(seat_selector).first
                if await seat_elem.count() > 0:
                    print(f"[LIFECYCLE] Found seat element by ID: {seat_id}", flush=True)
                    return seat_elem, seat_id
                # 如果找不到特定选择器，尝试查找所有座位
                all_seats = await self.tm.page.locator(".Seat").all()
                for seat in all_seats:
                    try:
                        seat_class = await seat.get_attribute("class")
                        import re
                        match = re.search(r'Seat--(\d+)', seat_class or "")
                        if match and int(match.group(1)) == seat_id:
                            print(f"[LIFECYCLE] Found seat element by class: {seat_id}", flush=True)
                            return seat, seat_id
                    except Exception:
                        continue

            # 回退方案：尝试通过username查找（如果配置了）
            username = self.tm.settings.get("player", {}).get("username", "").strip()
            if username:
                seat_users = self.tm.page.locator(".Seat__username")
                count = await seat_users.count()
                for i in range(count):
                    el = seat_users.nth(i)
                    text = await el.text_content()
                    if text and username.lower() in text.lower():
                        seat_elem = el.locator("xpath=ancestor::div[contains(@class, 'Seat')][1]")
                        try:
                            seat_class = await seat_elem.get_attribute("class")
                            import re
                            match = re.search(r'Seat--(\d+)', seat_class or "")
                            if match:
                                seat_id = int(match.group(1))
                                self.tm.state.my_seat_id = seat_id
                                print(f"[LIFECYCLE] Found seat by username: {seat_id}", flush=True)
                                return seat_elem, seat_id
                        except Exception:
                            pass

            print(f"[LIFECYCLE] Could not find my seat (my_seat_id={self.tm.state.my_seat_id})", flush=True)
        except Exception as e:
            print(f"[LIFECYCLE] Error finding my seat: {e}", flush=True)
        return None, None

    def get_exit_status(self) -> dict:
        """
        获取当前退出条件的状态信息，供 TableManager 做决策。
        
        Returns:
            dict 包含各种退出条件的状态
        """
        status = {
            "should_exit": False,
            "reason": None,
            "table_full": self._table_full,
            "stop_loss_triggered": False,
            "take_profit_triggered": False,
            "low_chips": False,
            "max_chips": False,
            "no_other_players": False,
            "max_cycles_reached": False,
            "empty_table_elapsed": 0.0,
            "profit": 0,
            "current_chips": self.tm.state.total_chips or 0,
        }
        
        if self.tm.initial_chips is None:
            return status
        
        # 检查桌子满了
        if self._table_full:
            status["should_exit"] = True
            status["reason"] = "table_full"
            return status
        
        # 计算盈亏 - 使用检测到的big_blind或配置的默认值
        if self.tm.big_blind > 0:
            bb = self.tm.big_blind
        else:
            # 从配置读取默认stakes
            try:
                import yaml
                with open("config/settings.yaml", 'r') as f:
                    config = yaml.safe_load(f)
                    stakes_str = config.get("game", {}).get("preferred_stakes", "1/2")
                    parts = stakes_str.split("/")
                    if len(parts) >= 2:
                        bb = int(parts[1])
                    else:
                        bb = 2  # 默认2
            except Exception:
                bb = 2  # 默认2

        stop_loss = bb * self.tm.stop_loss_bb
        take_profit = bb * self.tm.take_profit_bb
        low_chips = bb * self.tm.low_chips_bb
        max_chips = bb * self.tm.max_chips_bb

        current = self.tm.state.total_chips or 0
        profit = current - self.tm.initial_chips
        status["profit"] = profit

        if profit <= -stop_loss:
            status["stop_loss_triggered"] = True
            status["should_exit"] = True
            status["reason"] = f"stop_loss: {profit}"

        if profit >= take_profit:
            status["take_profit_triggered"] = True
            status["should_exit"] = True
            status["reason"] = f"take_profit: +{profit}"

        if current < low_chips and self.tm.is_sitting:
            status["low_chips"] = True
            status["should_exit"] = True
            status["reason"] = f"low_chips: {current}"

        # 检查筹码上限（当前筹码超过指定BB量）
        if current > max_chips and self.tm.is_sitting:
            status["max_chips"] = True
            status["should_exit"] = True
            status["reason"] = f"max_chips: {current} (>{max_chips})"
        
        # 检查其他活跃玩家
        other_active_players = [
            p for s, p in self.tm.state.players.items() 
            if s != self.tm.state.my_seat_id and p.status not in ["sit_out", "folded"]
        ]
        
        if self.tm.is_sitting and len(other_active_players) == 0:
            now = asyncio.get_event_loop().time()
            if self._empty_table_since is None:
                self._empty_table_since = now
                print(f"[TABLE] No other active players. Starting {self._SITOUT_LEAVE_DELAY}s grace period.", flush=True)
            
            elapsed = now - self._empty_table_since
            status["empty_table_elapsed"] = elapsed
            status["no_other_players"] = elapsed >= self._SITOUT_LEAVE_DELAY
            
            if status["no_other_players"]:
                status["should_exit"] = True
                status["reason"] = f"no_other_players: {elapsed:.1f}s"
        else:
            if self._empty_table_since is not None:
                print("[TABLE] Active players detected. Resetting sit-out timer.", flush=True)
                self._empty_table_since = None
        
        # 检查最大圈数
        if self.tm.dealer_cycle_count >= self.tm.max_cycles:
            status["max_cycles_reached"] = True
            status["should_exit"] = True
            status["reason"] = f"max_cycles: {self.tm.dealer_cycle_count}"
        
        return status
    
    async def check_exit_conditions(self):
        """兼容旧接口，返回是否应该退出。"""
        status = self.get_exit_status()
        if status["should_exit"] and status["reason"]:
            print(f"[TABLE] Exit condition: {status['reason']}", flush=True)
        return status["should_exit"]

    async def leave_table(self, navigate_to_lobby: bool = True):
        """
        离开桌子。
        
        Args:
            navigate_to_lobby: 是否导航到大厅找新桌子（True=是，False=关闭页面）
        """
        print(f"[TABLE] Leaving table {self.tm.page.url}...", flush=True)
        try:
            # 1. 点击 Stand Up（站起但留在桌子）
            stand_up = self.tm.page.get_by_role("button", name=re.compile(r"Stand\s*Up|站起", re.I)).first
            if await stand_up.count() > 0 and await stand_up.is_visible():
                print("[TABLE] Clicking Stand Up...", flush=True)
                await stand_up.click()
                await asyncio.sleep(2)
            else:
                print("[TABLE] Stand Up button not found, proceeding to Leave...", flush=True)

            # 2. 如果需要导航到大厅，直接跳转
            if navigate_to_lobby:
                print("[TABLE] Navigating to lobby to find next table...", flush=True)
                try:
                    await self.tm.page.goto("https://www.casino.org/replaypoker/lobby/rings", timeout=30000)
                    await asyncio.sleep(3)
                    print("[TABLE] Navigated to lobby.", flush=True)
                except Exception as e:
                    print(f"[TABLE] Failed to navigate to lobby: {e}", flush=True)
                finally:
                    # 标记为已关闭（让 BrowserManager 清理并找新桌子）
                    self.tm.is_closed = True
                    self.tm.exit_requested = True
                return

            # 3. 否则，完全离开桌子（关闭页面）
            leave = self.tm.page.get_by_role("button", name=re.compile(r"Leave|离开牌桌", re.I)).first
            if await leave.count() > 0 and await leave.is_visible():
                print("[TABLE] Clicking Leave...", flush=True)
                await leave.click()
                await asyncio.sleep(2)

            leave_confirm = self.tm.page.get_by_role("button", name=re.compile(r"Leave Table|确认离开", re.I)).first
            if await leave_confirm.count() > 0 and await leave_confirm.is_visible():
                await leave_confirm.click()
                await asyncio.sleep(2)

            if not self.tm.page.is_closed():
                await self.tm.page.close()

        except Exception as e:
            print(f"[TABLE] Error leaving table: {e}", flush=True)
            try:
                await self.tm.page.close()
            except Exception:
                pass
        finally:
            self.tm.is_closed = True
            self.tm.exit_requested = True
