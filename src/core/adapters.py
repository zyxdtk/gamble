"""
Adapters for connecting existing components to the new core interfaces.

.. deprecated::
    StrategyToAgentAdapter 和 create_strategy_agent 已废弃，
    请使用 PilotDecider（src.core.pilot_decider）替代。
"""

from typing import Dict, Any
from .interfaces import (
    PlayerAgent,
    GameAction,
    ActionType,
    GameState as CoreGameState,
    Player as CorePlayer,
)
from .events import EventBus, EventType, get_event_bus
from ..strategies.strategy_base import Strategy
from ..strategies.game_state import GameState as StrategyGameState
from ..strategies.action_plan import ActionType as StrategyActionType
import logging

logger = logging.getLogger(__name__)


class StrategyToAgentAdapter(PlayerAgent):
    """
    Adapter that wraps an existing Strategy into a PlayerAgent.
    
    This allows all existing strategies to work with the new architecture!
    """

    def __init__(self, strategy: Strategy, event_bus: EventBus = None):
        self._strategy = strategy
        self._event_bus = event_bus or get_event_bus()

    @property
    def name(self) -> str:
        return self._strategy.strategy_name

    def decide_action(self, state: CoreGameState) -> GameAction:
        """Convert CoreGameState to StrategyGameState, get decision, convert back."""
        # Convert core state to strategy state
        strategy_state = self._convert_to_strategy_state(state)
        
        # Get decision from strategy
        action_plan = self._strategy.make_decision(strategy_state)
        
        # Convert action plan to GameAction
        to_call = state.to_call
        pot = state.pot
        
        # Use the existing get_action_for_bet method
        action_str, amount = action_plan.get_action_for_bet(to_call, pot)
        
        # Map to ActionType
        action_type_map = {
            "fold": ActionType.FOLD,
            "check": ActionType.CHECK,
            "call": ActionType.CALL,
            "raise": ActionType.RAISE,
            "all_in": ActionType.ALL_IN,
            "bet": ActionType.BET,
        }
        
        action_type = action_type_map.get(action_str.lower(), ActionType.FOLD)
        
        return GameAction(
            action_type=action_type,
            amount=amount,
            bet_size_hint=action_plan.bet_size_hint,
            reasoning=action_plan.reasoning
        )

    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Forward events to the strategy's handle_event method."""
        self._strategy.handle_event(event_type, data)

    def reset(self) -> None:
        """Reset the strategy state."""
        self._strategy.reset()

    def _convert_to_strategy_state(self, core_state: CoreGameState) -> StrategyGameState:
        """Convert CoreGameState to the existing StrategyGameState format."""
        strategy_state = StrategyGameState()
        
        # Copy basic fields
        strategy_state.hole_cards = core_state.hole_cards.copy()
        strategy_state.community_cards = core_state.community_cards.copy()
        strategy_state.pot = core_state.pot
        strategy_state.my_seat_id = core_state.my_seat_id
        strategy_state.active_seat = core_state.active_seat
        strategy_state.to_call = core_state.to_call
        strategy_state.min_raise = core_state.min_raise
        strategy_state.max_raise = core_state.max_raise
        strategy_state.total_chips = core_state.total_chips
        strategy_state.current_stage = core_state.current_stage
        strategy_state.big_blind = getattr(core_state, 'big_blind', 2)
        
        # Convert available actions to strings
        strategy_state.available_actions = [
            action.value for action in core_state.available_actions
        ]
        
        # Convert players
        for seat_id, core_player in core_state.players.items():
            from ..strategies.game_state import Player as StrategyPlayer
            strategy_player = StrategyPlayer(
                seat_id=core_player.seat_id,
                user_id=core_player.user_id,
                name=core_player.name,
                chips=core_player.chips,
                is_active=core_player.is_active,
                is_acting=core_player.is_acting,
                status=core_player.status,
                hands_played=core_player.hands_played,
                vpip_actions=core_player.vpip_actions,
                pfr_actions=core_player.pfr_actions,
                bet=core_player.bet,
            )
            strategy_state.players[seat_id] = strategy_player
        
        return strategy_state


def create_strategy_agent(strategy_name: str) -> PlayerAgent:
    """
    Factory function to create a PlayerAgent from a strategy name.
    
    Args:
        strategy_name: Name of the strategy (e.g., "balanced", "range", "exploitative")
        
    Returns:
        A PlayerAgent instance wrapping the requested strategy
    """
    from ..strategies.strategies import (
        BalancedStrategy,
        RangeStrategy,
        ExploitativeStrategy,
        CheckOrFoldStrategy,
        AggressiveStrategy,
        NeuralStrategy,
        GtoSolverStrategy,
    )
    
    strategy_map = {
        "balanced": BalancedStrategy,
        "range": RangeStrategy,
        "exploitative": ExploitativeStrategy,
        "checkorfold": CheckOrFoldStrategy,
        "aggressive": AggressiveStrategy,
        "neural": NeuralStrategy,
        "gto": GtoSolverStrategy,
        "gto_solver": GtoSolverStrategy,
    }
    
    if strategy_name not in strategy_map:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    
    strategy_class = strategy_map[strategy_name]
    strategy = strategy_class()
    
    return StrategyToAgentAdapter(strategy)