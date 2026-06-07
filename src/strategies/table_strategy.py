"""
桌位策略 — 管理 Ring Game 中的桌位级别决策。

桌位策略负责决定何时 sit in/sit out、补筹码、止盈止损离场等，
与 HandStrategy（手牌策略：fold/check/call/raise）分离。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from src.utils.logger import bot_logger


class TableActionType(Enum):
    """桌位动作类型"""
    SIT_IN = "sit_in"
    SIT_OUT = "sit_out"
    BUYIN = "buyin"
    ADD_CHIPS = "add_chips"
    LEAVE = "leave"
    NONE = "none"


@dataclass
class TableAction:
    """桌位动作"""
    action_type: TableActionType = TableActionType.NONE
    amount: int = 0
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "amount": self.amount,
            "reasoning": self.reasoning,
        }


@dataclass
class TableState:
    """桌位状态快照"""
    my_chips: int = 0           # 桌上筹码
    my_bank: int = 0            # 银行余额（已锁定的利润）
    is_seated: bool = False     # 是否在座位上
    is_playing: bool = False    # 是否正在参与手牌
    hands_played: int = 0       # 已参与手数
    total_profit: int = 0       # 总盈亏（相对初始买入）
    current_bb: int = 2         # 当前大盲
    seat_count: int = 0         # 桌上总人数
    active_count: int = 0       # 正在参与手牌人数
    stop_loss_bb: int = 250     # 止损阈值（BB）
    take_profit_bb: int = 300   # 止盈阈值（BB）
    low_chips_bb: int = 10      # 短码补筹阈值（BB）
    max_chips_bb: int = 800     # 筹码过厚阈值（BB）

    @property
    def profit_in_bb(self) -> float:
        """盈亏以 BB 为单位"""
        return self.total_profit / self.current_bb if self.current_bb > 0 else 0.0

    @property
    def chips_in_bb(self) -> float:
        """桌上筹码以 BB 为单位"""
        return self.my_chips / self.current_bb if self.current_bb > 0 else 0.0


class TableStrategy(ABC):
    """桌位策略抽象基类"""

    strategy_name: str = "base"

    @abstractmethod
    def decide(self, state: TableState) -> TableAction:
        """根据桌位状态做出桌位级别决策"""
        pass

    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """处理桌位事件（子类可覆盖）"""
        pass


class DefaultTableStrategy(TableStrategy):
    """
    默认桌位策略：
    - 短码补筹
    - 筹码过厚 sit out（锁定利润）
    - 止损离场
    - 止盈离场
    """

    strategy_name = "default"

    def decide(self, state: TableState) -> TableAction:
        # 1. 止损检测
        if state.profit_in_bb <= -state.stop_loss_bb:
            return TableAction(
                action_type=TableActionType.LEAVE,
                reasoning=f"止损离场: 亏损 {state.profit_in_bb:.0f} BB",
            )

        # 2. 止盈检测
        if state.profit_in_bb >= state.take_profit_bb:
            return TableAction(
                action_type=TableActionType.LEAVE,
                reasoning=f"止盈离场: 盈利 {state.profit_in_bb:.0f} BB",
            )

        # 3. 短码补筹
        if state.is_playing and state.chips_in_bb < state.low_chips_bb:
            add_amount = int(100 * state.current_bb - state.my_chips)
            if add_amount > 0:
                return TableAction(
                    action_type=TableActionType.ADD_CHIPS,
                    amount=add_amount,
                    reasoning=f"短码补筹: {state.chips_in_bb:.0f} BB < {state.low_chips_bb} BB",
                )

        # 4. 筹码过厚 → sit out 锁定利润
        if state.is_playing and state.chips_in_bb > state.max_chips_bb:
            return TableAction(
                action_type=TableActionType.SIT_OUT,
                reasoning=f"筹码过厚 sit out: {state.chips_in_bb:.0f} BB > {state.max_chips_bb} BB",
            )

        # 5. sit out 状态且需要 sit in
        if state.is_seated and not state.is_playing:
            return TableAction(
                action_type=TableActionType.SIT_IN,
                reasoning="重新坐入",
            )

        return TableAction(action_type=TableActionType.NONE, reasoning="无需桌位操作")


class ConservativeTableStrategy(TableStrategy):
    """
    保守桌位策略：
    - 更紧的阈值
    - 盈利后倾向 sit out
    - 更频繁补筹（更低阈值）
    """

    strategy_name = "conservative"

    def decide(self, state: TableState) -> TableAction:
        # 保守止损：亏损 150 BB 即离场
        if state.profit_in_bb <= -150:
            return TableAction(
                action_type=TableActionType.LEAVE,
                reasoning=f"保守止损: 亏损 {state.profit_in_bb:.0f} BB",
            )

        # 保守止盈：盈利 200 BB 即离场
        if state.profit_in_bb >= 200:
            return TableAction(
                action_type=TableActionType.LEAVE,
                reasoning=f"保守止盈: 盈利 {state.profit_in_bb:.0f} BB",
            )

        # 盈利超过 100 BB 就 sit out
        if state.is_playing and state.profit_in_bb > 100:
            return TableAction(
                action_type=TableActionType.SIT_OUT,
                reasoning=f"保守锁利 sit out: 盈利 {state.profit_in_bb:.0f} BB",
            )

        # 更低的补筹阈值（15 BB）
        if state.is_playing and state.chips_in_bb < 15:
            add_amount = int(100 * state.current_bb - state.my_chips)
            if add_amount > 0:
                return TableAction(
                    action_type=TableActionType.ADD_CHIPS,
                    amount=add_amount,
                    reasoning=f"保守补筹: {state.chips_in_bb:.0f} BB",
                )

        if state.is_seated and not state.is_playing:
            return TableAction(
                action_type=TableActionType.SIT_IN,
                reasoning="重新坐入",
            )

        return TableAction(action_type=TableActionType.NONE, reasoning="无需桌位操作")


class AggressiveTableStrategy(TableStrategy):
    """
    激进桌位策略：
    - 更松的阈值
    - 频繁补筹
    - 不主动止盈
    """

    strategy_name = "aggressive"

    def decide(self, state: TableState) -> TableAction:
        # 激进止损：亏损 500 BB 才离场
        if state.profit_in_bb <= -500:
            return TableAction(
                action_type=TableActionType.LEAVE,
                reasoning=f"激进止损: 亏损 {state.profit_in_bb:.0f} BB",
            )

        # 不止盈

        # 补筹阈值更低（20 BB）
        if state.is_playing and state.chips_in_bb < 20:
            add_amount = int(100 * state.current_bb - state.my_chips)
            if add_amount > 0:
                return TableAction(
                    action_type=TableActionType.ADD_CHIPS,
                    amount=add_amount,
                    reasoning=f"激进补筹: {state.chips_in_bb:.0f} BB",
                )

        # 不 sit out（即使筹码过厚也继续打）

        if state.is_seated and not state.is_playing:
            return TableAction(
                action_type=TableActionType.SIT_IN,
                reasoning="重新坐入",
            )

        return TableAction(action_type=TableActionType.NONE, reasoning="无需桌位操作")
