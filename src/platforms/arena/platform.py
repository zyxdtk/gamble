"""
Arena-based game platform implementation.

Wraps the existing arena code to implement the GamePlatform interface.
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
from ...arena.game import GameEngine, Street, ActionType as ArenaActionType
from ...utils.logger import bot_logger


class ArenaPlatform(GamePlatform):
    """
    GamePlatform implementation for the local simulation arena.
    
    This wraps the existing GameEngine from the arena module.
    """

    def __init__(
        self,
        players_info: List[Dict] = None,
        small_blind: int = 1,
        big_blind: int = 2,
        event_bus: EventBus = None,
    ):
        self._players_info = players_info or [
            {"name": "Hero", "stack": 1000},
            {"name": "Villain1", "stack": 1000},
            {"name": "Villain2", "stack": 1000},
        ]
        self._small_blind = small_blind
        self._big_blind = big_blind
        self._event_bus = event_bus or get_event_bus()
        self._subscribers: List[Callable] = []
        
        self._game_engine = None
        self._initialized = False
        self._current_player_idx = 0
        self._hand_in_progress = False
        self._hero_seat_id = 0

    async def initialize(self, **kwargs) -> None:
        """Initialize the arena game engine."""
        self._game_engine = GameEngine(
            players_info=self._players_info,
            small_blind=self._small_blind,
            big_blind=self._big_blind,
        )
        
        # Hero is always the first player
        self._hero_seat_id = 0
        self._initialized = True
        
        # Publish connected event
        self._event_bus.publish(EventType.CONNECTED, {"platform": "arena"})
        
        bot_logger.info("ArenaPlatform initialized successfully")

    async def get_game_state(self) -> GameState:
        """Get the current game state from the arena."""
        if not self._game_engine:
            raise RuntimeError("ArenaPlatform not initialized")
        
        # Convert Street enum to string
        street_map = {
            Street.PREFLOP: "preflop",
            Street.FLOP: "flop",
            Street.TURN: "turn",
            Street.RIVER: "river",
            Street.SHOWDOWN: "showdown",
        }
        
        # Convert treys Card ints to strings like "Ac", "Kh"
        from treys import Card
        
        # Build core GameState
        core_state = GameState(
            hole_cards=[Card.int_to_str(c) for c in self._game_engine.players[self._hero_seat_id].hole_cards],
            community_cards=[Card.int_to_str(c) for c in self._game_engine.community_cards],
            pot=self._game_engine.pot,
            my_seat_id=self._hero_seat_id,
            active_seat=self._current_player_idx if self._hand_in_progress else None,
            to_call=self._game_engine.current_bet - self._game_engine.players[self._hero_seat_id].bet_this_street,
            min_raise=self._game_engine.min_raise,
            max_raise=self._game_engine.players[self._hero_seat_id].stack + self._game_engine.players[self._hero_seat_id].bet_this_street,
            available_actions=self._get_available_actions(),
            players={},
            total_chips=self._game_engine.players[self._hero_seat_id].stack,
            current_stage=street_map.get(self._game_engine.current_street, "preflop"),
            big_blind=self._big_blind,
        )
        
        # Convert players
        for idx, player in enumerate(self._game_engine.players):
            core_player = Player(
                seat_id=idx,
                user_id=f"player_{idx}",
                name=player.name,
                chips=player.stack,
                is_active=player.is_active,
                is_acting=(idx == self._current_player_idx and self._hand_in_progress),
                status="all_in" if player.is_all_in else ("active" if player.is_active else "folded"),
                hands_played=0,
                vpip_actions=0,
                pfr_actions=0,
                bet=player.bet_this_street,
            )
            core_state.players[idx] = core_player
        
        return core_state

    async def execute_action(self, action: GameAction) -> bool:
        """Execute an action in the arena."""
        if not self._game_engine:
            raise RuntimeError("ArenaPlatform not initialized")
        
        # Map GameAction to ArenaActionType
        action_map = {
            ActionType.FOLD: ArenaActionType.FOLD,
            ActionType.CHECK: ArenaActionType.CHECK,
            ActionType.CALL: ArenaActionType.CALL,
            ActionType.RAISE: ArenaActionType.RAISE,
            ActionType.ALL_IN: ArenaActionType.ALL_IN,
            ActionType.BET: ArenaActionType.RAISE,
        }
        
        arena_action = action_map.get(action.action_type, ArenaActionType.FOLD)
        
        bot_logger.info(f"Executing action: {action.action_type.value} (amount: {action.amount})")
        
        # Execute the action in the game engine
        success = self._game_engine.execute_action(
            player_idx=self._hero_seat_id,
            action_type=arena_action,
            amount=action.amount,
        )
        
        if success:
            # Publish action event
            self._event_bus.publish(EventType.PLAYER_ACTION, {
                "action": action.action_type.value,
                "amount": action.amount,
                "reasoning": action.reasoning,
            })
            
            # Advance to next player
            await self._advance_game()
        
        return success

    async def wait_for_my_turn(self, timeout: float = 300.0) -> bool:
        """Wait until it's our turn to act."""
        # In arena, this is synchronous, just check current player
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self._hand_in_progress and self._current_player_idx == self._hero_seat_id:
                return True
            
            # Simulate other players acting if it's not our turn
            if self._hand_in_progress and self._current_player_idx != self._hero_seat_id:
                await self._simulate_opponent_action()
            
            await asyncio.sleep(0.1)
        
        return False

    async def wait_for_hand_start(self, timeout: float = 300.0) -> bool:
        """Wait for a new hand to start."""
        if not self._game_engine:
            raise RuntimeError("ArenaPlatform not initialized")
        
        # Start a new hand
        dealer_idx = 0  # Simple rotation for now
        self._game_engine.reset_hand(dealer_idx=dealer_idx)
        
        # Deal hole cards
        self._game_engine.deal_hole_cards()
        
        # Post blinds
        self._current_player_idx = self._game_engine.post_blinds()
        
        self._hand_in_progress = True
        
        # Publish events
        state = await self.get_game_state()
        self._event_bus.publish(EventType.HAND_START, {
            "hand_number": 1,
            "hole_cards": state.hole_cards,
        })
        
        self._event_bus.publish(EventType.HOLE_CARDS_DEALT, {
            "cards": state.hole_cards,
        })
        
        # Publish preflop event
        self._event_bus.publish(EventType.PREFLOP, {})
        
        return True

    async def shutdown(self) -> None:
        """Clean up and shut down the arena."""
        self._game_engine = None
        self._initialized = False
        self._hand_in_progress = False
        
        # Publish disconnected event
        self._event_bus.publish(EventType.DISCONNECTED, {"platform": "arena"})
        
        bot_logger.info("ArenaPlatform shut down")

    def subscribe_events(self, callback: Callable[[GameEvent], None]) -> None:
        """Subscribe to game events."""
        self._subscribers.append(callback)
        self._event_bus.subscribe_all(callback)

    def _get_available_actions(self) -> List[ActionType]:
        """Get available actions for the current player."""
        if not self._game_engine or not self._hand_in_progress:
            return []
        
        player = self._game_engine.players[self._current_player_idx]
        to_call = self._game_engine.current_bet - player.bet_this_street
        
        actions = []
        
        if to_call == 0:
            actions.append(ActionType.CHECK)
            actions.append(ActionType.RAISE)
        else:
            actions.append(ActionType.FOLD)
            actions.append(ActionType.CALL)
            if player.stack > 0:
                actions.append(ActionType.RAISE)
        
        if player.stack > 0 and to_call > player.stack:
            actions.append(ActionType.ALL_IN)
        
        return actions

    async def _advance_game(self) -> None:
        """Advance the game to the next player or street."""
        # Simple implementation - in a real arena, this would be more complex
        # Check if hand is over
        active_players = [p for p in self._game_engine.players if p.is_active]
        if len(active_players) <= 1:
            # Hand over - showdown
            winners = self._game_engine.get_winners()
            self._hand_in_progress = False
            self._event_bus.publish(EventType.HAND_END, {"winners": winners})
            return
        
        # Check if we need to move to next street
        # This is simplified - full implementation would be in GameEngine
        pass

    async def _simulate_opponent_action(self) -> None:
        """Simulate an opponent taking an action."""
        # Simple implementation - villains just call or fold
        if not self._game_engine or not self._hand_in_progress:
            return
        
        player = self._game_engine.players[self._current_player_idx]
        to_call = self._game_engine.current_bet - player.bet_this_street
        
        # Simple rule: call if to_call is small, otherwise fold
        if to_call <= self._big_blind * 2 and player.stack > to_call:
            action = ArenaActionType.CALL
        else:
            action = ArenaActionType.FOLD
        
        self._game_engine.execute_action(self._current_player_idx, action, 0)
        
        # Publish opponent action event
        self._event_bus.publish(EventType.OPPONENT_ACTION, {
            "player_id": self._current_player_idx,
            "player_name": player.name,
            "action": action.value,
        })
        
        # Advance to next player
        self._current_player_idx = (self._current_player_idx + 1) % len(self._game_engine.players)
