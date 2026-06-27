"""
Ring Game CLI 用户交互模块。

.. deprecated::
    本模块已废弃，请使用 PilotDecider（src.core.pilot_decider）。
    RingPlayerConfig 直接设置 pilot_mode=PilotMode.ASSIST 即可，
    无需后续猴子补丁替换。
"""
import logging
import warnings
from typing import Any, Dict, Tuple

from src.platforms.arena.game import ActionType as ArenaActionType
from src.strategies.table_strategy import TableAction, TableActionType
from src.utils.cli_player import (
    ActionChoice,
    build_default,
    decide_hand_with_strategy,
    prompt_hand_action,
    prompt_table_action,
)

arena_logger = logging.getLogger("arena")

# ActionChoice 动作 -> TableActionType
_TABLE_ACTION_MAP = {
    "none": TableActionType.NONE,
    "sit_in": TableActionType.SIT_IN,
    "sit_out": TableActionType.SIT_OUT,
    "leave": TableActionType.LEAVE,
    "add_chips": TableActionType.ADD_CHIPS,
}


class CLIRingPlayer:
    """
    CLI 用户玩家。

    .. deprecated::
        请使用 RingPlayerConfig(pilot_mode=PilotMode.ASSIST) 替代。
    """

    @classmethod
    def create(cls, player: "RingPlayer") -> "RingPlayer":
        """从现有 RingPlayer 创建 CLIRingPlayer。"""
        warnings.warn(
            "CLIRingPlayer 已废弃，请使用 RingPlayerConfig(pilot_mode=PilotMode.ASSIST)",
            DeprecationWarning,
            stacklevel=2,
        )

        async def _cli_hand(payload):
            return await cls._cli_decide_hand_action(player, payload)

        async def _cli_table(payload):
            return await cls._cli_decide_table_action(player, payload)

        player._decide_hand_action = _cli_hand
        player._decide_table_action = _cli_table
        player.is_human = True
        return player

    @staticmethod
    async def _cli_decide_hand_action(player, payload: Dict[str, Any]) -> Tuple[str, int]:
        """手牌决策：复用统一 CLI 提示（GTO 默认）"""
        # 决策上下文用于日志
        ctx = (
            f"stage={payload.get('current_stage', '?')} "
            f"hand={' '.join(payload.get('hole_cards', []))} "
            f"board={' '.join(payload.get('community_cards', []))} "
            f"pot={payload.get('pot', 0)} to_call={payload.get('to_call', 0)}"
        )

        # 准备 GTO 默认动作
        default = build_default(
            payload,
            strategy_name=getattr(player, "_cli_strategy", "gto"),
        )

        choice: ActionChoice = await prompt_hand_action(
            payload,
            default=default,
            prompt_prefix="ring",
            context=ctx,
        )
        action_str = choice.raw or choice.action.upper()
        if choice.action == "allin" and not choice.raw:
            action_str = "ALL_IN"
        arena_logger.info(
            f"🎮 CLI 手牌决策: {action_str} {choice.amount} (来源={choice.source}) | {ctx}"
        )
        return action_str, choice.amount

    @staticmethod
    async def _cli_decide_table_action(player, payload: Dict[str, Any]) -> TableAction:
        """桌位决策：复用统一 CLI 提示（默认 none 继续游戏）"""
        ctx = (
            f"chips={payload.get('my_chips', 0)} "
            f"bank={payload.get('my_bank', 0)} "
            f"playing={payload.get('is_playing', False)}"
        )

        choice: ActionChoice = await prompt_table_action(
            payload,
            default=ActionChoice("none", 0, "none", "默认继续游戏", "fallback"),
            prompt_prefix="ring",
            title="桌位状态",
            context=ctx,
        )

        arena_logger.info(
            f"🎮 CLI 桌位决策: {choice.action} {choice.amount} (来源={choice.source}) | {ctx}"
        )
        action_type = _TABLE_ACTION_MAP.get(choice.action, TableActionType.NONE)
        return TableAction(
            action_type=action_type,
            amount=choice.amount if choice.action == "add_chips" else 0,
            reasoning=f"CLI {choice.source}: {choice.reasoning or choice.action}",
        )
