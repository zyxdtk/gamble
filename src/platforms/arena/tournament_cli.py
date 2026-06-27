"""
MTT/SNG CLI 用户交互模块。

.. deprecated::
    本模块已废弃，请使用 PilotDecider（src.core.pilot_decider）。
    ArenaAgent 构造时直接传入 pilot_mode=PilotMode.ASSIST 即可，
    无需后续猴子补丁替换。
"""
import logging
import warnings
from typing import Any, Dict, Tuple

from src.platforms.arena.agent import ArenaAgent
from src.platforms.arena.game import ActionType as ArenaActionType
from src.utils.cli_player import (
    ActionChoice,
    build_default,
    prompt_hand_action,
)

arena_logger = logging.getLogger("arena")

# 归一化动作名 -> ArenaActionType
_ARENA_ACTION_MAP = {
    "fold": ArenaActionType.FOLD,
    "check": ArenaActionType.CHECK,
    "call": ArenaActionType.CALL,
    "raise": ArenaActionType.RAISE,
    "allin": ArenaActionType.ALL_IN,
}


class CLITournamentPlayer:
    """
    CLI 用户玩家（锦标赛模式）。

    .. deprecated::
        请使用 ArenaAgent(pilot_mode=PilotMode.ASSIST) 替代。
    """

    @classmethod
    def create(cls, agent: ArenaAgent) -> ArenaAgent:
        warnings.warn(
            "CLITournamentPlayer 已废弃，请使用 ArenaAgent(pilot_mode=PilotMode.ASSIST)",
            DeprecationWarning,
            stacklevel=2,
        )
        async def _cli_get_action(arena_state):
            return await cls._cli_decide_hand_action(agent, arena_state)

        agent.get_action = _cli_get_action
        agent.is_human = True
        return agent

    @staticmethod
    async def _cli_decide_hand_action(
        agent: ArenaAgent, engine: 'GameEngine'
    ) -> Tuple[ArenaActionType, int]:
        """CLI 手牌决策：复用统一 CLI 提示（GTO 默认）"""
        # 用 agent._translate_state 构造 GameState，再转为显示 payload
        game_state = agent._translate_state(engine)
        payload = CLITournamentPlayer._game_state_to_payload(game_state, engine)

        # 决策上下文用于日志
        ctx = (
            f"stage={payload.get('current_stage', '?')} "
            f"hand={' '.join(payload.get('hole_cards', []))} "
            f"board={' '.join(payload.get('community_cards', []))} "
            f"pot={payload.get('pot', 0)} to_call={payload.get('to_call', 0)}"
        )

        # 准备 GTO 默认动作（默认 gto，可被 agent 覆盖为其他策略）
        default = build_default(
            payload,
            strategy_name=getattr(agent, "_cli_strategy", "gto"),
        )

        choice: ActionChoice = await prompt_hand_action(
            payload,
            default=default,
            prompt_prefix="tourney",
            context=ctx,
        )

        arena_action = _ARENA_ACTION_MAP.get(choice.action, ArenaActionType.FOLD)
        amount = choice.amount if choice.action == "call" else choice.amount
        # 锦标赛模式 RAISE 是 "加注至" 不是 "增加"，amount 已经是 to-amount
        arena_logger.info(
            f"🎮 CLI 手牌决策: {arena_action.value} {amount} (来源={choice.source}) | {ctx}"
        )
        return arena_action, amount

    @staticmethod
    def _game_state_to_payload(game_state, engine: 'GameEngine') -> Dict[str, Any]:
        """从 GameState 对象构建显示 payload（统一 schema）"""
        # 确定可用动作（与 game.py 中的判定一致）
        available_actions = []
        if game_state.to_call == 0:
            available_actions = ["FOLD", "CHECK", "RAISE", "ALL_IN"]
        else:
            available_actions = ["FOLD", "CALL", "RAISE", "ALL_IN"]

        # 翻译当前阶段
        from src.platforms.arena.game import Street
        stage_map = {
            Street.PREFLOP: "preflop",
            Street.FLOP: "flop",
            Street.TURN: "turn",
            Street.RIVER: "river",
        }
        current_stage = stage_map.get(engine.current_street, "preflop")

        # 构建玩家信息
        players_data = {}
        for seat_id, sp in game_state.players.items():
            players_data[str(seat_id)] = {
                "user_id": sp.user_id,
                "name": sp.name,
                "chips": sp.chips,
                "is_active": sp.is_active,
                "status": sp.status,
                "bet": sp.bet,
                "hands_played": sp.hands_played,
                "vpip_actions": sp.vpip_actions,
                "pfr_actions": sp.pfr_actions,
            }

        return {
            "my_seat_id": game_state.my_seat_id,
            "hole_cards": game_state.hole_cards,
            "community_cards": game_state.community_cards,
            "pot": game_state.pot,
            "to_call": game_state.to_call,
            "min_raise": game_state.min_raise,
            "max_raise": game_state.max_raise,
            "available_actions": available_actions,
            "current_stage": current_stage,
            "players": players_data,
            "my_chips": game_state.players[game_state.my_seat_id].chips if game_state.my_seat_id in game_state.players else 0,
        }
