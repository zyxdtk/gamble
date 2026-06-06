from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionPlan, ActionType
from src.strategies.game_state import GameState


class CheckOrFoldStrategy(Strategy):
    strategy_name = "check_or_fold"

    def make_decision(self, state: GameState) -> ActionPlan:
        """落实 Check or Fold 核心逻辑"""
        if state.to_call == 0:
            plan = ActionPlan(ActionType.CHECK, reasoning="Check or Fold策略：能过则过")
        else:
            plan = ActionPlan(ActionType.FOLD, reasoning="Check or Fold策略：不能过就弃牌")
            
        plan.strategy_name = self.strategy_name
        plan.my_equity = getattr(self, "_last_equity", 0.0)
        return plan