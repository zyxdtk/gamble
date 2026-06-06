"""
Browser-based game platform implementation.

Wraps the existing bot code to implement the GamePlatform interface.
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Callable

from ...core.interfaces import (
    GamePlatform,
    GameState,
    Player,
    GameAction,
    ActionType,
)
from ...core.events import (
    EventBus,
    EventType,
    GameEvent,
    get_event_bus,
)
from ...utils.logger import bot_logger


class BrowserPlatform(GamePlatform):
    """
    GamePlatform implementation for ReplayPoker via browser automation.
    
    This wraps the existing BrowserManager and TableManager from the bot module.
    """

    def __init__(
        self,
        headless: bool = False,
        auto_mode: bool = True,
        event_bus: EventBus = None,
    ):
        self._headless = headless
        self._auto_mode = auto_mode
        self._event_bus = event_bus or get_event_bus()
        self._subscribers: List[Callable] = []
        
        # Lazy imports to avoid circular dependencies
        self._browser_manager = None
        self._table_manager = None
        self._initialized = False
        self._last_hand_count = 0

    async def initialize(self, **kwargs) -> None:
        """Initialize the browser and connect to ReplayPoker."""
        from ...bot.browser_manager import BrowserManager
        
        # Override parameters from kwargs
        headless = kwargs.get("headless", self._headless)
        auto_mode = kwargs.get("auto_mode", self._auto_mode)
        
        bot_logger.info("Initializing BrowserPlatform...")
        
        # Create browser manager
        self._browser_manager = BrowserManager(
            headless=headless,
            auto_mode=auto_mode,
            apprentice_mode=False,
        )
        
        await self._browser_manager.start()
        
        # Get the first table manager
        if self._browser_manager.table_managers:
            self._table_manager = list(self._browser_manager.table_managers.values())[0]
        
        self._initialized = True
        
        # Publish connected event
        self._event_bus.publish(EventType.CONNECTED, {"platform": "browser"})
        
        bot_logger.info("BrowserPlatform initialized successfully")

    async def get_game_state(self) -> GameState:
        """Get the current game state from the browser."""
        if not self._table_manager:
            raise RuntimeError("BrowserPlatform not initialized")
        
        # Get the internal state
        internal_state = self._table_manager.state
        
        # Convert to core GameState
        core_state = GameState(
            hole_cards=internal_state.hole_cards.copy(),
            community_cards=internal_state.community_cards.copy(),
            pot=internal_state.pot,
            my_seat_id=internal_state.my_seat_id,
            active_seat=internal_state.active_seat,
            to_call=internal_state.to_call,
            min_raise=internal_state.min_raise,
            max_raise=internal_state.max_raise,
            available_actions=self._convert_actions(internal_state.available_actions),
            players={},
            total_chips=internal_state.total_chips,
            current_stage=internal_state.current_stage,
            big_blind=self._table_manager.big_blind if hasattr(self._table_manager, "big_blind") else 2,
        )
        
        # Convert players
        for seat_id, player in internal_state.players.items():
            core_player = Player(
                seat_id=player.seat_id,
                user_id=player.user_id,
                name=player.name,
                chips=player.chips,
                is_active=player.is_active,
                is_acting=player.is_acting,
                status=player.status,
                hands_played=player.hands_played,
                vpip_actions=player.vpip_actions,
                pfr_actions=player.pfr_actions,
                bet=player.bet,
            )
            core_state.players[seat_id] = core_player
        
        return core_state

    async def execute_action(self, action: GameAction) -> bool:
        """Execute an action in the browser."""
        if not self._table_manager or not self._table_manager.play_manager:
            raise RuntimeError("BrowserPlatform not initialized")
        
        bot_logger.info(f"Executing action: {action.action_type.value} (amount: {action.amount})")
        
        # Convert GameAction to the format expected by PlayManager
        success = await self._table_manager.play_manager.perform_click(
            action_text=action.action_type.value,
            amount=action.amount,
            bet_size_hint=action.bet_size_hint,
        )
        
        if success:
            # Publish action event
            self._event_bus.publish(EventType.PLAYER_ACTION, {
                "action": action.action_type.value,
                "amount": action.amount,
                "reasoning": action.reasoning,
            })
        
        return success

    async def wait_for_my_turn(self, timeout: float = 300.0) -> bool:
        """Wait until it's our turn to act."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if not self._table_manager:
                await asyncio.sleep(0.5)
                continue
            
            # Update state from DOM
            await self._table_manager.play_manager.update_state_from_dom()
            
            # Check if it's our turn
            state = await self.get_game_state()
            if state.is_my_turn:
                return True
            
            await asyncio.sleep(0.5)
        
        bot_logger.warning(f"wait_for_my_turn timed out after {timeout}s")
        return False

    async def wait_for_hand_start(self, timeout: float = 300.0) -> bool:
        """Wait for a new hand to start."""
        if not self._table_manager:
            raise RuntimeError("BrowserPlatform not initialized")
        
        start_time = time.time()
        initial_hands = self._table_manager.hands_played
        
        bot_logger.info(f"Waiting for hand start (current hands: {initial_hands})")
        
        while time.time() - start_time < timeout:
            # Update state
            await self._table_manager.play_manager.update_state_from_dom()
            
            # Check if hand count increased
            if self._table_manager.hands_played > initial_hands:
                # Publish hand start event
                state = await self.get_game_state()
                self._event_bus.publish(EventType.HAND_START, {
                    "hand_number": self._table_manager.hands_played,
                    "hole_cards": state.hole_cards,
                })
                
                if state.hole_cards:
                    self._event_bus.publish(EventType.HOLE_CARDS_DEALT, {
                        "cards": state.hole_cards,
                    })
                
                return True
            
            await asyncio.sleep(0.5)
        
        bot_logger.warning(f"wait_for_hand_start timed out after {timeout}s")
        return False

    async def shutdown(self) -> None:
        """Clean up and shut down the browser."""
        bot_logger.info("Shutting down BrowserPlatform...")
        
        if self._browser_manager:
            await self._browser_manager.stop()
        
        self._initialized = False
        
        # Publish disconnected event
        self._event_bus.publish(EventType.DISCONNECTED, {"platform": "browser"})
        
        bot_logger.info("BrowserPlatform shut down")

    def subscribe_events(self, callback: Callable[[GameEvent], None]) -> None:
        """Subscribe to game events."""
        self._subscribers.append(callback)
        self._event_bus.subscribe_all(callback)

    def _convert_actions(self, action_strings: List[str]) -> List[ActionType]:
        """Convert action strings to ActionType enum."""
        action_map = {
            "fold": ActionType.FOLD,
            "check": ActionType.CHECK,
            "call": ActionType.CALL,
            "raise": ActionType.RAISE,
            "bet": ActionType.BET,
            "all in": ActionType.ALL_IN,
            "all_in": ActionType.ALL_IN,
        }
        
        actions = []
        for action_str in action_strings:
            action_type = action_map.get(action_str.lower())
            if action_type:
                actions.append(action_type)
        
        return actions
