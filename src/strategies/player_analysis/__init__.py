from .tags import PlayerTag, get_player_tag
from .database import PlayerDatabase
from .manager import PlayerManager
from .model import BaseRangeModel, ActionBasedRangeModel
from .stats_model import StatsAwareRangeModel
from .showdown_model import ShowdownAwareRangeModel

# 保持兼容性：默认 RangeModel 使用 ActionBased 实现
RangeModel = ActionBasedRangeModel

__all__ = [
    'PlayerTag',
    'get_player_tag',
    'PlayerDatabase',
    'PlayerManager',
    'BaseRangeModel',
    'ActionBasedRangeModel',
    'StatsAwareRangeModel',
    'ShowdownAwareRangeModel',
    'RangeModel'
]
