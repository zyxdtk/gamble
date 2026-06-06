from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionPlan
from src.strategies.game_state import GameState


class AggressiveStrategy(Strategy):
    """
    激进型策略 (Aggressive Strategy)
    特点：坚决执行 RFI（加注开局），拒绝平入，并具有更高的 3-bet 挤压频率。
    """
    strategy_name = "aggressive"
    
    def __init__(self, thinking_timeout: float = 2.0):
        super().__init__(thinking_timeout)
    
    def make_decision(self, state: GameState) -> ActionPlan:
        """执行激进型决策逻辑"""
        return self._get_aggressive_plan(state)