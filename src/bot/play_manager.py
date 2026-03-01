from __future__ import annotations
import re
from ..core.utils import human_delay
from ..engine.engine_manager import EngineManager


class PlayManager:
    """Manages parsing game state from DOM, action button discovery, and action execution."""
    
    def __init__(self, table_manager):
        self.tm = table_manager
        self.engine_mgr = EngineManager()
        self._brain_created = False
    
    def ensure_brain_exists(self, strategy_type: str) -> None:
        if not self._brain_created:
            table_id = str(id(self.tm))
            self.engine_mgr.create_brain(table_id, strategy_type)
            self._brain_created = True
    
    def update_brain_state(self) -> None:
        table_id = str(id(self.tm))
        self.engine_mgr.update_brain(table_id, self.tm.state)
    
    def request_decision(self) -> dict | None:
        table_id = str(id(self.tm))
        return self.engine_mgr.get_decision(table_id, self.tm.state)
    
    def reset_brain(self) -> None:
        table_id = str(id(self.tm))
        self.engine_mgr.reset_brain(table_id)
    
    def remove_brain(self) -> None:
        table_id = str(id(self.tm))
        self.engine_mgr.remove_brain(table_id)
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
                        if self.tm.initial_chips is None:
                            self.tm.initial_chips = self.tm.state.total_chips
                            # 同时记录买入金额，用于盈亏统计
                            self.tm.total_buyin = self.tm.state.total_chips
                            print(f"[TEST] 初始总筹码: {self.tm.initial_chips}, 买入: {self.tm.total_buyin}", flush=True)

            buttons = await self.find_action_buttons()
            self.tm.state.available_actions = list(buttons.keys())

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
                                print(f"[TABLE] Big blind detected: {parsed} from '{text}'", flush=True)
                                return
                except Exception:
                    continue
        except Exception as e:
            print(f"[TABLE] Error detecting big blind: {e}", flush=True)

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
        
        if len(self.tm._unique_seats_this_cycle) > 0 and seat in self.tm._unique_seats_this_cycle:
            self.tm.dealer_cycle_count += 1
            print(
                f"[CYCLE] ✅ 完成第 {self.tm.dealer_cycle_count} 圈！"
                f"共玩 {self.tm.hands_played} 手，"
                f"本圈座位: {sorted(self.tm._unique_seats_this_cycle)}",
                flush=True
            )
            self.tm._unique_seats_this_cycle = {seat}
        else:
            if not self.tm._unique_seats_this_cycle:
                print(f"[CYCLE] 庄家起始位: {seat}，开始记录周期。", flush=True)
            self.tm._unique_seats_this_cycle.add(seat)

    async def find_action_buttons(self):
        buttons = {}
        if self.tm.is_closed:
            return buttons
        targets = ["Fold", "Call", "Check", "Raise", "Bet", "All In"]
        try:
            for text in targets:
                locator = self.tm.page.get_by_role("button", name=re.compile(f"^{text}", re.I))
                if await locator.count() > 0 and await locator.first.is_visible():
                    buttons[text.lower()] = locator.first
        except Exception:
            pass
        return buttons

    async def perform_click(self, action_text: str):
        buttons = await self.find_action_buttons()
        actions_to_try = [a.strip().lower() for a in action_text.split("/")]
        await human_delay()
        
        for choice in actions_to_try:
            target = None
            if choice == "fold": 
                target = buttons.get("fold")
            elif choice in ["check", "call"]: 
                target = buttons.get("check") or buttons.get("call")
            elif choice in ["raise", "bet", "all-in"]: 
                target = buttons.get("bet") or buttons.get("raise") or buttons.get("all in")
            
            if target:
                await target.click()
                return True
        return False
