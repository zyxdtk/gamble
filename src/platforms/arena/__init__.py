"""
Arena platform implementation for local strategy testing.
"""

from .game import GameEngine, PlayerState, Street, ActionType

__all__ = [
    "ArenaPlatform",
    "ArenaConfig",
    "ArenaPlayerConfig",
    "ArenaReport",
    "GameEngine",
    "PlayerState",
    "Street",
    "ActionType",
    "ArenaAgent",
    "Competition",
    # MTT
    "MTTManager",
    "MTTConfig",
    "MTTReport",
    "MTTPlayerStats",
    "MTTPlayerConfig",
    "PrizePayout",
    "TournamentTable",
    "BlindSchedule",
    "BlindLevel",
    # SNG
    "SitAndGo",
    "SNGConfig",
    "SNGReport",
    "SNGPlayerStats",
]


def __getattr__(name):
    """延迟导入，避免在不需要时触发 torch 等重依赖"""
    if name == "ArenaPlatform":
        from .platform import ArenaPlatform
        return ArenaPlatform
    elif name == "ArenaConfig":
        from .platform import ArenaConfig
        return ArenaConfig
    elif name == "ArenaPlayerConfig":
        from .platform import ArenaPlayerConfig
        return ArenaPlayerConfig
    elif name == "ArenaReport":
        from .platform import ArenaReport
        return ArenaReport
    elif name == "ArenaAgent":
        from .agent import ArenaAgent
        return ArenaAgent
    elif name == "Competition":
        from .competition import Competition
        return Competition
    # MTT 相关
    elif name == "MTTManager":
        from .mtt import MTTManager
        return MTTManager
    elif name == "MTTConfig":
        from .mtt import MTTConfig
        return MTTConfig
    elif name == "MTTReport":
        from .mtt import MTTReport
        return MTTReport
    elif name == "MTTPlayerStats":
        from .mtt import MTTPlayerStats
        return MTTPlayerStats
    elif name == "MTTPlayerConfig":
        from .mtt import MTTPlayerConfig
        return MTTPlayerConfig
    elif name == "PrizePayout":
        from .mtt import PrizePayout
        return PrizePayout
    elif name == "TournamentTable":
        from .table import TournamentTable
        return TournamentTable
    elif name == "BlindSchedule":
        from .blind_schedule import BlindSchedule
        return BlindSchedule
    elif name == "BlindLevel":
        from .blind_schedule import BlindLevel
        return BlindLevel
    # SNG 相关
    elif name == "SitAndGo":
        from .sitngo import SitAndGo
        return SitAndGo
    elif name == "SNGConfig":
        from .sitngo import SNGConfig
        return SNGConfig
    elif name == "SNGReport":
        from .sitngo import SNGReport
        return SNGReport
    elif name == "SNGPlayerStats":
        from .sitngo import SNGPlayerStats
        return SNGPlayerStats
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
