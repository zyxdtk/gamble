"""
Browser 交互式 CLI — 从 main.py 中提取的浏览器手动控制模块。
"""
import asyncio
import functools
import os
from typing import Optional

from src.platforms.browser.adapters import ReplayPokerAdapter, TableInfo, TableFilter
from src.platforms.browser.browser_platform import (
    BrowserPlatform,
    BrowserPlatformConfig,
    TableSelectionStrategy
)
from src.utils.logger import bot_logger


class BrowserTestCLI:
    """Interactive test CLI for BrowserPlatform."""

    def __init__(
        self,
        config: Optional[BrowserPlatformConfig] = None,
        headless: bool = False
    ):
        self.config = config or BrowserPlatformConfig.from_file()
        self.config.headless = headless

        self.platform = BrowserPlatform(config=self.config)
        self.platform.auto_mode = False

        self.running = False

        # 截图配置 - 放在 data 目录下
        self.screenshot_dir = "./data/snapshots"
        self.auto_screenshot_enabled = False
        self.auto_screenshot_on_actions = True
        self.auto_screenshot_on_state_change = False
        self.screenshot_counter = 0

        # 主动提示配置
        self.last_prompt_actions = None  # 上次提示的动作集合
        self.monitor_task = None         # 状态监控任务

        # 创建截图目录
        import os
        os.makedirs(self.screenshot_dir, exist_ok=True)

    async def start(self):
        """Start the platform and CLI."""
        await self.platform.initialize()
        self.running = True

        print("\n" + "=" * 60)
        print("  Browser Poker Platform Test CLI")
        print("=" * 60)
        print(f"  Website: {self.platform.adapter.get_name()}")
        print(f"  Config: preferred_stakes={self.config.preferred_stakes}")
        print(f"          strategy={self.config.table_selection_strategy.value}")
        print("=" * 60 + "\n")

        self.print_help()

        # 启动状态监控任务
        self.monitor_task = asyncio.create_task(self.monitor_game_state())

    async def stop(self):
        """Stop the platform."""
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        await self.platform.stop()
        self.running = False

    async def monitor_game_state(self):
        """Monitor game state and prompt user when it's their turn to act."""
        last_prompted_actions = None
        debug_counter = 0

        while self.running:
            try:
                await asyncio.sleep(0.5)

                debug_counter += 1
                if debug_counter % 20 == 0:
                    if self.platform.table_pages:
                        pass

                if self.last_prompt_actions == frozenset():
                    continue

                if not self.platform.table_pages:
                    continue

                actions = await self.platform.get_available_actions()
                available_actions = actions.get('available', [])

                if available_actions and len(available_actions) > 0:
                    current_actions = frozenset(available_actions)
                    if current_actions != last_prompted_actions:
                        last_prompted_actions = current_actions
                        self.last_prompt_actions = current_actions
                        print("\n" + "=" * 60)
                        print("  ⚡ Your turn to act!")
                        print("=" * 60)
                        await self.cmd_available_actions()
                        print("test-cli> ", end="", flush=True)

                elif not available_actions and last_prompted_actions is not None:
                    last_prompted_actions = None
                    self.last_prompt_actions = None

            except Exception as e:
                pass

    def print_help(self):
        """Print help message."""
        print("\n" + "-" * 60)
        print("  Available Commands:")
        print("-" * 60)

        print("\n  [Login & Lobby]")
        print("    login              - Ensure logged in (supports manual login)")
        print("    lobby              - Navigate to lobby")
        print("    tables [filter]    - List available tables (filter: stakes)")
        print("    best               - Show best available table")
        print("    open [idx|url]     - Open a table by index, URL, or best")
        print("    join [min|max|amt] - Quick join: find best table and sit down")
        print("    clearhistory       - Clear visited table history")

        print("\n  [Table Management]")
        print("    sit                - Try to sit down at current table")
        print("    buyin <amount>     - Set buy-in amount and confirm")
        print("    buyin default      - Use default buy-in amount")
        print("    buyin cancel       - Cancel buy-in popup")
        print("    leave              - Leave current table")

        print("\n  [Game State]")
        print("    state              - Show current game state")
        print("    actions            - Show available actions")

        print("\n  [Game Actions]")
        print("    fold               - Fold")
        print("    check              - Check")
        print("    call               - Call")
        print("    raise <amount>     - Raise to amount")
        print("    bet <amount>       - Bet amount")
        print("    allin              - Go all-in")

        print("\n  [Configuration]")
        print("    config             - Show current configuration")
        print("    stakes <level>     - Set preferred stakes (e.g. 1/2, 5/10)")
        print("    strategy <type>    - Set table selection strategy")
        print("                         (fifo|most|least|random)")

        print("\n  [Screenshots]")
        print("    screenshot [name]  - Take manual screenshot")
        print("    snap               - Quick snapshot (timestamped)")
        print("    autosnap on/off    - Toggle auto-screenshot mode")
        print("    snaps              - List recent screenshots")
        print("    snapdir            - Show screenshots directory")

        print("\n  [Utility]")
        print("    url                - Show current URL(s)")
        print("    help, ?            - Show this help")
        print("    quit, q, exit      - Exit the program")
        print("-" * 60 + "\n")

    async def run(self):
        """Run the interactive CLI loop."""
        await self.start()

        try:
            while self.running:
                try:
                    loop = asyncio.get_event_loop()
                    cmd_line = await loop.run_in_executor(
                        None, functools.partial(input, "test-cli> ")
                    )
                    cmd_line = cmd_line.strip()

                    if not cmd_line:
                        continue

                    parts = cmd_line.split()
                    cmd = parts[0].lower()

                    if cmd in ("quit", "q", "exit"):
                        break
                    elif cmd in ("help", "?"):
                        self.print_help()
                    elif cmd == "login":
                        await self.cmd_login()
                    elif cmd == "lobby":
                        await self.platform.navigate_to_lobby()
                        print("Navigated to lobby.")
                    elif cmd == "tables":
                        filter_stakes = parts[1] if len(parts) > 1 else None
                        await self.cmd_tables(filter_stakes)
                    elif cmd == "best":
                        await self.cmd_best_table()
                    elif cmd == "open":
                        target = parts[1] if len(parts) > 1 else None
                        await self.cmd_open_table(target)
                    elif cmd == "join":
                        buyin_type = parts[1] if len(parts) > 1 else "min"
                        await self.cmd_join(buyin_type)
                    elif cmd == "clearhistory":
                        self.platform.adapter.clear_visited_history()
                        print("Visited history cleared.")
                    elif cmd == "sit":
                        if len(parts) > 1 and parts[1] == "in":
                            success = await self.platform.sit_in()
                            print("Sit in:" + (" ✓ Success" if success else " ✗ Failed"))
                        else:
                            success = await self.platform.try_sit_down()
                            print("Sit down:" + (" ✓ Success" if success else " ✗ Failed"))
                            print("  Tip: Use 'buyin <amount>' to confirm buy-in if popup appears")
                    elif cmd == "buyin":
                        if len(parts) >= 2:
                            amount = parts[1]
                            if amount.lower() == "default":
                                await self.cmd_buyin_default()
                            elif amount.lower() == "min":
                                await self.cmd_buyin_min()
                            elif amount.lower() == "max":
                                await self.cmd_buyin_max()
                            elif amount.lower() == "cancel":
                                await self.cmd_buyin_cancel()
                            elif amount.isdigit():
                                await self.cmd_buyin_amount(int(amount))
                            else:
                                print(f"Unknown buyin command: {amount}")
                        else:
                            print("Usage: buyin <amount>|default|min|max|cancel")
                    elif cmd == "leave":
                        await self.platform.leave_table()
                        print("Left table.")
                    elif cmd == "state" or cmd == "status":
                        await self.cmd_game_state()
                    elif cmd == "actions":
                        await self.cmd_available_actions()
                    elif cmd in ("fold", "check", "call", "allin"):
                        await self.cmd_execute_action(cmd)
                    elif cmd in ("raise", "bet"):
                        if len(parts) > 1:
                            amount_or_preset = parts[1]
                            if amount_or_preset.lower() in ("min", "half", "pot", "max"):
                                await self.cmd_execute_action(cmd, None, amount_or_preset.lower())
                            elif amount_or_preset.isdigit():
                                await self.cmd_execute_action(cmd, int(amount_or_preset))
                            else:
                                print(f"Unknown preset or amount: {amount_or_preset}")
                        else:
                            print(f"Usage: {cmd} <amount>|min|half|pot|max")
                    elif cmd == "config":
                        self.cmd_show_config()
                    elif cmd == "stakes" and len(parts) > 1:
                        self.config.preferred_stakes = parts[1]
                        print(f"Preferred stakes set to: {parts[1]}")
                    elif cmd == "strategy" and len(parts) > 1:
                        await self.cmd_set_strategy(parts[1])
                    elif cmd == "screenshot":
                        await self.cmd_screenshot(parts[1] if len(parts) > 1 else None)
                    elif cmd == "snap":
                        await self.cmd_quick_snapshot()
                    elif cmd == "autosnap":
                        if len(parts) > 1:
                            self.auto_screenshot_enabled = (parts[1].lower() == "on")
                            print(f"Auto-snapshot {'enabled' if self.auto_screenshot_enabled else 'disabled'}")
                        else:
                            print(f"Auto-snapshot is currently {'enabled' if self.auto_screenshot_enabled else 'disabled'}")
                    elif cmd == "snaps":
                        self.cmd_list_snapshots()
                    elif cmd == "snapdir":
                        print(f"Screenshots directory: {self.screenshot_dir}")
                    elif cmd == "url":
                        await self.cmd_show_urls()
                    else:
                        print(f"Unknown command: {cmd}. Type 'help' for commands.")

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    import traceback
                    print(f"\nError: {e}")
                    traceback.print_exc()
                    print()

        finally:
            await self.stop()
            print("\nGoodbye!")

    # === 命令实现 ===

    async def cmd_login(self):
        """Login command."""
        print("\n" + "-" * 60)
        print("  Manual Login Required")
        print("-" * 60)
        print("  Please log in to the poker website in the browser.")
        print("  This program will wait until login is detected.\n")
        print("  Press Ctrl+C to cancel.\n")

        logged_in = await self.platform.ensure_logged_in()

        if logged_in:
            print("✓ Logged in successfully!")
        else:
            print("✗ Login failed or timeout.")
        print()

    async def cmd_tables(self, filter_stakes: Optional[str] = None):
        """List tables command."""
        filter_obj = TableFilter(
            stakes=filter_stakes or self.config.preferred_stakes,
            min_players=self.config.min_players,
            max_players=self.config.max_players
        )

        tables = await self.platform.adapter.get_available_tables(
            self.platform.lobby_page,
            filter_obj
        )

        print(f"\n--- Available Tables ({len(tables)}) ---")
        if not tables:
            print("  No tables found.")
        else:
            for i, table in enumerate(tables[:20]):
                visited = " [VISITED]" if (
                    table.table_id and
                    self.platform.adapter.is_table_visited(table.table_id)
                ) else ""
                print(f"  {i+1:2d}. {table.stakes or '?'} "
                      f"({table.players}/{table.max_players})"
                      f"{visited}")
                print(f"       {table.url}")

        print()

    async def cmd_best_table(self):
        """Show best available table."""
        best = await self.platform.select_best_table()
        if not best:
            print("\nNo available tables.\n")
            return

        visited = " (VISITED)" if (
            best.table_id and
            self.platform.adapter.is_table_visited(best.table_id)
        ) else ""

        print(f"\n--- Best Available Table (Strategy: {self.config.table_selection_strategy.value}) ---")
        print(f"  Stakes: {best.stakes or '?'}")
        print(f"  Players: {best.players}/{best.max_players}{visited}")
        print(f"  URL: {best.url}")
        print()

    async def cmd_open_table(self, target: Optional[str] = None):
        """Open table command."""
        if target is None or target == "best":
            table_id = await self.platform.open_table()
            if table_id:
                print(f"\nOpened table: {table_id}\n")
            return

        if target.isdigit():
            idx = int(target) - 1
            tables = await self.platform.get_available_tables()
            if 0 <= idx < len(tables):
                await self.platform.open_table(table_info=tables[idx])
                print(f"\nOpened table {idx+1}\n")
            else:
                print(f"\nInvalid index: {target}\n")
        else:
            await self.platform.open_table(table_url=target)
            print(f"\nOpened URL: {target}\n")

    async def cmd_join(self, buyin_type: str = "min"):
        """Quick join - find best table, open it, sit down, and buy-in."""
        print("\n=== Quick Join ===")

        original_last_prompt = self.last_prompt_actions
        self.last_prompt_actions = frozenset()

        try:
            print("0. Ensuring we're in lobby...")
            try:
                await self.platform.navigate_to_lobby()
                print("   ✓ In lobby")
            except Exception as e:
                print(f"   ✗ Failed to navigate to lobby: {e}")
                print()
                return

            print("1. Finding best table...")
            best = await self.platform.select_best_table()
            if not best:
                print("   ✗ No available tables")
                print()
                return

            print(f"   ✓ Found: {best.stakes} ({best.players}/{best.max_players})")

            print(f"2. Opening table...")
            table_id = await self.platform.open_table(table_info=best)
            if not table_id:
                print("   ✗ Failed to open table")
                print()
                return

            print(f"   ✓ Opened table: {table_id}")

            print("   Waiting for table to load...")
            await asyncio.sleep(3)

            print("3. Sitting down...")
            sit_success = await self.platform.try_sit_down()
            if not sit_success:
                print("   ✗ Failed to sit down")
                print()
                return

            print("   ✓ Sat down successfully")

            print("   Waiting for buy-in popup...")
            await asyncio.sleep(2)

            print(f"4. Buy-in ({buyin_type})...")
            if buyin_type.lower() == "min":
                await self.cmd_buyin_min()
            elif buyin_type.lower() == "max":
                await self.cmd_buyin_max()
            elif buyin_type.lower() == "default":
                await self.cmd_buyin_default()
            elif buyin_type.isdigit():
                await self.cmd_buyin_amount(int(buyin_type))
            else:
                print(f"   ✗ Unknown buy-in type: {buyin_type}")

            print("\n=== Join complete ===")
        finally:
            self.last_prompt_actions = original_last_prompt

    async def cmd_game_state(self):
        """Show game state."""
        state = await self.platform.get_game_state()
        actions = await self.platform.get_all_visible_actions()
        available = actions.get('available', [])

        print(f"\n--- Game State ---")
        print(f"  Pot: {state.pot}")
        print(f"  Community Cards: {state.community_cards}")
        print(f"  My Seat: {state.my_seat_id}")
        print(f"  To Call: {state.to_call}")
        print(f"  Min Raise: {state.min_raise}")
        print(f"  My Turn: {state.is_my_turn}")
        if available:
            print(f"  Available Actions: {', '.join(available)}")
        else:
            print(f"  Available Actions: (none)")
        print()

    async def cmd_available_actions(self):
        """Show available actions (bypasses turn check for debugging)."""
        actions = await self.platform.get_all_visible_actions()

        print(f"\n=== Available Actions ===")

        available = actions.get('available', [])
        if available:
            print(f"Actions:")
            for action in available:
                if action in ["fold", "check"]:
                    print(f"  • {action}")
                elif action == "call":
                    print(f"  • call ({actions.get('to_call', 0)})")
                elif action in ["raise", "bet"]:
                    print(f"  • {action} <amount>|min|half|pot|max")
                    print(f"    (min: {actions.get('min_raise', 0)})")
                elif action == "allin":
                    print(f"  • allin")
        else:
            print("No actions available")

        presets = actions.get('presets', {})
        if presets:
            preset_labels = []
            if presets.get('min'):
                preset_labels.append("min")
            if presets.get('half'):
                preset_labels.append("½ Pot")
            if presets.get('pot'):
                preset_labels.append("Pot")
            if presets.get('max'):
                preset_labels.append("Max")
            print(f"\nPresets: {', '.join(preset_labels)}")

        to_call = actions.get('to_call', 0)
        if to_call > 0:
            print(f"\nTo Call: {to_call}")

        print()

    async def cmd_execute_action(self, action: str, amount: Optional[int] = None, preset: Optional[str] = None):
        """Execute a game action."""
        from src.core.interfaces import GameAction, ActionType

        action_map = {
            "fold": ActionType.FOLD,
            "check": ActionType.CHECK,
            "call": ActionType.CALL,
            "raise": ActionType.RAISE,
            "bet": ActionType.RAISE,
            "allin": ActionType.ALL_IN,
        }

        action_type = action_map.get(action)
        if not action_type:
            print(f"Unknown action: {action}")
            return

        game_action = GameAction(action_type=action_type)
        if amount is not None:
            game_action.amount = amount
        if preset is not None:
            game_action.bet_size_hint = preset

        success = await self.platform.execute_action(game_action)

        if amount:
            print(f"\n{action} {amount}: " + ("✓" if success else "✗") + "\n")
        else:
            print(f"\n{action}: " + ("✓" if success else "✗") + "\n")

        if self.auto_screenshot_enabled:
            context = f"action_{action}{f'_{amount}' if amount else ''}"
            await self._take_full_snapshot(context)

    def cmd_show_config(self):
        """Show current config."""
        print(f"\n--- Current Configuration ---")
        print(f"  Headless: {self.config.headless}")
        print(f"  Preferred Stakes: {self.config.preferred_stakes}")
        print(f"  Table Strategy: {self.config.table_selection_strategy.value}")
        print(f"  Max Tables: {self.config.max_tables}")
        print(f"  Strategy Type: {self.config.strategy_type}")
        print(f"  User Data Dir: {self.config.user_data_dir}")
        print()

    async def cmd_set_strategy(self, strategy_str: str):
        """Set table selection strategy."""
        strategy_map = {
            "fifo": TableSelectionStrategy.FIFO,
            "most": TableSelectionStrategy.MOST_PLAYERS,
            "least": TableSelectionStrategy.LEAST_PLAYERS,
            "random": TableSelectionStrategy.RANDOM,
        }

        strategy = strategy_map.get(strategy_str.lower())
        if not strategy:
            print(f"Unknown strategy: {strategy_str}")
            print(f"Valid options: {', '.join(strategy_map.keys())}")
            return

        self.config.table_selection_strategy = strategy
        print(f"Table selection strategy set to: {strategy.value}")

    async def cmd_show_urls(self):
        """Show current URLs."""
        print(f"\n--- Current URLs ---")
        print(f"  Lobby: {self.platform.lobby_page.url}")
        for table_id, page in self.platform.table_pages.items():
            print(f"  Table {table_id}: {page.url}")
        print()

    async def cmd_screenshot(self, name: Optional[str] = None):
        """Take a screenshot (image only)."""
        import time

        if name is None:
            name = f"screenshot_{int(time.time())}.png"

        lobby_path = f"{self.screenshot_dir}/lobby_{name}"
        await self.platform.lobby_page.screenshot(path=lobby_path)
        print(f"Saved lobby screenshot: {lobby_path}")

        for i, (table_id, page) in enumerate(self.platform.table_pages.items()):
            table_path = f"{self.screenshot_dir}/table_{table_id}_{name}"
            await page.screenshot(path=table_path)
            print(f"Saved table screenshot: {table_path}")

    async def cmd_quick_snapshot(self):
        """Quick snapshot - captures images and page data for debugging."""
        await self._take_full_snapshot()

    async def _take_full_snapshot(self, context: str = ""):
        """Take a full snapshot including images, HTML, and game state."""
        import time
        import json

        timestamp = int(time.time())
        self.screenshot_counter += 1

        snap_dir = f"{self.screenshot_dir}/snap_{timestamp}"
        os.makedirs(snap_dir, exist_ok=True)

        info = {
            "timestamp": timestamp,
            "counter": self.screenshot_counter,
            "context": context,
            "urls": {
                "lobby": self.platform.lobby_page.url
            },
            "tables": [],
            "game_state": None,
            "available_actions": None
        }

        await self.platform.lobby_page.screenshot(path=f"{snap_dir}/lobby.png")
        html = await self.platform.lobby_page.content()
        with open(f"{snap_dir}/lobby.html", "w", encoding="utf-8") as f:
            f.write(html)
        info["urls"]["lobby"] = self.platform.lobby_page.url

        for table_id, page in self.platform.table_pages.items():
            table_info = {
                "table_id": table_id,
                "url": page.url
            }

            await page.screenshot(path=f"{snap_dir}/table_{table_id}.png")
            html = await page.content()
            with open(f"{snap_dir}/table_{table_id}.html", "w", encoding="utf-8") as f:
                f.write(html)

            info["tables"].append(table_info)

        try:
            state = await self.platform.get_game_state()
            info["game_state"] = {
                "pot": state.pot,
                "community_cards": state.community_cards,
                "my_seat_id": state.my_seat_id,
                "to_call": state.to_call,
                "min_raise": state.min_raise
            }
        except Exception as e:
            info["game_state_error"] = str(e)

        try:
            actions = await self.platform.get_available_actions()
            info["available_actions"] = actions
        except Exception as e:
            info["actions_error"] = str(e)

        with open(f"{snap_dir}/info.json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Snapshot saved to: {snap_dir}")
        print(f"   - {len(info['tables']) + 1} screenshots")
        print(f"   - {len(info['tables']) + 1} HTML files")
        print(f"   - Game state captured")
        print()

    def cmd_list_snapshots(self):
        """List recent snapshots."""
        snap_dirs = []
        for entry in os.listdir(self.screenshot_dir):
            path = os.path.join(self.screenshot_dir, entry)
            if os.path.isdir(path) and entry.startswith("snap_"):
                snap_dirs.append(path)

        snap_dirs.sort(reverse=True)

        print(f"\n--- Recent Snapshots ({len(snap_dirs)}) ---")
        if not snap_dirs:
            print("  No snapshots found.")
        else:
            for i, snap_path in enumerate(snap_dirs[:10]):
                basename = os.path.basename(snap_path)
                timestamp = basename.replace("snap_", "")
                try:
                    import time
                    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(timestamp)))
                except:
                    dt = "Unknown"

                files = os.listdir(snap_path)
                images = [f for f in files if f.endswith(".png")]
                htmls = [f for f in files if f.endswith(".html")]

                print(f"  {i+1}. {basename}")
                print(f"     Time: {dt}")
                print(f"     Files: {len(files)} ({len(images)} images, {len(htmls)} HTML)")
        print()

    async def maybe_auto_snapshot(self, context: str = ""):
        """Take automatic snapshot if enabled."""
        if self.auto_screenshot_enabled:
            await self._take_full_snapshot(context)

    async def cmd_buyin_amount(self, amount: int):
        """Set buy-in amount and confirm with OK."""
        page = self.platform._get_table_page()
        if not page:
            print("No active table page found!")
            return

        try:
            success = await self.platform.adapter.set_buyin_amount(page, amount)
            if success:
                confirm_success = await self.platform.adapter.confirm_buyin(page)
                if confirm_success:
                    print(f"✓ Buy-in {amount} confirmed!")
                else:
                    print("✗ Failed to click OK")
            else:
                print("✗ Failed to set buy-in amount")
        except Exception as e:
            print(f"Error during buy-in: {e}")

    async def cmd_buyin_default(self):
        """Directly click OK with current default amount."""
        page = self.platform._get_table_page()
        if not page:
            print("No active table page found!")
            return

        try:
            success = await self.platform.adapter.confirm_buyin(page)
            if success:
                print("✓ Buy-in confirmed with default amount!")
            else:
                print("✗ Failed to click OK")
        except Exception as e:
            print(f"Error during buy-in: {e}")

    async def cmd_buyin_min(self):
        """Click Min button then OK."""
        page = self.platform._get_table_page()
        if not page:
            print("No active table page found!")
            return

        try:
            success = await self.platform.adapter.select_min_buyin(page)
            if success:
                confirm_success = await self.platform.adapter.confirm_buyin(page)
                if confirm_success:
                    print("✓ Buy-in Min confirmed!")
                else:
                    print("✓ Selected Min, but failed to click OK")
            else:
                print("✗ Failed to select Min")
        except Exception as e:
            print(f"Error during buy-in: {e}")

    async def cmd_buyin_max(self):
        """Click Max button then OK."""
        page = self.platform._get_table_page()
        if not page:
            print("No active table page found!")
            return

        try:
            success = await self.platform.adapter.select_max_buyin(page)
            if success:
                confirm_success = await self.platform.adapter.confirm_buyin(page)
                if confirm_success:
                    print("✓ Buy-in Max confirmed!")
                else:
                    print("✓ Selected Max, but failed to click OK")
            else:
                print("✗ Failed to select Max")
        except Exception as e:
            print(f"Error during buy-in: {e}")

    async def cmd_buyin_cancel(self):
        """Cancel buy-in popup."""
        page = self.platform._get_table_page()
        if not page:
            print("No active table page found!")
            return

        try:
            success = await self.platform.adapter.cancel_buyin(page)
            if success:
                print("✓ Buy-in popup cancelled")
            else:
                print("✗ Failed to cancel buy-in")
        except Exception as e:
            print(f"Error cancelling buy-in: {e}")
