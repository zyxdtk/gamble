"""
Core abstraction layer for Texas Hold'em AI system.
Provides platform-agnostic interfaces and common types.
"""

from .interfaces import (
    GamePlatform,
    PlayerAgent,
    GameAction,
    ActionType,
    GameState,
    GameRunner,
)
from .events import GameEvent, EventType, EventBus, get_event_bus
from .adapters import StrategyToAgentAdapter, create_strategy_agent

__all__ = [
    "GamePlatform",
    "PlayerAgent",
    "GameAction",
    "ActionType",
    "GameState",
    "GameRunner",
    "GameEvent",
    "EventType",
    "EventBus",
    "get_event_bus",
    "StrategyToAgentAdapter",
    "create_strategy_agent",
]
