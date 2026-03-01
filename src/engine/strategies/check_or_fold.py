from src.engine.brain_base import Brain
from src.engine.action_plan import ActionPlan, ActionType
from src.core.game_state import GameState


class CheckOrFoldBrain(Brain):
    strategy_name = "checkorfold"
    
    def create_initial_plan(self, state: GameState) -> ActionPlan:
        return ActionPlan(
            primary_action=ActionType.CHECK,
            fallback_action=ActionType.FOLD,
            reasoning="Check or Fold策略：能过则过，不能过就弃牌"
        )
    
    def update_plan(self, state: GameState) -> ActionPlan:
        return self.create_initial_plan(state)
    
    def deep_think(self, state: GameState) -> ActionPlan:
        return self.create_initial_plan(state)
