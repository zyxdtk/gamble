"""
ReplayPoker website adapter.
Implements WebsiteAdapter interface for ReplayPoker.
"""
import asyncio
import re
from typing import Dict, List, Optional, Any
from playwright.async_api import Page
from .base import WebsiteAdapter, TableInfo, TableFilter
from src.utils.logger import bot_logger, dom_logger
from ..human_delay import human_delay


class ReplayPokerAdapter(WebsiteAdapter):
    """Adapter for ReplayPoker website."""
    
    def __init__(self, preferred_stakes: str = "1/2"):
        super().__init__()
        self.preferred_stakes = preferred_stakes
    
    def get_name(self) -> str:
        return "ReplayPoker"
    
    def get_lobby_url(self) -> str:
        return "https://www.casino.org/replaypoker/lobby/rings"
    
    async def is_at_lobby(self, page: Page) -> bool:
        return "/lobby" in page.url
    
    async def is_at_table(self, page: Page) -> bool:
        return "/table/" in page.url
    
    async def get_available_tables(
        self, 
        page: Page, 
        filter: Optional[TableFilter] = None
    ) -> List[TableInfo]:
        """Get list of available tables from ReplayPoker lobby."""
        tables = []
        try:
            # 先检查当前URL是否在大厅
            current_url = page.url
            if "/lobby" not in current_url.lower() and "/play" not in current_url.lower():
                bot_logger.warning(f"Not in lobby page: {current_url}")
                # 尝试导航到大厅
                try:
                    await page.goto("https://www.casino.org/replaypoker/play/#/lobby")
                    await page.wait_for_load_state("networkidle")
                except Exception as e:
                    bot_logger.error(f"Failed to navigate to lobby: {e}")
            
            # 等待桌子链接出现（增加超时时间）
            try:
                await page.wait_for_selector("a[href*='/play/table/']", timeout=15000)
            except Exception as e:
                # 尝试刷新页面
                bot_logger.warning(f"Table selector not found, refreshing page...")
                await page.reload()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_selector("a[href*='/play/table/']", timeout=15000)
            
            stakes_filter = filter.stakes if filter else self.preferred_stakes
            
            # 方法1：查找所有带有座位状态的桌子行
            seat_classes = ["seats-yellow", "seats-green", "seats-red"]
            
            for seat_class in seat_classes:
                rows = page.locator(f".lobby-game:has(.{seat_class})")
                count = await rows.count()
                bot_logger.debug(f"Found {count} tables with class {seat_class}")
                
                for i in range(count):
                    row = rows.nth(i)
                    await self._extract_table_info(row, tables, stakes_filter)
            
            # 方法2：如果上面没找到，查找所有 .lobby-game 元素
            if not tables:
                rows = page.locator(".lobby-game")
                count = await rows.count()
                bot_logger.debug(f"Found {count} tables using .lobby-game selector")
                
                for i in range(count):
                    row = rows.nth(i)
                    await self._extract_table_info(row, tables, stakes_filter)
            
            # 方法3：兜底 - 获取所有包含 table 链接的元素
            if not tables:
                all_links = page.locator("a[href*='/play/table/']")
                count = await all_links.count()
                bot_logger.debug(f"Found {count} table links as fallback")
                
                for i in range(min(count, 20)):
                    href = await all_links.nth(i).get_attribute("href")
                    if href:
                        url = f"https://www.casino.org{href}" if href.startswith("/") else href
                        table_id = self.extract_table_id(url)
                        tables.append(TableInfo(
                            url=url,
                            table_id=table_id,
                            stakes=stakes_filter
                        ))
            
            bot_logger.info(f"Found {len(tables)} tables total")
            
        except Exception as e:
            bot_logger.error(f"Failed to get available tables: {e}")
        
        # 去重
        seen = set()
        unique_tables = []
        for table in tables:
            if table.url not in seen:
                seen.add(table.url)
                unique_tables.append(table)
        
        return unique_tables
    
    async def _extract_table_info(self, row, tables: list, stakes_filter: Optional[str]):
        """Extract table info from a row element."""
        try:
            # 筛选盲注级别
            if stakes_filter:
                row_text = await row.text_content()
                if row_text:
                    clean_text = row_text.replace(" ", "")
                    target = stakes_filter.strip().replace(" ", "")
                    if target and target not in clean_text:
                        return
            
            # 提取链接
            link = row.locator("a[href*='/play/table/']").first
            href = await link.get_attribute("href")
            if not href:
                return
            
            url = f"https://www.casino.org{href}" if href.startswith("/") else href
            table_id = self.extract_table_id(url)
            
            table_info = TableInfo(
                url=url,
                table_id=table_id,
                stakes=stakes_filter
            )
            
            # 尝试提取座位数
            try:
                seats_elem = row.locator("[class*='seats']").first
                if await seats_elem.count() > 0:
                    seats_text = await seats_elem.text_content()
                    if seats_text:
                        seats_match = re.search(r'(\d+)/(\d+)', seats_text.replace(' ', ''))
                        if seats_match:
                            table_info.players = int(seats_match.group(1))
                            table_info.max_players = int(seats_match.group(2))
            except Exception:
                pass
            
            tables.append(table_info)
        except Exception as e:
            bot_logger.debug(f"Failed to extract table info: {e}")
    
    async def get_best_available_table(
        self, 
        page: Page, 
        exclude_visited: bool = True,
        filter: Optional[TableFilter] = None
    ) -> Optional[TableInfo]:
        """Get the best available table based on criteria."""
        all_tables = await self.get_available_tables(page, filter)
        
        if not all_tables:
            return None
        
        # 过滤已访问的桌子
        if exclude_visited:
            available = [
                t for t in all_tables 
                if t.table_id is None or not self.is_table_visited(t.table_id)
            ]
        else:
            available = all_tables
        
        if not available:
            bot_logger.warning("All available tables have been visited recently.")
            # 返回一个（即使已访问）
            return all_tables[0]
        
        # 选择策略：优先选择玩家多的桌子
        available.sort(key=lambda t: t.players, reverse=True)
        return available[0]
    
    async def open_table(self, page: Page, url: str) -> bool:
        try:
            # 记录为已访问
            table_id = self.extract_table_id(url)
            if table_id:
                self.mark_table_visited(table_id)
            
            await page.goto(url, timeout=20000)
            await asyncio.sleep(3)
            return True
        except Exception as e:
            bot_logger.error(f"Failed to open table {url}: {e}")
            return False
    
    async def try_sit_down(
        self, 
        page: Page, 
        buyin_amount: Optional[int] = None,
        auto_seat: bool = True
    ) -> bool:
        """Try to sit down at ReplayPoker table."""
        try:
            # Check if page is still valid
            if page.is_closed():
                bot_logger.error("Page is closed, cannot sit down")
                return False
            
            if auto_seat:
                # 方法1: 通过类选择器查找按钮（更可靠）
                seat_btn = page.locator(".SitNowControls .Button")
                if await seat_btn.count() > 0 and await seat_btn.is_visible():
                    await seat_btn.first.click()
                    await asyncio.sleep(1)
                    bot_logger.info("Clicked 'Seat Me Anywhere' button (by class)")
                    return True
                
                # 方法2: 通过文本查找
                seat_anywhere = page.get_by_text("Seat Me Anywhere", exact=False)
                if await seat_anywhere.count() > 0 and await seat_anywhere.is_visible():
                    await seat_anywhere.click()
                    await asyncio.sleep(1)
                    bot_logger.info("Clicked 'Seat Me Anywhere' button (by text)")
                    return True
                
                # 方法3: 查找包含 Seat 的按钮
                seat_btn_text = page.get_by_text("Seat", exact=False)
                if await seat_btn_text.count() > 0 and await seat_btn_text.is_visible():
                    await seat_btn_text.click()
                    await asyncio.sleep(1)
                    bot_logger.info("Clicked seat button")
                    return True
            
            # TODO: 支持手动选择座位和设置买入
            return False
        except Exception as e:
            bot_logger.error(f"Failed to sit down: {e}")
            return False
    
    async def set_buyin_amount(self, page: Page, amount: int) -> bool:
        """Set buy-in amount in the buy-in popup."""
        try:
            # 尝试找到买入金额输入框
            input_selectors = [
                "input[name*='buyin']",
                "input[name*='amount']",
                ".BuyinModal input",
                ".buyin-input",
                "input[type='number']"
            ]
            
            for selector in input_selectors:
                inp = page.locator(selector).first
                if await inp.count() > 0 and await inp.is_visible():
                    await inp.click(click_count=3)
                    await inp.fill(str(amount))
                    await asyncio.sleep(0.3)
                    bot_logger.info(f"Set buy-in amount to {amount}")
                    return True
            
            # 如果没找到输入框，尝试点击预设金额按钮
            preset_buttons = page.locator("button", has_text=str(amount))
            if await preset_buttons.count() > 0:
                await preset_buttons.first.click()
                await asyncio.sleep(0.3)
                bot_logger.info(f"Selected preset buy-in {amount}")
                return True
            
            bot_logger.warning("Buy-in input not found")
            return False
        except Exception as e:
            bot_logger.error(f"Failed to set buy-in amount: {e}")
            return False
    
    async def select_default_buyin(self, page: Page) -> bool:
        """Select the default buy-in amount (middle value or min/max)."""
        try:
            # 方法1: 查找预设按钮 (Min/Max)
            preset_buttons = page.locator(".BuyInModal__presets .Button")
            if await preset_buttons.count() > 0:
                # 如果有多个预设，选择第一个（Min）
                await preset_buttons.first.click()
                await asyncio.sleep(0.3)
                bot_logger.info("Selected preset buy-in option")
                return True
            
            # 方法2: 查找带有 preset 类的按钮
            preset_buttons = page.locator("[class*='BuyInModal__preset']")
            if await preset_buttons.count() > 0:
                await preset_buttons.first.click()
                await asyncio.sleep(0.3)
                bot_logger.info("Selected buy-in preset")
                return True
            
            # 方法3: 查找带有 "Min" 或 "Max" 文字的按钮
            for text in ["Min", "Max", "Default"]:
                btn = page.get_by_text(text, exact=False)
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.3)
                    bot_logger.info(f"Selected '{text}' buy-in")
                    return True
            
            bot_logger.warning("No buy-in preset button found")
            return False
        except Exception as e:
            bot_logger.error(f"Failed to select default buy-in: {e}")
            return False
    
    async def select_min_buyin(self, page: Page) -> bool:
        """Select minimum buy-in amount."""
        try:
            # 等待 buy-in 弹窗出现
            await asyncio.sleep(0.5)

            # 方法1: 通过类名查找 Min 按钮
            min_btn = page.locator(".BuyInModal__preset--min")
            if await min_btn.count() > 0 and await min_btn.is_visible():
                # disabled 说明当前 amount 已经是 min，状态已满足，无需点击
                if await min_btn.is_disabled():
                    bot_logger.info("Min buy-in 按钮已 disabled（当前就是 min），跳过")
                    return True
                await min_btn.click()
                await asyncio.sleep(0.3)
                bot_logger.info("Selected minimum buy-in (by class)")
                return True

            # 方法2: 通过包含 "Min" 的按钮文本查找（限制在 buy-in 弹窗内）
            buyin_modal = page.locator(".BuyInModal").first
            if await buyin_modal.count() > 0:
                min_text_btn = buyin_modal.get_by_text("Min", exact=False)
                if await min_text_btn.count() > 0:
                    for i in range(await min_text_btn.count()):
                        btn = min_text_btn.nth(i)
                        if await btn.is_visible():
                            if await btn.is_disabled():
                                bot_logger.info("Min buy-in 按钮已 disabled（当前就是 min），跳过")
                                return True
                            await btn.click()
                            await asyncio.sleep(0.3)
                            bot_logger.info("Selected minimum buy-in (by text)")
                            return True

            # 方法3: 查找 BuyInModal 内的第一个按钮
            preset_btns = page.locator(".BuyInModal .Button")
            if await preset_btns.count() > 0:
                first_btn = preset_btns.first
                if await first_btn.is_visible():
                    if await first_btn.is_disabled():
                        bot_logger.info("First buy-in 按钮已 disabled，跳过")
                        return True
                    await first_btn.click()
                    await asyncio.sleep(0.3)
                    bot_logger.info("Selected first buy-in preset (fallback)")
                    return True

            bot_logger.warning("Min buy-in button not found")
            return False
        except Exception as e:
            bot_logger.error(f"Failed to select minimum buy-in: {e}")
            return False

    async def select_max_buyin(self, page: Page) -> bool:
        """Select maximum buy-in amount."""
        try:
            # 等待 buy-in 弹窗出现
            await asyncio.sleep(0.5)

            # 方法1: 通过类名查找 Max 按钮
            max_btn = page.locator(".BuyInModal__preset--max")
            if await max_btn.count() > 0 and await max_btn.is_visible():
                if await max_btn.is_disabled():
                    bot_logger.info("Max buy-in 按钮已 disabled（当前就是 max），跳过")
                    return True
                await max_btn.click()
                await asyncio.sleep(0.3)
                bot_logger.info("Selected maximum buy-in (by class)")
                return True

            # 方法2: 通过包含 "Max" 的按钮文本查找（限制在 buy-in 弹窗内）
            buyin_modal = page.locator(".BuyInModal").first
            if await buyin_modal.count() > 0:
                max_text_btn = buyin_modal.get_by_text("Max", exact=False)
                if await max_text_btn.count() > 0:
                    for i in range(await max_text_btn.count()):
                        btn = max_text_btn.nth(i)
                        if await btn.is_visible():
                            if await btn.is_disabled():
                                bot_logger.info("Max buy-in 按钮已 disabled（当前就是 max），跳过")
                                return True
                            await btn.click()
                            await asyncio.sleep(0.3)
                            bot_logger.info("Selected maximum buy-in (by text)")
                            return True

            # 方法3: 查找 BuyInModal 内的最后一个按钮
            preset_btns = page.locator(".BuyInModal .Button")
            count = await preset_btns.count()
            if count > 0:
                last_btn = preset_btns.nth(count - 1)
                if await last_btn.is_visible():
                    if await last_btn.is_disabled():
                        bot_logger.info("Last buy-in 按钮已 disabled，跳过")
                        return True
                    await last_btn.click()
                    await asyncio.sleep(0.3)
                    bot_logger.info("Selected last buy-in preset (fallback)")
                    return True
            
            bot_logger.warning("Max buy-in button not found")
            return False
        except Exception as e:
            bot_logger.error(f"Failed to select maximum buy-in: {e}")
            return False
    
    async def confirm_buyin(self, page: Page) -> bool:
        """Confirm buy-in and sit down."""
        try:
            # 优先通过类名查找（更精确）
            ok_btn = page.locator(".BuyInModal__button--submit, .Button--submit")
            if await ok_btn.count() > 0 and await ok_btn.is_visible():
                await ok_btn.click()
                await asyncio.sleep(1)
                bot_logger.info("Confirmed buy-in with submit button")
                return True
            
            # 备用：通过类名查找按钮组内的按钮
            modal_btn = page.locator(".BuyInModal__button")
            if await modal_btn.count() > 0 and await modal_btn.is_visible():
                # 找到第二个按钮（通常 Cancel 是第一个，OK 是第二个）
                buttons = modal_btn.all()
                if len(buttons) >= 2:
                    await buttons[1].click()
                    await asyncio.sleep(1)
                    bot_logger.info("Confirmed buy-in with second modal button")
                    return True
            
            # 最后尝试通过文字查找（使用 exact=True 避免匹配玩家名字）
            confirm_texts = ["Ok", "Confirm", "Sit Down", "Buy In", "Join Table"]
            
            for text in confirm_texts:
                btn = page.get_by_text(text, exact=True)
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(1)
                    bot_logger.info(f"Confirmed buy-in with '{text}' button")
                    return True
            
            return False
        except Exception as e:
            bot_logger.error(f"Failed to confirm buy-in: {e}")
            return False
    
    async def cancel_buyin(self, page: Page) -> bool:
        """Cancel the buy-in popup."""
        try:
            cancel_texts = ["Cancel", "Close", "X"]
            
            for text in cancel_texts:
                btn = page.get_by_text(text, exact=False)
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.3)
                    bot_logger.info(f"Cancelled buy-in with '{text}' button")
                    return True
            
            # 尝试点击弹窗外部关闭
            close_btn = page.locator(".modal-close, [aria-label*='Close'], .close-icon")
            if await close_btn.count() > 0 and await close_btn.is_visible():
                await close_btn.first.click()
                await asyncio.sleep(0.3)
                bot_logger.info("Cancelled buy-in with close button")
                return True
            
            return False
        except Exception as e:
            bot_logger.error(f"Failed to cancel buy-in: {e}")
            return False
    
    async def get_game_state(self, page: Page) -> Dict[str, Any]:
        """Extract game state from ReplayPoker page (DOM only)."""
        state = {
            "pot": 0,
            "pot_rake": 0,
            "rake": 0,
            "community_cards": [],
            "my_seat_id": None,
            "is_my_turn": False,
            "to_call": 0,
            "min_raise": 0,
            "players": {}
        }
        try:
            # 1. 提取底池
            # ReplayPoker 有两个 pot 显示：
            #   - .Pot__value span: 原始底池（下注总额，在页面上方）
            #   - .Stack--pot .Stack__value span: 抽税后底池（在公共牌下方）
            pot_elem = page.locator(".Pot__value span").first
            if await pot_elem.count() > 0:
                pot_text = await pot_elem.text_content(timeout=500)
                if pot_text:
                    m = re.search(r'([\d,]+)', pot_text)
                    if m:
                        state["pot"] = int(m.group(1).replace(",", ""))

            pot_rake_elem = page.locator(".Stack--pot .Stack__value span").first
            if await pot_rake_elem.count() > 0:
                pot_rake_text = await pot_rake_elem.text_content(timeout=500)
                if pot_rake_text:
                    m = re.search(r'([\d,]+)', pot_rake_text)
                    if m:
                        state["pot_rake"] = int(m.group(1).replace(",", ""))

            rake_elem = page.locator(".Stack--rake .Stack__value").first
            if await rake_elem.count() > 0:
                rake_text = await rake_elem.text_content(timeout=500)
                if rake_text:
                    m = re.search(r'([\d,]+)', rake_text)
                    if m:
                        state["rake"] = int(m.group(1).replace(",", ""))
            dom_logger.debug(f"[DOM] pot={state['pot']}, pot_rake={state.get('pot_rake', 0)}, rake={state.get('rake', 0)}")
            
            # 2. 提取公共牌
            community_cards = []
            # [FIX] 只在 Cards__communityCards 内查找，避免匹配手牌的 Card--0/Card--1
            # 方法1: 从社区牌区域提取可见的牌
            card_elems = page.locator(".Cards__communityCards .Card--withValue")
            for i in range(await card_elems.count()):
                card_class = await card_elems.nth(i).get_attribute("class") or ""
                card_match = re.search(r'Card--([A-Z][a-z])', card_class)
                if card_match:
                    community_cards.append(card_match.group(1))

            # 方法2: 从聊天消息中提取——收集最近一手牌的所有 "Dealt to board" 消息
            # flop 是 [ 6c 3h 4h ]，turn/river 是逐张 [ 6h ], [ 4s ]
            if not community_cards:
                chat_messages = page.locator(".ChatMessage--dealer")
                count = await chat_messages.count()
                for i in range(count - 1, -1, -1):
                    msg = chat_messages.nth(i)
                    msg_text = await msg.text_content()
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
            
            state["community_cards"] = community_cards
            dom_logger.debug(f"[DOM] community_cards={community_cards}")

            # 3. 提取我的座位ID
            # [FIX] ReplayPoker 使用 .Seat--currentUser 而不是 .Seat--me
            my_seat_elem = page.locator(".Seat--currentUser").first
            if await my_seat_elem.count() > 0:
                # 尝试从 class 中提取位置信息，例如 "Position Position--4"
                seat_class = await my_seat_elem.get_attribute("class") or ""
                position_match = re.search(r'Position--(\d+)', seat_class)
                if position_match:
                    state["my_seat_id"] = int(position_match.group(1))
            dom_logger.debug(f"[DOM] my_seat_id={state['my_seat_id']}")
            
            # 检测是否轮到用户行动（需要多个条件满足）
            is_my_turn = False
            turn_checks = []
            
            # 方法1: 检查是否有 "Your Turn" 或类似的提示
            your_turn_elem = page.locator(".HandStatus__text", has_text=re.compile("Your Turn", re.IGNORECASE))
            if await your_turn_elem.count() > 0 and await your_turn_elem.is_visible():
                turn_checks.append(True)
            else:
                # 尝试其他选择器
                your_turn_elem2 = page.locator("[class*='TurnIndicator'], [class*='yourTurn']")
                if await your_turn_elem2.count() > 0 and await your_turn_elem2.is_visible():
                    turn_checks.append(True)
            
            # 方法2: 检查自己座位是否有 "currentPlayer" 样式
            my_seat = page.locator(".Seat--currentUser")
            if await my_seat.count() > 0:
                class_name = await my_seat.first.get_attribute("class")
                if class_name and ("currentPlayer" in class_name or "active" in class_name or "turn" in class_name.lower()):
                    turn_checks.append(True)
            
            # 方法3: 检查行动按钮是否存在且可点击
            # [FIX] ReplayPoker 使用 .BettingControls__actions 而不是 .ActionButtons
            action_buttons = page.locator(".BettingControls__actions button")
            if await action_buttons.count() > 0:
                for i in range(await action_buttons.count()):
                    btn = action_buttons.nth(i)
                    disabled = await btn.get_attribute("disabled")
                    if disabled is None:
                        # 再检查按钮是否不是灰色（通过样式）
                        style = await btn.get_attribute("style") or ""
                        opacity_match = re.search(r'opacity:\s*([\d.]+)', style)
                        if opacity_match:
                            opacity = float(opacity_match.group(1))
                            if opacity < 0.5:
                                continue
                        turn_checks.append(True)
                        break
            
            # 方法4: 检查是否显示 "You" 或 "Your" 标签
            you_label = page.locator("text=You", exact=False)
            if await you_label.count() > 0:
                parent = await you_label.first.evaluate("el => el.parentElement")
                if parent:
                    parent_class = await page.evaluate("el => el.className", parent)
                    if "active" in parent_class or "turn" in parent_class.lower():
                        turn_checks.append(True)
            
            # 需要至少2个条件满足才认为是用户的回合
            if len(turn_checks) >= 2:
                state["is_my_turn"] = True
            elif len(turn_checks) == 1 and await page.locator(".BettingControls__actions button").count() > 0:
                # [FIX] 如果只有一个turn检查通过，但有可用的操作按钮，也认为是用户回合
                action_buttons = page.locator(".BettingControls__actions button")
                for i in range(await action_buttons.count()):
                    btn = action_buttons.nth(i)
                    disabled = await btn.get_attribute("disabled")
                    if disabled is None:  # 有可点击的按钮
                        state["is_my_turn"] = True
                        break
            
            # 4. 提取 to_call (跟注金额) 和 min_raise (最小加注)
            # [FIX] ReplayPoker 使用 .BettingControls__actions 而不是 .ActionButtons
            action_buttons = page.locator(".BettingControls__actions button")
            for i in range(await action_buttons.count()):
                btn = action_buttons.nth(i)
                if not await btn.is_visible():
                    continue
                
                btn_text = await btn.text_content()
                if not btn_text:
                    continue
                
                # 提取 Call 按钮的金额（精确匹配关键词后的数字）
                if re.search(r'\bCall\b', btn_text, re.IGNORECASE):
                    m = re.search(r'\bCall\s+([\d,]+)', btn_text, re.IGNORECASE)
                    if m:
                        state["to_call"] = int(m.group(1).replace(",", ""))
                    else:
                        # Call 按钮没有金额 = check 场景，to_call 为 0
                        state["to_call"] = 0

                # 提取 Raise/Bet 按钮的最小金额
                if re.search(r'\b(Raise|Bet)\b', btn_text, re.IGNORECASE):
                    m = re.search(r'\b(?:Raise|Bet)\s+(?:to\s+)?([\d,]+)', btn_text, re.IGNORECASE)
                    if m:
                        state["min_raise"] = int(m.group(1).replace(",", ""))
            dom_logger.debug(
                f"[DOM] to_call={state['to_call']}, min_raise={state['min_raise']}"
            )
        except Exception:
            bot_logger.exception("[DOM] get_game_state error")
        return state
    
    async def get_available_actions(self, page: Page) -> Dict[str, Any]:
        """Get available betting actions and preset buttons."""
        actions = {
            "available": [],
            "to_call": 0,
            "min_raise": 0,
            "presets": {}  # 预设按钮：min, half, pot, max
        }
        try:
            targets = {
                "fold": r"\bFold\b",
                "check": r"\bCheck\b",
                "call": r"\bCall\b",
                "raise": r"\bRaise\b",
                "bet": r"\bBet\b",
                "all_in": r"\bAll\s*In\b",
            }
            
            for action_name, button_regex in targets.items():
                btn = page.get_by_role("button", name=re.compile(button_regex, re.IGNORECASE))
                try:
                    if await btn.count(timeout=2000) > 0:
                        first_btn = btn.first

                        # [FIX] 多重可见性检查
                        # 1. 检查是否 visible
                        if not await first_btn.is_visible(timeout=2000):
                            continue
                except Exception:
                    # 按钮查找超时，跳过
                    continue
                    
                    # 2. 检查是否在 viewport 内（排除屏幕外的元素）
                    is_in_viewport = await first_btn.evaluate("""
                        (el) => {
                            const rect = el.getBoundingClientRect();
                            return (
                                rect.top >= 0 &&
                                rect.left >= 0 &&
                                rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                                rect.right <= (window.innerWidth || document.documentElement.clientWidth)
                            );
                        }
                    """)
                    if not is_in_viewport:
                        continue
                    
                    # 3. 检查父元素是否隐藏（例如 .AwaitTurn 容器）
                    parent_class = await first_btn.evaluate("""
                        (el) => {
                            let parent = el.parentElement;
                            while (parent) {
                                const style = window.getComputedStyle(parent);
                                if (style.display === 'none' || style.visibility === 'hidden') {
                                    return parent.className;
                                }
                                parent = parent.parentElement;
                            }
                            return '';
                        }
                    """)
                    if parent_class:
                        bot_logger.debug(f"Button '{action_name}' hidden by parent: {parent_class}")
                        continue
                    
                    # 4. 检查按钮是否被禁用（灰色状态）
                    disabled = await first_btn.get_attribute("disabled")
                    if disabled is not None:  # 有 disabled 属性
                        continue
                    
                    # 5. 检查样式中的 opacity，如果太低说明是禁用状态
                    style = await first_btn.get_attribute("style") or ""
                    opacity_match = re.search(r'opacity:\s*([\d.]+)', style)
                    if opacity_match:
                        opacity = float(opacity_match.group(1))
                        if opacity < 0.5:  # 透明度过低，视为禁用
                            continue
                    
                    actions["available"].append(action_name)
            
            if "call" in actions["available"]:
                try:
                    call_btn = page.get_by_role("button", name=re.compile(r"\bCall\b", re.IGNORECASE)).first
                    label = await call_btn.text_content(timeout=2000)
                    if label:
                        m = re.search(r'\bCall\s+([\d,]+)', label, re.IGNORECASE)
                        if m:
                            actions["to_call"] = int(m.group(1).replace(",", ""))
                        else:
                            actions["to_call"] = 0
                except Exception:
                    pass

            raise_btn = None
            try:
                if "raise" in actions["available"]:
                    raise_btn = page.get_by_role("button", name=re.compile(r"\bRaise\b", re.IGNORECASE)).first
                elif "bet" in actions["available"]:
                    raise_btn = page.get_by_role("button", name=re.compile(r"\bBet\b", re.IGNORECASE)).first

                if raise_btn:
                    label = await raise_btn.text_content(timeout=2000)
                    if label:
                        m = re.search(r'\b(?:Raise|Bet)\s+(?:to\s+)?([\d,]+)', label, re.IGNORECASE)
                        if m:
                            actions["min_raise"] = int(m.group(1).replace(",", ""))
            except Exception:
                pass

            # 检测预设按钮
            preset_selectors = {
                "min": ".Preset--min",
                "half": ".Preset--half",
                "pot": ".Preset--pot",
                "max": ".Preset--max"
            }

            for preset_name, selector in preset_selectors.items():
                try:
                    btn = page.locator(selector)
                    if await btn.count(timeout=2000) > 0 and await btn.first.is_visible(timeout=2000):
                        actions["presets"][preset_name] = True
                except Exception:
                    pass

            dom_logger.debug(
                f"[DOM] available_actions={actions['available']}, "
                f"to_call={actions['to_call']}, min_raise={actions['min_raise']}, "
                f"presets={list(actions['presets'].keys())}"
            )
        except Exception:
            bot_logger.exception("Failed to get available actions")
        return actions
    
    async def execute_action(self, page: Page, action: str, amount: Optional[int] = None, preset: Optional[str] = None) -> bool:
        """Execute action on ReplayPoker page."""
        try:
            action_lower = action.lower()

            if action_lower == "fold":
                btn = page.get_by_role("button", name=re.compile("Fold", re.IGNORECASE)).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await human_delay("fold")
                    await btn.click()
                    return True

            elif action_lower in ["check", "call"]:
                btn = page.get_by_role("button", name=re.compile("Check", re.IGNORECASE)).first
                if not (await btn.count() > 0 and await btn.is_visible(timeout=3000)):
                    btn = page.get_by_role("button", name=re.compile("Call", re.IGNORECASE)).first

                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await human_delay("check" if action_lower == "check" else "call")
                    await btn.click()
                    return True

            elif action_lower in ["raise", "bet"]:
                # 如果有预设，先点击预设按钮
                if preset:
                    preset_selectors = {
                        "min": ".Preset--min",
                        "half": ".Preset--half",
                        "pot": ".Preset--pot",
                        "max": ".Preset--max"
                    }
                    selector = preset_selectors.get(preset)
                    if selector:
                        preset_btn = page.locator(selector).first
                        if await preset_btn.count(timeout=3000) > 0 and await preset_btn.is_visible(timeout=3000):
                            await preset_btn.click()
                            await asyncio.sleep(0.3)
                            bot_logger.info(f"Clicked preset button: {preset}")
                elif amount:
                    # 否则设置具体金额
                    input_selectors = [
                        ".BettingControls input",
                        "input.NumberInput__input",
                        "input[type='text']"
                    ]
                    for selector in input_selectors:
                        inp = page.locator(selector).first
                        if await inp.count(timeout=3000) > 0 and await inp.is_visible(timeout=3000):
                            await inp.click(click_count=3)
                            await inp.fill(str(amount))
                            await asyncio.sleep(0.3)
                            break

                # 点击 Raise/Bet 按钮
                btn = page.get_by_role("button", name=re.compile("Raise", re.IGNORECASE)).first
                if not (await btn.count() > 0 and await btn.is_visible(timeout=3000)):
                    btn = page.get_by_role("button", name=re.compile("Bet", re.IGNORECASE)).first

                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await human_delay("raise")
                    await btn.click()
                    return True

            elif action_lower in ["all_in", "allin"]:
                btn = page.get_by_role("button", name=re.compile("All In", re.IGNORECASE)).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await human_delay("all_in")
                    await btn.click()
                    return True

            return False
        except Exception as e:
            bot_logger.error(f"Failed to execute action {action}: {e}")
            return False
    
    async def sit_in(self, page: Page) -> bool:
        """Sit in from sitting out state."""
        try:
            # 方法1: 查找 Sit in 按钮（通过类名）
            sit_in_btn = page.locator(".SeatControls__action--sitIn")
            if await sit_in_btn.count() > 0 and await sit_in_btn.is_visible():
                await sit_in_btn.click()
                await asyncio.sleep(0.5)
                bot_logger.info("Clicked 'Sit in' button")
                return True
            
            # 方法2: 备用：通过文字查找
            sit_in_text = page.get_by_text("Sit in", exact=False)
            if await sit_in_text.count() > 0 and await sit_in_text.is_visible():
                await sit_in_text.click()
                await asyncio.sleep(0.5)
                bot_logger.info("Clicked 'Sit in' button (by text)")
                return True
            
            # [FIX] 方法3: 检查是否是 "Sit Out" 状态，需要取消勾选
            sit_out_checkbox = page.locator(".Footer__settings--sittingOut .CheckBox.CheckBox--checked")
            if await sit_out_checkbox.count() > 0:
                bot_logger.info("Detected 'Sit Out' state, unchecking checkbox...")
                await sit_out_checkbox.click()
                await asyncio.sleep(0.5)
                bot_logger.info("Uncheked 'Sit Out Next Hand' - you are now sitting in!")
                return True
            
            bot_logger.warning("Sit in button not found")
            return False
        except Exception as e:
            bot_logger.error(f"Failed to sit in: {e}")
            return False
    
    async def sit_out(self, page: Page) -> bool:
        """Sit out by checking 'Sit Out Next Hand' checkbox."""
        try:
            sit_out_cb = page.locator(".Footer__settings--sittingOut .CheckBox").first
            if await sit_out_cb.count() > 0:
                cls = await sit_out_cb.get_attribute("class") or ""
                if "CheckBox--checked" not in cls:
                    await sit_out_cb.click()
                    await asyncio.sleep(0.5)
                    bot_logger.info("已勾选 'Sit Out Next Hand'")
                    return True
                # 已经处于 sit out 状态
                return True
            return False
        except Exception as e:
            bot_logger.error(f"Sit out 操作失败: {e}")
            return False

    async def add_chips(self, page: Page, amount: Optional[int] = None) -> bool:
        """Add chips while seated at the table.

        ReplayPoker 的 'Add Chips' 按钮在牌桌头部（.Header__button--addChips），
        点击后弹出与初始买入相同的 BuyInModal。
        """
        try:
            # 1. 点击 Add Chips 按钮
            add_btn_selectors = [
                ".Header__button--addChips",
                "button.Button--primary.Header__button--addChips",
            ]
            clicked = False
            for selector in add_btn_selectors:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await btn.click()
                    await asyncio.sleep(1)
                    bot_logger.info("点击 'Add Chips' 按钮")
                    clicked = True
                    break

            # 备用: 通过文字查找
            if not clicked:
                add_btn_text = page.get_by_role("button", name=re.compile("Add Chips", re.IGNORECASE)).first
                if await add_btn_text.count() > 0 and await add_btn_text.is_visible(timeout=3000):
                    await add_btn_text.click()
                    await asyncio.sleep(1)
                    bot_logger.info("点击 'Add Chips' 按钮 (by text)")
                    clicked = True

            if not clicked:
                bot_logger.warning("未找到 'Add Chips' 按钮")
                return False

            # 2. 在弹出的 BuyInModal 中设置金额并确认
            if amount:
                await self.set_buyin_amount(page, amount)

            confirmed = await self.confirm_buyin(page)
            if confirmed:
                bot_logger.info(f"补筹成功{f' {amount}' if amount else ''}")
                return True
            else:
                bot_logger.warning("补筹确认失败")
                # 尝试取消弹窗避免卡住
                await self.cancel_buyin(page)
                return False

        except Exception as e:
            bot_logger.error(f"补筹异常: {e}")
            return False

    async def leave_table(self, page: Page) -> bool:
        """Leave ReplayPoker table."""
        try:
            await page.goto(self.get_lobby_url(), timeout=20000)
            return True
        except Exception as e:
            bot_logger.error(f"Failed to leave table: {e}")
            return False
