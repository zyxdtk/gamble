"""
飞行员决策器 — 根据 pilot_mode 编排 AI 和人类决策。

核心思路：
- 三个猴子补丁点已经统一使用 cli_player.py 的 payload schema → build_default() → prompt_hand_action() 流程
- PilotDecider 将这个流程正式化
- 输入/输出都在 payload dict / ActionChoice 层，与 cli_player.py schema 一致
- 各平台只需负责：自身状态 → payload，ActionChoice → 平台动作
- suggest() 是同步的（纯 AI），decide_hand()/decide_table() 是异步的（可能等待人类输入）
"""
from __future__ import annotations

import logging
from typing import Optional

from src.strategies.strategy_base import Strategy
from src.strategies.table_strategy import DefaultTableStrategy, TableStrategy, TableState, TableAction
from src.utils.cli_player import (
    ActionChoice,
    PilotMode,
    StdinMonitor,
    build_default,
    prompt_hand_action,
    prompt_table_action,
)

pilot_logger = logging.getLogger("pilot_decider")


class PilotDecider:
    """飞行员决策器 — 根据 pilot_mode 编排 AI 和人类决策"""

    def __init__(
        self,
        strategy: Strategy,
        pilot_mode: PilotMode,
        table_strategy: Optional[TableStrategy] = None,
        stdin_monitor: Optional[StdinMonitor] = None,
    ):
        self.strategy = strategy
        self.pilot_mode = pilot_mode
        self.table_strategy = table_strategy or DefaultTableStrategy()
        self.stdin_monitor = stdin_monitor

    def suggest(self, payload: dict) -> ActionChoice:
        """获取 AI 策略建议（同步，不等待人类）"""
        return build_default(payload, strategy_name=self.strategy.strategy_name)

    async def decide_hand(self, payload: dict, **prompt_kwargs) -> ActionChoice:
        """手牌决策

        AUTO: 直接返回 AI 建议
        MANAGED: AI 自主，除非 stdin_monitor 显示人类接管
        ASSIST: AI 建议为默认，人类确认/覆盖
        """
        ai_choice = self.suggest(payload)

        if self.pilot_mode == PilotMode.AUTO:
            return ai_choice

        if self.pilot_mode == PilotMode.MANAGED:
            if self.stdin_monitor and self.stdin_monitor.is_takeover:
                choice = await prompt_hand_action(
                    payload, default=ai_choice, **prompt_kwargs
                )
                # takeover 只接管一手，之后交还 AI
                self.stdin_monitor._takeover = False
                return choice
            return ai_choice

        # ASSIST
        return await prompt_hand_action(payload, default=ai_choice, **prompt_kwargs)

    async def decide_table(self, payload: dict, **prompt_kwargs) -> ActionChoice:
        """桌位决策

        AUTO: table_strategy.decide() → ActionChoice
        MANAGED: AI 自主，除非 stdin_monitor 显示人类接管
        ASSIST: AI 建议为默认，人类确认/覆盖
        """
        table_state = TableState(
            my_chips=payload.get("my_chips", 0),
            my_bank=payload.get("my_bank", 0),
            is_seated=payload.get("is_seated", False),
            is_playing=payload.get("is_playing", False),
            hands_played=payload.get("hands_played", 0),
            total_profit=payload.get("total_profit", 0),
            current_bb=payload.get("current_bb", 2),
            seat_count=payload.get("seat_count", 0),
            active_count=payload.get("active_count", 0),
            stop_loss_bb=payload.get("stop_loss_bb", 250),
            take_profit_bb=payload.get("take_profit_bb", 300),
            low_chips_bb=payload.get("low_chips_bb", 10),
            max_chips_bb=payload.get("max_chips_bb", 800),
        )

        action = self.table_strategy.decide(table_state)

        # 转换 TableAction → ActionChoice
        ai_choice = self._table_action_to_choice(action)

        if self.pilot_mode == PilotMode.AUTO:
            return ai_choice

        if self.pilot_mode == PilotMode.MANAGED:
            if self.stdin_monitor and self.stdin_monitor.is_takeover:
                choice = await prompt_table_action(
                    payload, default=ai_choice, **prompt_kwargs
                )
                self.stdin_monitor._takeover = False
                return choice
            return ai_choice

        # ASSIST
        return await prompt_table_action(payload, default=ai_choice, **prompt_kwargs)

    @staticmethod
    def _table_action_to_choice(action: TableAction) -> ActionChoice:
        """将 TableAction 转换为 ActionChoice"""
        from src.strategies.table_strategy import TableActionType

        _MAP = {
            TableActionType.NONE: "none",
            TableActionType.SIT_IN: "sit_in",
            TableActionType.SIT_OUT: "sit_out",
            TableActionType.LEAVE: "leave",
            TableActionType.ADD_CHIPS: "add_chips",
        }
        action_name = _MAP.get(action.action_type, "none")
        amount = action.amount if action.action_type == TableActionType.ADD_CHIPS else 0
        return ActionChoice(
            action=action_name,
            amount=amount,
            label=action.reasoning or action_name,
            reasoning=action.reasoning or "",
            source=f"table_strategy:{action.action_type.value}",
        )
