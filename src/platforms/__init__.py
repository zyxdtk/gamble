"""
Platform implementations for the Texas Hold'em AI system.
"""

from .browser import BrowserPlatform

__all__ = [
    "BrowserPlatform",
    "ArenaPlatform",
    "ArenaConfig",
    "ArenaPlayerConfig",
    "ArenaReport",
    "RingPlatform",
    "RingConfig",
    "RingPlayerConfig",
    "RingReport",
]


def __getattr__(name):
    """延迟导入 Arena 模块，避免 torch 依赖阻断导入"""
    if name in ("ArenaPlatform", "ArenaConfig", "ArenaPlayerConfig", "ArenaReport"):
        from . import arena
        return getattr(arena, name)
    if name in ("RingPlatform", "RingConfig", "RingPlayerConfig", "RingReport"):
        from . import arena
        return getattr(arena, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
