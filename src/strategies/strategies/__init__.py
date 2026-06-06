from .check_or_fold import CheckOrFoldStrategy
from .balanced import BalancedStrategy
from .exploitative import ExploitativeStrategy
from .range import RangeStrategy
from .aggressive import AggressiveStrategy

__all__ = [
    'CheckOrFoldStrategy',
    'BalancedStrategy',
    'ExploitativeStrategy',
    'RangeStrategy',
    'NeuralStrategy',
    'AggressiveStrategy',
    'ICMStrategy',
]


def __getattr__(name):
    """延迟导入，避免 torch 等重依赖阻断整个模块"""
    if name == 'NeuralStrategy':
        from .neural import NeuralStrategy
        return NeuralStrategy
    elif name == 'ICMStrategy':
        from .icm import ICMStrategy
        return ICMStrategy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
