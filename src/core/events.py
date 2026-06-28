"""
Event system for the Texas Hold'em AI system.

Defines event types and a simple event bus for decoupled communication.
"""

from enum import Enum
from typing import Callable, Dict, List, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of game events."""
    # Hand lifecycle
    HAND_START = "hand_start"
    HAND_END = "hand_end"
    
    # Game stages
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"
    
    # Player actions
    PLAYER_ACTION = "player_action"
    OPPONENT_ACTION = "opponent_action"
    
    # State changes
    STATE_UPDATE = "state_update"
    HOLE_CARDS_DEALT = "hole_cards_dealt"
    COMMUNITY_CARDS_DEALT = "community_cards_dealt"
    
    # Table actions (Ring Game)
    TABLE_ACTION = "table_action"

    # Platform events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class GameEvent:
    """Represents a game event."""
    event_type: EventType
    data: Dict[str, Any]
    timestamp: float


class EventBus:
    """
    Simple event bus for decoupled communication.
    
    Components can publish events and subscribe to event types.
    """

    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._all_subscribers: List[Callable] = []

    def subscribe(self, event_type: EventType, callback: Callable[[GameEvent], None]) -> None:
        """Subscribe to a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def subscribe_all(self, callback: Callable[[GameEvent], None]) -> None:
        """Subscribe to all events."""
        self._all_subscribers.append(callback)

    def publish(self, event_type: EventType, data: Dict[str, Any]) -> None:
        """Publish an event to all subscribers."""
        import time
        event = GameEvent(
            event_type=event_type,
            data=data,
            timestamp=time.time()
        )
        
        # Notify type-specific subscribers
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(event)
                except Exception as e:
                    from src.utils.diagnostics import log_exception_with_traceback
                    log_exception_with_traceback(
                        logger, e,
                        f"[events] Error in event subscriber event_type={event_type} "
                        f"cb={getattr(callback, '__name__', str(callback))}",
                        level=logging.ERROR,
                        event_type=str(event_type),
                        cb=getattr(callback, "__name__", str(callback)),
                    )

        # Notify all-subscribers
        for callback in self._all_subscribers:
            try:
                callback(event)
            except Exception as e:
                from src.utils.diagnostics import log_exception_with_traceback
                log_exception_with_traceback(
                    logger, e,
                    f"[events] Error in all-event subscriber "
                    f"cb={getattr(callback, '__name__', str(callback))}",
                    level=logging.ERROR,
                    cb=getattr(callback, "__name__", str(callback)),
                )

    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            if callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)

    def unsubscribe_all(self, callback: Callable) -> None:
        """Unsubscribe from all events."""
        if callback in self._all_subscribers:
            self._all_subscribers.remove(callback)


# Global event bus instance
_global_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    return _global_event_bus
