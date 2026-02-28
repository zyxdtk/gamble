import asyncio
import argparse
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text

from .bot.poker_client import ReplayPokerClient
from .engine.brain import PokerBrain

console = Console()

class GameUI:
    def __init__(self, auto_mode=False):
        self.brain = PokerBrain()
        self.client = ReplayPokerClient(headless=False, auto_mode=auto_mode)
        self.layout = Layout()
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        self.layout["header"].update(Panel("Texas Hold'em AI Assistant", style="bold green"))
        self.layout["footer"].update(Panel("Waiting for game connection...", style="dim"))

    def generate_view(self, state):
        hole_cards = state.hole_cards
        community_cards = state.community_cards
        pot = state.pot
        
        # Analyze Hand
        if hole_cards and community_cards:
            score, hand_class = self.brain.evaluate_hand(hole_cards, community_cards)
            strength = self.brain.get_percentage_strength(score)
            advice = f"Hand: {hand_class} (Strength: {strength:.1%})"
            color = "green" if strength > 0.7 else "yellow" if strength > 0.4 else "red"
        elif hole_cards:
            advice = "Preflop: Waiting for board..."
            color = "blue"
        else:
            advice = "Waiting for deal..."
            color = "dim"

        # Body Content
        body_text = Text()
        body_text.append(f"\n Hole Cards: {hole_cards}\n", style="bold magenta")
        body_text.append(f" Community:  {community_cards}\n", style="bold cyan")
        body_text.append(f" Pot Size:   {pot}\n", style="bold yellow")
        
        self.layout["body"].update(Panel(body_text, title="Game State"))
        self.layout["footer"].update(Panel(advice, style=f"bold {color}"))
        
        return self.layout

    async def run(self):
        await self.client.start_browser()
        print("Browser started. Please login and join a table.")
        
        # Support for auto mode in main loop
        if self.client.auto_mode_enabled:
             print("[MODE] Running in Fully Autonomous Mode.")
        else:
             print("[MODE] Running in Assist Mode.")

        last_log = ""
        while True:
            # Check if page closed
            if self.client.page and self.client.page.is_closed():
                print("[STOP] Browser page closed. Exiting.", flush=True)
                break

            state = await self.client.get_game_state()
            hole_cards = state.hole_cards
            community_cards = state.community_cards
            
            # Simple Logging
            current_log = f"Hole: {hole_cards} | Board: {community_cards}"
            
            if hole_cards or community_cards:
                 # Evaluate
                score, hand_class = self.brain.evaluate_hand(hole_cards, community_cards)
                strength = self.brain.get_percentage_strength(score)
                current_log += f" | Rank: {hand_class} ({strength:.1%})"

            if current_log != last_log:
                print(current_log)
                last_log = current_log
            
            # If in auto mode, the logic inside poker_client's WS handler or a poll can trigger execute_decision.
            # For now, let's keep the client-side decision check if needed.
            if self.client.auto_mode_enabled:
                # The poker_client.py:main() had a check logic. 
                # Let's see if we should move that here or let poker_client handle it.
                # ReplayPokerClient.process_replay_poker_message already triggers HUD updates and handles auto logic?
                # Actually in current poker_client.py, it was in the main() loop.
                # Let's check for buttons here too if we want.
                buttons = await self.client.find_action_buttons()
                if buttons:
                     print("[AUTO] It's our turn! (Buttons visible)", flush=True)
                     suggestion = self.client.engine.decide(self.client.state)
                     print(f"[AUTO] Suggestion: {suggestion}", flush=True)
                     
                     await self.client.update_hud(suggestion)
                     await self.client.execute_decision(suggestion)
                     
                     # Wait a bit
                     await asyncio.sleep(5)
                
            await asyncio.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assist", action="store_true", help="Run in Assist Mode (default)")
    parser.add_argument("--auto", action="store_true", help="Run in Auto Mode")
    args = parser.parse_args()

    # If --auto is specified, run in auto mode
    ui = GameUI(auto_mode=args.auto)
    asyncio.run(ui.run())
