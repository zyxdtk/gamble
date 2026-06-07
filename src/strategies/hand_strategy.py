"""
手牌策略接口 — Ring Game 中的手牌级别决策。

HandStrategy 是 Ring Game 中手牌决策的接口，
与 TableStrategy（桌位策略）分离。

StrategyHandAdapter 将现有 Strategy 适配为 HandStrategy，
实现向后兼容。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict

from src.strategies.game_state import GameState
from src.strategies.action_plan import ActionPlan
from src.strategies.strategy_base import Strategy


class HandStrategy(ABC):
    """手牌策略抽象基类"""

    strategy_name: str = "base"

    @abstractmethod
    def make_decision(self, state: GameState) -> ActionPlan:
        """根据手牌状态做出决策"""
        pass

    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """处理手牌事件（子类可覆盖）"""
        pass


class StrategyHandAdapter(HandStrategy):
    """
    适配器：将现有 Strategy 包装为 HandStrategy。

    使 Ring Game 可以复用所有已有的 Strategy 实现，
    无需修改 Strategy 基类。
    """

    def __init__(self, strategy: Strategy):
        self._strategy = strategy
        self.strategy_name = strategy.strategy_name

    @property
    def strategy(self) -> Strategy:
        return self._strategy

    def make_decision(self, state: GameState) -> ActionPlan:
        """委托给 Strategy.make_decision()"""
        return self._strategy.make_decision(state)

    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """委托给 Strategy.handle_event()"""
        self._strategy.handle_event(event_type, data)
