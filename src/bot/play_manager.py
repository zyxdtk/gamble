import asyncio
import re
from .utils import human_delay
from ..brain.brain_manager import BrainManager
from ..utils.logger import bot_logger


class PlayManager:
    """Manages parsing game state from DOM, action button discovery, and action execution."""
    
    def __init__(self, table_manager):
        self.tm = table_manager
        self.brain_mgr = BrainManager()
        self._brain_created = False
    
    def ensure_brain_exists(self, strategy_type: str) -> None:
        if not self._brain_created:
            table_id = str(id(self.tm))
            self.brain_mgr.create_brain(table_id, strategy_type)
            self._brain_created = True
    
    def update_brain_state(self) -> None:
        table_id = str(id(self.tm))
        self.brain_mgr.update_brain(table_id, "state_update", {"state": self.tm.state})
    
    def request_decision(self) -> dict | None:
        table_id = str(id(self.tm))
        return self.brain_mgr.get_decision(table_id, self.tm.state)
    
    def reset_brain(self) -> None:
        table_id = str(id(self.tm))
        self.brain_mgr.reset_brain(table_id)
    
    def remove_brain(self) -> None:
        table_id = str(id(self.tm))
        self.brain_mgr.remove_brain(table_id)
        self._brain_created = False
        
    async def update_state_from_dom(self):
        if self.tm.is_closed:
            return
        try:
            await self._update_dealer_cycle()
            await self._detect_big_blind()

            pot_elem = self.tm.page.locator(".Pot__value").first
            if await pot_elem.count() > 0:
                pot_text = await pot_elem.text_content(timeout=500)
                if pot_text:
                    val = re.sub(r"[^\d]", "", pot_text)
                    if val:
                        self.tm.state.pot = int(val)

            my_seat, seat_id = await self.tm.lifecycle_mgr._find_my_seat()
            if my_seat and self.tm.is_sitting:
                chips_elem = my_seat.locator(".Stack__value, .Seat__stack").first
                if await chips_elem.count() > 0:
                    chips_text = await chips_elem.text_content(timeout=500)
                    val = re.sub(r"[^\d]", "", chips_text)
                    if val:
                        self.tm.state.total_chips = int(val)
                        if self.tm.starting_stack is None:
                            self.tm.starting_stack = self.tm.state.total_chips
                            bot_logger.info(f"初始起始筹码: {self.tm.starting_stack}")

            buttons = await self.find_action_buttons()
            self.tm.state.available_actions = list(buttons.keys())

            # [FIX] 如果找到操作按钮，说明轮到我行动
            if buttons and self.tm.state.my_seat_id is not None:
                my_player = self.tm.state.players.get(self.tm.state.my_seat_id)
                if my_player:
                    my_player.is_acting = True
                    self.tm.state.active_seat = self.tm.state.my_seat_id
            elif not buttons:
                # [FIX] 如果没有可用按钮，确保清除 acting 状态
                if self.tm.state.my_seat_id is not None:
                    my_player = self.tm.state.players.get(self.tm.state.my_seat_id)
                    if my_player:
                        my_player.is_acting = False

            # 提取 to_call (跟注金额)
            self.tm.state.to_call = 0
            if "call" in buttons:
                btn = buttons["call"]
                label = await btn.text_content()
                digits = re.sub(r"[^\d]", "", label)
                if digits:
                    self.tm.state.to_call = int(digits)
                    bot_logger.debug(f"Detected to_call: {self.tm.state.to_call}")

            self.tm.state.min_raise = 0
            if "raise" in buttons or "bet" in buttons:
                btn = buttons.get("raise") or buttons.get("bet")
                label = await btn.text_content()
                digits = re.sub(r"[^\d]", "", label)
                if digits:
                    self.tm.state.min_raise = int(digits)
            
            self.update_brain_state()

        except Exception:
            pass

    async def _detect_big_blind(self):
        if self.tm.is_closed or self.tm.big_blind > 0:
            return
        try:
            # 尝试多种选择器检测盲注信息
            selectors = [
                "[class*='Stakes']",
                "[class*='Blinds']",
                "[class*='blind']",
                "[class*='stakes']",
                ".TableInfo__stakes",
                ".TableInfo__blinds",
                "[data-testid*='stakes']",
                "[data-testid*='blind']",
            ]
            for sel in selectors:
                try:
                    el = self.tm.page.locator(sel).first
                    if await el.count() > 0:
                        text = (await el.text_content(timeout=500) or "").strip()
                        if text:
                            parsed = self._parse_stakes_string(text)
                            if parsed > 0:
                                self.tm.big_blind = parsed
                                bot_logger.info(f"Big blind detected: {parsed} from '{text}'")
                                return
                except Exception:
                    continue
        except Exception as e:
            bot_logger.error(f"Error detecting big blind: {e}")

    def _parse_stakes_string(self, text: str) -> int:
        if not text:
            return 0
        parts = text.split("/")
        if len(parts) >= 2:
            bb_str = parts[1].strip().lower()
            return self._parse_amount_string(bb_str)
        return 0
        
    def _parse_amount_string(self, s: str) -> int:
        multiplier = 1
        if s.endswith("k"):
            multiplier = 1000
            s = s[:-1]
        elif s.endswith("m"):
            multiplier = 1000000
            s = s[:-1]
        val = re.sub(r"[^\d\.]", "", s)
        try:
            return int(float(val) * multiplier)
        except (ValueError, TypeError):
            return 0

    async def _detect_dealer_seat(self) -> int | None:
        if self.tm.is_closed:
            return None
        try:
            dealer_el = self.tm.page.locator(".DealerButton").first
            if await dealer_el.count() > 0:
                cls = (await dealer_el.get_attribute("class") or "")
                m = re.search(r"Position--(\d+)", cls)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
        return None

    async def _update_dealer_cycle(self):
        seat = await self._detect_dealer_seat()
        if seat is None or seat == self.tm._last_dealer_seat:
            return

        self.tm._last_dealer_seat = seat
        
        if len(self.tm._unique_seats_this_cycle) >= 2 and seat in self.tm._unique_seats_this_cycle:
            self.tm.dealer_cycle_count += 1
            bot_logger.info(
                f"✅ 完成第 {self.tm.dealer_cycle_count} 圈！"
                f"共玩 {self.tm.hands_played} 手，"
                f"本圈座位: {sorted(self.tm._unique_seats_this_cycle)}"
            )
            self.tm._unique_seats_this_cycle = {seat}
        else:
            if not self.tm._unique_seats_this_cycle:
                bot_logger.info(f"庄家起始位: {seat}，开始记录周期。")
            self.tm._unique_seats_this_cycle.add(seat)

    async def find_action_buttons(self):
        buttons = {}
        if self.tm.is_closed:
            return buttons
        # 修改匹配项：All In 可能带有空格或连字符
        targets = ["Fold", "Call", "Check", "Raise", "Bet", ("All In", "All[ -]?In")]
        for item in targets:
            try:
                if isinstance(item, tuple):
                    name, pattern = item
                else:
                    name, pattern = item, f"^{item}"
                
                locator = self.tm.page.get_by_role("button", name=re.compile(pattern, re.I))
                count = await locator.count()
                if count > 0:
                    first = locator.first
                    if await first.is_visible():
                        buttons[name.lower()] = first
            except Exception as e:
                bot_logger.debug(f"查找按钮 {name} 时出错: {e}")
                continue
        return buttons

    async def perform_click(self, action_text: str, amount: int = 0, bet_size_hint: str | None = None):
        buttons = await self.find_action_buttons()
        actions_to_try = [a.strip().lower() for a in action_text.split("/")]
        await human_delay()
        
        for choice in actions_to_try:
            target = None
            is_raise = False
            if choice == "fold": 
                target = buttons.get("fold")
            elif choice in ["check", "call"]: 
                # [FIX] 如果需要 Call 但按钮显示为 All In（筹码不足时），也应支持
                target = buttons.get("check") or buttons.get("call") or buttons.get("all in")
            elif choice in ["raise", "bet", "all-in", "all_in"]:
                target = buttons.get("bet") or buttons.get("raise") or buttons.get("all in")
                is_raise = True
            
            if target:
                if is_raise:
                    # [FIX] Replay Poker 的正确流程：先设置金额（控件与按钮同时可见），再点击 Raise/Bet 提交
                    # 不能先点击按钮：点击 Bet/Raise 会直接以最小加注提交
                    amount_set = await self.set_raise_amount(amount=amount, bet_size_hint=bet_size_hint, pot=self.tm.state.pot)
                    if not amount_set:
                        bot_logger.warning("未能设置加注金额，仍然提交（将以最小加注执行）")
                    # [FIX] 设置金额后，按钮可能变成 All In，需要重新查找
                    await asyncio.sleep(0.3)
                    buttons = await self.find_action_buttons()
                    target = buttons.get("bet") or buttons.get("raise") or buttons.get("all in")
                    if not target:
                        bot_logger.error("设置金额后找不到提交按钮")
                        return False
                    # [FIX] 尝试点击可用的按钮，如果 Raise 不可用则尝试 All In
                    try:
                        # 先检查当前 target 是否 enabled
                        is_enabled = await target.is_enabled()
                        if not is_enabled:
                            # 尝试 All In 按钮
                            all_in_btn = buttons.get("all in")
                            if all_in_btn:
                                is_all_in_enabled = await all_in_btn.is_enabled()
                                if is_all_in_enabled:
                                    bot_logger.info("Raise 按钮不可用，切换到 All In")
                                    target = all_in_btn
                                else:
                                    bot_logger.warning("Raise 和 All In 按钮都不可用")
                                    return False
                            else:
                                bot_logger.warning("Raise 按钮不可用且找不到 All In")
                                return False
                        await target.click(timeout=5000)
                    except Exception as e:
                        bot_logger.warning(f"点击按钮失败（可能已超时自动fold）: {e}")
                        return False
                else:
                    try:
                        await target.click(timeout=5000)
                    except Exception as e:
                        bot_logger.warning(f"点击按钮失败（可能已超时自动fold）: {e}")
                        return False

                return True
        return False

    async def set_raise_amount(self, amount: int = 0, bet_size_hint: str | None = None, pot: int = 0):
        """点击 Raise/Bet 后，通过快捷按钮或 input 设置加注金额。
        
        优先级：
          1. 直接用 bet_size_hint 点对应快捷按钮（MIN/½POT/POT/MAX）
          2. 按 amount/pot 比例自动映射到最近快捷按钮
          3. 直接输入到 input 框（兜底）
        """
        page = self.tm.page
        await asyncio.sleep(0.4)
        
        # ── 快捷按钮映射 ──────────────────────────────────────────────────────────
        # 截图中按钮文本大致为："MIN" / "½ POT" / "POT" / "MAX"
        PRESET_BUTTONS = {
            "min":      ["MIN", "Min", "min"],
            "half_pot": ["½ POT", "1/2 POT", "1/2", "Half", "HALF"],
            "pot":      ["POT", "Pot"],
            "max":      ["MAX", "Max", "All In", "ALL IN"],
        }
        
        # 1. 如果没有 hint，根据 amount/pot 比例自动推断
        if bet_size_hint is None and pot > 0 and amount > 0:
            ratio = amount / pot
            if ratio > 1.5:
                bet_size_hint = "max"
            elif ratio > 0.75:
                bet_size_hint = "pot"
            elif ratio > 0.4:
                bet_size_hint = "half_pot"
            else:
                bet_size_hint = "min"
            bot_logger.info(f"自动推断加注档位: {bet_size_hint} (amount={amount}, pot={pot}, ratio={ratio:.2f})")
        
        # 1. 尝试点击对应的快捷按钮
        if bet_size_hint and bet_size_hint in PRESET_BUTTONS:
            # [ADD] 优先使用根据实战探测得到的精确 CSS 类名
            class_map = {
                "min": ".Preset--min",
                "half_pot": ".Preset--half",
                "pot": ".Preset--pot",
                "max": ".Preset--max"
            }
            if bet_size_hint in class_map:
                try:
                    p_btn = page.locator(class_map[bet_size_hint]).first
                    if await p_btn.count() > 0 and await p_btn.is_visible():
                        await p_btn.click()
                        bot_logger.info(f"✅ 通过精确类名点击快捷按钮 [{class_map[bet_size_hint]}]")
                        return True
                except Exception:
                    pass

            # [RETAIN] 备选：文本匹配逻辑 (保留原有灵活性)
            labels = PRESET_BUTTONS[bet_size_hint]
            for label in labels:
                try:
                    # 使用 Playwright 推荐的 get_by_role 配合正则
                    btn = page.get_by_role("button", name=re.compile(f".*{label}.*", re.I)).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await asyncio.sleep(0.1)
                        await btn.click()
                        bot_logger.info(f"✅ 通过 get_by_role 点击快捷按钮 [{label}] ({bet_size_hint})")
                        return True
                        
                    # 备选：传统的 has-text 选择器
                    selectors = [
                        f"button:has-text('{label}')",
                        f".m-bet-controls__preset:has-text('{label}')",
                        f".m-btn:has-text('{label}')",
                        f"[role='button']:has-text('{label}')",
                        f"div[class*='preset']:has-text('{label}')",
                    ]
                    
                    for selector in selectors:
                        el = page.locator(selector).first
                        if await el.count() > 0 and await el.is_visible():
                            await asyncio.sleep(0.1)
                            await el.click()
                            bot_logger.info(f"✅ 通过 selector 点击快捷按钮 [{label}] ({bet_size_hint})")
                            return True
                except Exception:
                    continue
        bot_logger.warning(f"未找到快捷按钮 ({bet_size_hint})，降级为 input 输入")
        
        # 3. 兜底：直接往 input 框填数字
        if amount <= 0:
            return False
            
        bot_logger.info(f"尝试通过 input 输入金额: {amount}...")
        
        # Replay Poker 的金额输入框结构：
        number_selectors = [
            ".BettingControls input",                       # [NEW] 实战探测最速选择器
            "input.NumberInput__input",                     # 常见类名
            ".NumberInput input",                           # 组件结构
            "input[inputmode='numeric']",                   # 属性特征
            "input[type='text'][pattern='[0-9]*']",         # 属性特征
            ".BettingControls [class*='input']",
            ".RaiseControls input",
            ".BetSlider input",
            "input[type='number']",
        ]
        
        # 先等待最多 2s，让控件渲染完成
        for _ in range(4):
            for sel in number_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        # 清空并输入金额
                        await el.click(click_count=3)
                        await page.keyboard.press("Control+a")
                        await el.fill(str(amount))
                        await asyncio.sleep(0.3)
                        await el.press("Enter")
                        bot_logger.info(f"✅ input 成功设置金额: {amount} (selector: {sel})")
                        return True
                except Exception:
                    continue
            await asyncio.sleep(0.5)
        
        bot_logger.warning(f"未找到任何金额控件，使用默认最小加注 (期望: {amount})")
        return False
