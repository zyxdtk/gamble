import asyncio
import json
import os
from playwright.async_api import async_playwright
import re
from ..core.game_state import GameState
from ..engine.decision_engine import DecisionEngine
from ..ui.hud import HUD
from ..core.utils import human_delay, get_randomized_amount

class ReplayPokerClient:
        
    def __init__(self, headless=False, auto_mode=False):
        self.headless = headless
        self.auto_mode_enabled = auto_mode
        self.page = None
        self.state = GameState()
        self.playwright = None
        self.engine = DecisionEngine()
        self.hud = HUD()
        self.is_sitting = False
        self.current_balance = 0
        self.session_profit = 0
        self.lobby_url = "https://www.replaypoker.com/lobby"
        self.target_stakes = "1/2" # Default target

    async def find_action_buttons(self):
        """Finds available action buttons on the page."""
        if not self.page:
            return {}
            
        try:
            if self.page.is_closed():
                return {}
        except:
             return {}
            
        buttons = {}
        # Common text for buttons. Case insensitive usually handled by locators or we normalize.
        # We use strict=False to match "Call 100" as "Call"
        targets = ["Fold", "Call", "Check", "Raise", "Bet", "All In"]
        
        try:
            for text in targets:
                 # Look for buttons with this text
                 locator = self.page.get_by_text(text, exact=False)
                 if await locator.count() > 0:
                     # Check if visible
                     if await locator.first.is_visible():
                         buttons[text.lower()] = locator.first
        except Exception as e:
            # Page might have closed during loop
            # print(f"Error finding buttons: {e}", flush=True)
            return {}
        
        return buttons

    async def click_button(self, action_name):
        """Clicks a button by name with safety checks."""
        buttons = await self.find_action_buttons()
        # Map generic actions to specific buttons
        # Raise might be "Bet", "Raise to..."
        # Call might be "Call 100", "Check" (if free)
        
        target = None
        if action_name.lower() == "fold":
            target = buttons.get("fold")
        elif action_name.lower() in ["check", "call"]:
            target = buttons.get("check") or buttons.get("call")
        elif action_name.lower() in ["bet", "raise", "all-in"]:
            target = buttons.get("bet") or buttons.get("raise") or buttons.get("all in")
            
        if target:
            print(f"[AUTO] Clicking {action_name}...", flush=True)
            try:
                await target.click()
                return True
            except Exception as e:
                 print(f"[AUTO] Failed to click {action_name}: {e}", flush=True)
        else:
             print(f"[AUTO] Button for {action_name} not found. Available: {list(buttons.keys())}", flush=True)
        return False

    async def execute_decision(self, decision_text):
        """Parses decision text and attempts to execute it."""
        # Example decision: "Pre-flop: STRONG (AQs) - RAISE/CALL"
        # Extract actions: RAISE, CALL
        if " - " not in decision_text:
            return

        recommendation = decision_text.split(" - ")[-1]
        actions = recommendation.split("/") # ["RAISE", "CALL"]
        
        import random
        # Human-like delay
        await human_delay()

        for action in actions:
            action = action.strip()
            if await self.click_button(action):
                print(f"[AUTO] Successfully executed {action}", flush=True)
                return
        
        print("[AUTO] Could not execute any suggested actions.", flush=True)
        
    async def run_automation_tick(self):
        """Unified tick for automated actions (lobby, sitting, playing)."""
        if not self.page: return
        
        # 1. Periodically update state from DOM
        await self.update_state_from_dom()
        
        # 2. Only run automation if enabled
        if not self.auto_mode_enabled: return
        
        url = self.page.url
        if "/lobby" in url:
            await self.navigate_to_lobby()
        elif "/table/" in url:
            if not self.is_sitting:
                await self.sit_and_buyin()
            else:
                # 1. Check for "I'm back" overlay or button
                im_back = self.page.get_by_text("I'm back", exact=False).first
                if await im_back.count() > 0 and await im_back.is_visible():
                    print("[TABLE] 'I'm back' button detected. Clicking...", flush=True)
                    await im_back.click()
                    await asyncio.sleep(1)

                # 3. Check for low chips -> Rebuy
                if self.is_sitting and self.state.total_chips < 100: # Threshold
                    await self.handle_rebuy()

                # 4. Check for our turn
                buttons = await self.find_action_buttons()
                if buttons:
                     print("[AUTO] It's our turn! (Buttons visible)", flush=True)
                     decision_data = self.engine.decide(self.state)
                     suggestion = decision_data.get("my_action", "") if isinstance(decision_data, dict) else decision_data
                     print(f"[AUTO] Suggestion: {suggestion}", flush=True)
                     
                     await self.update_hud(decision_data)
                     await self.execute_decision(suggestion)
                     
                     # Wait a bit to avoid double clicking before UI updates
                     await asyncio.sleep(5)
        elif self.page.url == "https://www.replaypoker.com/" or self.page.url == "https://www.replaypoker.com/home":
             # At home page, go to lobby
             await self.navigate_to_lobby()

    async def navigate_to_lobby(self):
        """Navigates to the ring games lobby."""
        if not self.page: return
        
        print("[LOBBY] Navigating to lobby...", flush=True)
        try:
            # ReplayPoker lobby link or direct URL
            await self.page.goto(self.lobby_url)
            await self.page.wait_for_load_state("networkidle")
            
            # Click "Ring Games" if not already there
            ring_games_tab = self.page.get_by_role("link", name="Ring Games")
            if await ring_games_tab.count() > 0:
                await ring_games_tab.click()
                await asyncio.sleep(2)
                
            await self.apply_lobby_filters()
            await self.join_best_table()
        except Exception as e:
            print(f"[LOBBY] Navigation failed: {e}", flush=True)

    async def apply_lobby_filters(self):
        """Applies filters for Hold'em, 9-max, etc."""
        print("[LOBBY] Applying filters...", flush=True)
        try:
            # Hold'em filter
            holdem_filter = self.page.get_by_text("Texas Hold'em", exact=False).first
            if await holdem_filter.count() > 0:
                await holdem_filter.click()
                
            # Stake levels can be tricky, usually they are tabs or checkboxes
            # For now, let's assume we want "Low" or "Medium" stakes
            low_stake = self.page.get_by_text("Low", exact=True)
            if await low_stake.count() > 0:
                await low_stake.click()
            
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[LOBBY] Filter application error: {e}", flush=True)

    async def join_best_table(self):
        """Finds a table with empty seats and joins."""
        print("[LOBBY] Searching for a table...", flush=True)
        try:
            # Look for "Play" buttons in the table list
            # ReplayPoker uses 'Play' or 'Join' or just clicking the row
            play_buttons = self.page.get_by_role("button", name="Play")
            if await play_buttons.count() > 0:
                # Click the first one that has a reasonable number of players (not full, not empty)
                # For simplicity, just pick the first available
                print("[LOBBY] Found a table! Joining...", flush=True)
                await play_buttons.first.click()
                return True
            
            # Alternative: clicking row? 
            # (Requires more specific selectors based on actual site structure)
        except Exception as e:
            print(f"[LOBBY] Failed to join table: {e}", flush=True)
        return False

    async def sit_and_buyin(self):
        """Clicks an empty seat and handles the buy-in popup."""
        if not self.page or "/table/" not in self.page.url:
            return
            
        try:
            # 1. Find an empty seat
            # ReplayPoker empty seats often have 'Sit here' or '+' icon
            sit_here = self.page.get_by_text("Sit here", exact=False).first
            if await sit_here.count() > 0 and await sit_here.is_visible():
                print("[TABLE] Found empty seat. Sitting...", flush=True)
                await sit_here.click()
                await asyncio.sleep(2)
                
                # 2. Handle Buy-in dialog
                # Usually has 'Bring Chips', 'Buy In', 'Confirm'
                buyin_button = self.page.get_by_role("button", name=re.compile("Buy In|Bring Chips|Confirm", re.I)).first
                if await buyin_button.count() > 0:
                    print("[TABLE] Confirming Buy-in...", flush=True)
                    await buyin_button.click()
                    self.is_sitting = True
                    return True
        except Exception as e:
            print(f"[TABLE] Sit/Buy-in failed: {e}", flush=True)
        return False
    async def inject_hud(self):
        """Injects the HUD HTML/CSS into the page."""
        if self.page:
            await self.hud.inject(self.page)
            # Set up mode toggle listener
            await self.setup_mode_toggle_listener()


    async def update_hud(self, suggestion):
        """Updates the HUD content with new suggestion."""
        if self.page:
            await self.hud.update_content(self.page, suggestion)

    async def setup_mode_toggle_listener(self):
        """Sets up listener for mode toggle events from the HUD."""
        if not self.page:
            return
            
        try:
            # Inject event listener that calls Python callback
            await self.page.evaluate("""() => {
                window.addEventListener('ai-mode-change', (event) => {
                    // Store mode in window for Python to read
                    window.aiAutoMode = event.detail.autoMode;
                });
            }""")
            
            # Start polling for mode changes
            asyncio.create_task(self.poll_mode_changes())
        except Exception as e:
            print(f"[HUD] Failed to setup mode listener: {e}", flush=True)

    async def poll_mode_changes(self):
        """Polls for mode changes from the frontend."""
        last_mode = self.auto_mode_enabled
        while True:
            try:
                if self.page and not self.page.is_closed():
                    # Read mode from window
                    auto_mode = await self.page.evaluate("() => window.aiAutoMode || false")
                    if auto_mode != last_mode:
                        self.auto_mode_enabled = auto_mode
                        mode_name = "自动" if auto_mode else "辅助"
                        print(f"[MODE] 切换到 {mode_name} 模式", flush=True)
                        last_mode = auto_mode
            except Exception:
                pass
            await asyncio.sleep(0.5)  # Poll every 500ms


    async def process_replay_poker_message(self, data):
        """Handles the 'output' payload from ReplayPoker."""
        if not isinstance(data, dict):
            return
            
        updates = data.get("updates", [])
        for update in updates:
            self.handle_game_update(update)
            
        # After processing updates, ask for advice
        decision_data = self.engine.decide(self.state)
        
        # Always update HUD with structured data
        await self.update_hud(decision_data)
        
        # Print to console for logging
        if self.state.hole_cards:
            # Extract my action for console logging
            my_action = decision_data.get("my_action", "") if isinstance(decision_data, dict) else decision_data
            print(f"[ADVISOR] {my_action}", flush=True)

    # (Existing methods...)
    async def start_browser(self):
        """Starts the browser and connects to the existing session if possible, or starts a new one."""
        print("Initializing Playwright...", flush=True)
        self.playwright = await async_playwright().start()
        
        # Ensure data directory exists
        os.makedirs("./data", exist_ok=True)
        user_data_dir = "./data/browser_data"
        print(f"Launching browser with user_data_dir={user_data_dir}...", flush=True)
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=self.headless,
                channel="chrome", 
                args=["--disable-blink-features=AutomationControlled"]
            )
        except Exception as e:
            print(f"\n[ERROR] Failed to launch persistent browser: {e}", flush=True)
            print("[HINT] This usually means an old browser window is still open.", flush=True)
            print("[ACTION] Please CLOSE all Chrome/Playwright windows and try again.", flush=True)
            raise e

        # Try to find an existing table page
        found_table = False
        if self.context.pages:
            for page in self.context.pages:
                if "/table/" in page.url:
                    print(f"Found existing table page: {page.url}", flush=True)
                    self.page = page
                    found_table = True
                    break
            
            if found_table:
                await self.inject_hud()
        
        if not found_table:
            # Default to first page if no table found yet, but don't attach listeners yet if not table
            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = await self.context.new_page()

            print("Navigating to https://www.replaypoker.com/...", flush=True)
            await self.page.goto("https://www.replaypoker.com/")
            
            # Check if login is needed
            if "login" in self.page.url:
                 print("[LOBBY] Login required. Please login manually in the browser.", flush=True)
            else:
                 # Attempt to go to lobby
                 await self.navigate_to_lobby()

        print("Browser launched. Attaching listeners...", flush=True)
        # Attach to all pages initially, but handlers will filter by URL
        for page in self.context.pages:
             await self.attach_network_listeners_to_page(page)

        # Listen for new pages (tabs/popups)
        self.context.on("page", self.on_page_created)

    async def on_page_created(self, page):
        """Handler for new pages/tabs."""
        print(f"[BROWSER] New page created: {page.url}", flush=True)
        # Wait a bit for URL to update
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except:
             pass
             
        if "/table/" in page.url:
             print(f"[BROWSER] valid table detected: {page.url}", flush=True)
             self.page = page
             await self.attach_network_listeners_to_page(page)
             # Inject HUD
             await self.inject_hud()
        else:
             # Still attach listeners in case it navigates to a table later? 
             # For now, let's attach but rely on URL filtering in handlers.
             await self.attach_network_listeners_to_page(page)


    async def on_frame_navigated(self, frame, page):
        """Handler for frame navigation events."""
        # Only handle main frame navigation
        if frame != page.main_frame:
            return
            
        url = frame.url
        print(f"[BROWSER] Page navigated to: {url}", flush=True)
        
        # Check if navigated to a table page
        if "/table/" in url:
            print(f"[BROWSER] Table page detected after navigation: {url}", flush=True)
            self.page = page
            # Inject HUD
            await self.inject_hud()
    async def dump_html(self, state_name="debug_state"):
        """Dumps current page HTML for debugging."""
        if not self.page or "/table/" not in self.page.url:
             return

        try:
            content = await self.page.content()
            filename = f"data/{state_name}.html"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[DEBUG] Saved HTML to {filename}")
        except Exception as e:
            print(f"[ERROR] Could not dump HTML: {e}")

    async def attach_network_listeners(self):
         """Deprecated, logic moved to start_browser."""
         pass

    async def attach_network_listeners_to_page(self, page):
        """Listens to WebSocket frames and Console logs on a specific page."""
        print(f"Attaching listeners to {page.url}...", flush=True)
        # We need to bind the page to the handler to check its URL later
        # Or just check page.url inside the handler if we know which page triggered it.
        # Playwright handlers don't pass the page object by default for console/ws?
        # console msg has .page property. ws does not? ws.page exists in recent playwright.
        
        page.on("websocket", self.on_websocket)
        page.on("console", self.on_console)
        # Listen for navigation events to inject HUD when navigating to table
        page.on("framenavigated", lambda frame: self.on_frame_navigated(frame, page))

    def on_console(self, msg):
        """Fallback: Listen to console logs which often mirror WS data."""
        if "/table/" not in msg.page.url:
            return

        # Simple filter to avoid spam
        text = msg.text
        if "cards" in text or "hand" in text:
             # print(f"[CONSOLE] {text[:200]}", flush=True)
             if "cards" in text:
                 self.extract_cards_from_text(text)

    def on_websocket(self, ws):
        # In Playwright, ws.page might be available or we check ws.url content?
        # Actually ws.url is the socket URL, not the page URL.
        # We can try to access the page via the event if possible, but standard API is just 'ws'.
        # However, we only care if the *initiating page* is a table. 
        # Since we attached listeners specifically to pages, maybe we capturing them is enough?
        # But if we attached to ALL pages, we need to know which one.
        # Let's check if the page associated with this WS is a table.
        # ws.page is available in python playwright? Yes.
        
        try:
             if "/table/" not in ws.page.url:
                  return
        except:
             pass

        print(f"WebSocket opened: {ws.url}", flush=True)
        ws.on("framesent", self.handle_ws_frame)
        ws.on("framereceived", self.handle_ws_frame)

    async def handle_ws_frame(self, frame):
        try:
            if isinstance(frame, str):
                payload = frame
            elif hasattr(frame, 'text'):
                payload = frame.text
                if payload is None:
                     # Binary frame?
                     if hasattr(frame, 'body') and frame.body:
                          print(f"[WS BINARY] {len(frame.body)} bytes", flush=True)
                     return
            else:
                 print(f"[WS UNKNOWN] Frame type: {type(frame)}", flush=True)
                 return
            
            # DEBUG: Print EVERYTHING (truncated) to see the protocol
            # print(f"[WS RAW] {payload[:200]}", flush=True)

            # Try parsing the entire payload as JSON first
            try:
                # ReplayPoker seems to use a custom array format: ["7", null, "table:...", "output", {data}]
                if payload.startswith("["):
                    data = json.loads(payload)
                    if isinstance(data, list) and len(data) >= 4:
                        msg_type = data[0]
                        channel = data[2]
                        event = data[3]
                        if event == "output" and len(data) > 4:
                            await self.process_replay_poker_message(data[4])
                        elif event == "heartbeat":
                            pass # maximize signal/noise ratio
                        else:
                             # print(f"[WS VIS] {event}", flush=True)
                             pass
                
                # Socket.IO style "42"
                elif payload.startswith("42"): 
                    payload = payload[2:]
                    data = json.loads(payload)
                    if isinstance(data, list) and len(data) > 1:
                        self.process_json_data(data[1])
                else:
                     # Attempt generic JSON
                     data = json.loads(payload)
                     self.process_json_data(data)

            except json.JSONDecodeError:
                # Fallback
                if "cards" in payload:
                    self.extract_cards_from_text(payload)

        except Exception as e:
            print(f"Error handling frame: {e}", flush=True)



    def handle_game_update(self, update):
        """Processes a single game update action."""
        action = update.get("action")
        
        # DEBUG: Print interesting actions
        if action not in ["tick", "heartbeat"]:
             print(f"[GAME ACTION] {action}: {update}", flush=True)

        # 1. Update general player state from 'players' list if available
        if "players" in update:
            for p_data in update["players"]:
                seat_id = p_data.get("seatId")
                if seat_id is not None:
                    player = self.state.players.get(seat_id)
                    if not player:
                        from ..core.game_state import Player
                        player = Player(seat_id=seat_id)
                        self.state.players[seat_id] = player
                    
                    # Update fields
                    if "userId" in p_data:
                        player.name = f"User{p_data['userId']}" # We don't have screen name easily yet
                    if "stack" in p_data:
                        player.chips = p_data["stack"]
                    if "state" in p_data:
                        # Map game state to our status
                        # state: bet, call, fold, ask (acting?), playing, sitOut
                        game_state = p_data["state"]
                        if game_state == "fold":
                            player.is_active = False
                            player.status = "folded"
                        elif game_state == "sitOut":
                            player.is_active = False
                            player.status = "sit_out"
                        else:
                            player.is_active = True
                            player.status = "active"

        # 2. Handle specific actions
        if action in ["bet", "call", "raise", "check", "fold"]:
            seat_id = update.get("seatId")
            if seat_id is not None:
                player = self.state.players.get(seat_id)
                if player:
                    player.last_action = action
                    player.street_actions.append(action)
                    # We will let DecisionEngine calculate range based on this history
        
        elif action == "deal":
            if "cards" in update:
                self.update_cards_from_json(update["cards"])
            # Reset street actions on new street? Usually 'state' changes (preFlop -> flop)
            # We assume 'dealCommunityCards' implies new street usually, or 'state' field in update?
            # Actually 'tick' has 'state': 'preFlop' etc.
            
        elif action == "dealCommunityCards":
             if "cards" in update:
                 self.update_cards_from_json(update["cards"])
             # New street, maintain street_actions? 
             # For now, simplistic approach: clear street actions if we see new community cards? 
             # Or maybe just keep all actions for now.
             for p in self.state.players.values():
                 p.street_actions = [] # Reset for new street

        elif action == "updatePots":
            # {"action": "updatePots", "pots": [{"chips": 2023, ...}], ...}
            pots = update.get("pots", [])
            if pots:
                # Sum all pots (main + side pots)
                total_pot = sum(p.get("chips", 0) for p in pots)
                if total_pot > 0:
                    self.state.pot = total_pot
                    # print(f"[GAME] Pot Updated: {self.state.pot}", flush=True)

        elif action == "tick":
            # {"action": "tick", "currentPlayer": {"seatId": 1, ...}, ...}
            current_player = update.get("currentPlayer")
            if current_player:
                seat_id = current_player.get("seatId")
                self.state.active_seat = seat_id
                # Set is_acting
                for pid, p in self.state.players.items():
                    p.is_acting = (pid == seat_id)

        elif action == "awardPot":
             print("[GAME] Hand Ended. Pot Awarded.", flush=True)
             self.state.reset_round()


    def process_json_data(self, data):
        """Processes generic structured JSON data (legacy/socketio)."""

    def update_cards_from_json(self, cards):
        """Updates internal card state based on JSON list."""
        if len(cards) == 2:
            current_holes = sorted(self.state.hole_cards)
            new_cards = sorted(cards)
            if current_holes != new_cards:
                print(f"[GAME] New Hole Cards: {cards}")
                self.state.hole_cards = cards
        elif len(cards) >= 3:
            # Community cards
            current_board = sorted(self.state.community_cards)
            new_board = sorted(cards)
            if current_board != new_board:
                 print(f"[GAME] New Board: {cards}")
                 self.state.community_cards = cards

    def extract_cards_from_text(self, text):
        """Fallback regex extraction."""
        matches = re.findall(r'\[\s*"([2-9TJQKA][dhsc])"\s*,\s*"([2-9TJQKA][dhsc])"(?:\s*,\s*"([2-9TJQKA][dhsc])")*\s*\]', text)
        for match in matches:
            cards = [c for c in match if c]
            self.update_cards_from_json(cards)

    async def update_state_from_dom(self):
        """Parses visible elements to update Pot, Turn, etc."""
        if not self.page or "/table/" not in self.page.url:
            return

        try:
             # Check if HUD is injected
            is_injected = await self.page.evaluate("() => !!document.getElementById('ai-hud')")
            if not is_injected:
                await self.inject_hud()

            # 1. Update Pot
            # ReplayPoker common selector for total pot
            pot_locator = self.page.locator(".table-pot, .pot-value, .pot-amount").first
            if await pot_locator.count() > 0:
                pot_text = await pot_locator.text_content(timeout=200)
                if pot_text:
                    # Clean up text (e.g., "1,200")
                    cleaned = re.sub(r"[^\d]", "", pot_text)
                    if cleaned:
                        self.state.pot = int(cleaned)

            # 2. Check for balance in Header
            # ReplayPoker user chip count often in .user-chips or similar
            balance_locator = self.page.locator(".user-chips, .balance-value").first
            if await balance_locator.count() > 0:
                balance_text = await balance_locator.text_content(timeout=200)
                if balance_text:
                     cleaned = re.sub(r"[^\d]", "", balance_text)
                     if cleaned:
                         self.current_balance = int(cleaned)
                         self.state.total_chips = self.current_balance

            # 3. Check for specific action buttons (My Turn)
            # ReplayPoker buttons are usually in .game-controls or similar
            buttons = await self.find_action_buttons()
            if buttons:
                 # If we see buttons AND a specific timeout bar, it's definitely our turn?
                 # For now, finding some specific buttons is enough
                 pass
                    
        except Exception:
            # Ignore timeouts or selector errors during polling
            pass

    async def get_game_state(self) -> GameState:
        """
        Returns the current game state object.
        Triggers DOM updates before returning.
        """
        await self.update_state_from_dom()
        return self.state

    async def handle_rebuy(self):
        """Finds and clicks rebuy buttons if visible."""
        print("[TABLE] Attempting Rebuy...", flush=True)
        try:
            rebuy_btn = self.page.get_by_role("button", name=re.compile("Rebuy|Add Chips", re.I)).first
            if await rebuy_btn.count() > 0:
                await rebuy_btn.click()
                await asyncio.sleep(2)
                confirm = self.page.get_by_role("button", name=re.compile("Confirm|Bring", re.I)).first
                if await confirm.count() > 0:
                    await confirm.click()
        except Exception as e:
            print(f"[TABLE] Rebuy failed: {e}", flush=True)

    async def handle_reconnect(self):
        """Refreshes the page if connection lost."""
        print("[SYSTEM] Attempting Reconnect...", flush=True)
        try:
             await self.page.reload()
             await self.page.wait_for_load_state("networkidle")
             await asyncio.sleep(5)
             await self.navigate_to_lobby()
        except Exception as e:
             print(f"[SYSTEM] Reconnect failed: {e}", flush=True)

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()

# For quick testing
async def main():
    # Set auto_mode=False (Assist Mode) by default
    client = ReplayPokerClient(headless=False, auto_mode=False)
    try:
        await client.start_browser()
        print("Browser started. Please navigate to a table.")
        if client.auto_mode_enabled:
             print("Auto Mode: ENABLED. Will click buttons when it's your turn.")
        else:
             print("Assist Mode: ENABLED. Suggestions will be printed to HUD/Console.")
        
        while True:
            await asyncio.sleep(2)
            
            if client.page and client.page.is_closed():
                print("[STOP] Browser page closed. Exiting auto-player.", flush=True)
                break

            # Let the client handle everything in one pulse
            await client.run_automation_tick()
            
            # await client.dump_html() # Debug if needed
    except KeyboardInterrupt:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
