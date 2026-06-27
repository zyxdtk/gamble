"""
Core abstraction layer for Texas Hold'em AI system.
Provides platform-agnostic interfaces and common types.
"""

from .interfaces import (
    GamePlatform,
    GameAction,
    ActionType,
    GameState,
    Player,
)
from .events import GameEvent, EventType, EventBus, get_event_bus
from .pilot_decider import PilotDecider
from .dispatch import SessionConfig, register_runner, get_runner

__all__ = [
    "GamePlatform",
    "GameAction",
    "ActionType",
    "GameState",
    "Player",
    "GameEvent",
    "EventType",
    "EventBus",
    "get_event_bus",
    "PilotDecider",
    "SessionConfig",
    "register_runner",
    "get_runner",
]
