"""
Core interfaces for the Texas Hold'em AI system.

This module defines the abstract base classes that all components must implement,
enabling decoupling between strategy logic and game platforms.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import asyncio


class ActionType(Enum):
    """Standard action types supported by all platforms."""
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"
    ALL_IN = "all_in"
    BET = "bet"


@dataclass
class GameAction:
    """Represents a game action to be executed."""
    action_type: ActionType
    amount: int = 0
    bet_size_hint: Optional[str] = None  # "min", "half_pot", "pot", "max"
    reasoning: str = ""


@dataclass
class Player:
    """Standard player representation across all platforms."""
    seat_id: int
    user_id: str
    name: str
    chips: int
    is_active: bool = True
    is_acting: bool = False
    status: str = "active"
    hands_played: int = 0
    vpip_actions: int = 0
    pfr_actions: int = 0
    bet: int = 0

    @property
    def vpip(self) -> float:
        return (self.vpip_actions / self.hands_played * 100) if self.hands_played > 0 else 0.0

    @property
    def pfr(self) -> float:
        return (self.pfr_actions / self.hands_played * 100) if self.hands_played > 0 else 0.0


@dataclass
class GameState:
    """Platform-agnostic game state representation."""
    hole_cards: List[str]
    community_cards: List[str]
    pot: int
    my_seat_id: Optional[int]
    active_seat: Optional[int]
    to_call: int
    min_raise: int
    max_raise: int
    available_actions: List[ActionType]
    players: Dict[int, Player]
    total_chips: int
    current_stage: str = "preflop"
    big_blind: int = 2

    @property
    def is_my_turn(self) -> bool:
        if self.my_seat_id is None:
            return False
        my_player = self.players.get(self.my_seat_id)
        return my_player.is_acting if my_player else False


class GamePlatform(ABC):
    """
    Abstract base class for a Texas Hold'em game platform.
    
    Implementations:
    - BrowserPlatform: Connects to ReplayPoker via browser automation
    - ArenaPlatform: Local simulation arena for strategy testing
    - WebPlatform: Web server for human vs bot games
    """

    @abstractmethod
    async def initialize(self, **kwargs) -> None:
        """Initialize the platform connection/setup."""
        pass

    @abstractmethod
    async def get_game_state(self) -> GameState:
        """Get the current game state snapshot."""
        pass

    @abstractmethod
    async def execute_action(self, action: GameAction) -> bool:
        """Execute an action in the game. Returns True if successful."""
        pass

    @abstractmethod
    async def wait_for_my_turn(self, timeout: float = 300.0) -> bool:
        """Wait until it's our turn to act. Returns False on timeout."""
        pass

    @abstractmethod
    async def wait_for_hand_start(self, timeout: float = 300.0) -> bool:
        """Wait for a new hand to start. Returns False on timeout."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up and shut down the platform."""
        pass

    @abstractmethod
    def subscribe_events(self, callback) -> None:
        """Subscribe to game events (see events.py)."""
        pass


class PlayerAgent(ABC):
    """
    Abstract base class for a player agent.
    
    A PlayerAgent encapsulates a strategy and makes decisions based on game state.
    It can be connected to any GamePlatform implementation.
    """

    @abstractmethod
    def decide_action(self, state: GameState) -> GameAction:
        """Make a decision based on the current game state."""
        pass

    @abstractmethod
    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle game events (e.g., opponent actions, showdowns)."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset agent state for a new game/session."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the agent name/strategy identifier."""
        pass


class GameRunner:
    """
    Orchestrates a game session between a PlayerAgent and a GamePlatform.
    
    This decouples the agent from the platform - any agent can run on any platform!
    """

    def __init__(self, platform: GamePlatform, agent: PlayerAgent):
        self.platform = platform
        self.agent = agent
        self._running = False

    async def run(self, max_hands: Optional[int] = None) -> None:
        """Run the game session."""
        self._running = True
        hands_played = 0

        try:
            await self.platform.initialize()
            
            while self._running and (max_hands is None or hands_played < max_hands):
                # Wait for a new hand to start
                if not await self.platform.wait_for_hand_start():
                    break

                # Play the hand
                await self._play_hand()
                hands_played += 1

        finally:
            await self.platform.shutdown()

    async def _play_hand(self) -> None:
        """Play a single hand of poker."""
        while self._running:
            # Wait for our turn
            if not await self.platform.wait_for_my_turn(timeout=30.0):
                break

            # Get current state
            state = await self.platform.get_game_state()
            
            if not state.is_my_turn:
                continue

            # Ask agent for decision
            action = self.agent.decide_action(state)

            # Execute the action
            await self.platform.execute_action(action)

            # If we folded, hand is over for us
            if action.action_type == ActionType.FOLD:
                break

    def stop(self) -> None:
        """Stop the game runner."""
        self._running = False
