"""
Website adapters for browser platform.
"""
from .base import WebsiteAdapter, TableInfo, TableFilter
from .replay_poker import ReplayPokerAdapter

__all__ = [
    "WebsiteAdapter",
    "TableInfo",
    "TableFilter",
    "ReplayPokerAdapter",
]
