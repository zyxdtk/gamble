from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionPlan, ActionType
from src.strategies.game_state import GameState


class BalancedStrategy(Strategy):
    """
    平衡型策略 (Balanced Strategy)
    直接使用基类提供的通用平衡决策模型。
    """
    strategy_name = "balanced"
    
    def __init__(self, thinking_timeout: float = 2.0):
        super().__init__(thinking_timeout)
    
    def make_decision(self, state: GameState) -> ActionPlan:
        """落实平衡决策逻辑"""
        return self._get_balanced_plan(state)