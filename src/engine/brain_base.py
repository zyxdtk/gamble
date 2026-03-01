from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
import threading

from ..core.game_state import GameState
from .action_plan import ActionPlan, ActionType


class Brain(ABC):
    strategy_name: str = "base"

    def __init__(self, thinking_timeout: float = 2.0):
        self.thinking_timeout = thinking_timeout
        self.current_plan: Optional[ActionPlan] = None
        self._lock = threading.Lock()

    def create_initial_plan(self, state: GameState) -> ActionPlan:
        """创建初始计划 - 基类提供简单的check/fold实现"""
        return ActionPlan(
            primary_action=ActionType.CHECK,
            fallback_action=ActionType.FOLD,
            reasoning="Base strategy: check or fold"
        )

    @abstractmethod
    def deep_think(self, state: GameState) -> ActionPlan:
        """深度思考 - 子类必须实现具体策略，返回新的计划"""
        pass

    def receive_table_update(self, state: GameState) -> None:
        """
        接收桌面状态更新 - 当前版本不处理，由make_decision统一决策
        """
        pass

    def make_decision(self, state: GameState) -> dict:
        """做出决策 - 执行 deep_think 获取新计划"""
        with self._lock:
            try:
                # 执行深度思考获取新计划
                self.current_plan = self.deep_think(state)
            except Exception as e:
                print(f"[BRAIN ERROR] {self.strategy_name} deep_think error: {e}", flush=True)

            # 如果 deep_think 失败或返回 None，使用默认计划
            if self.current_plan is None:
                try:
                    self.current_plan = self.create_initial_plan(state)
                except Exception as e2:
                    print(f"[BRAIN ERROR] {self.strategy_name} fallback create_initial_plan error: {e2}", flush=True)
                    self.current_plan = ActionPlan(primary_action=ActionType.FOLD, reasoning="Critical Brain Failure - Folding")

            to_call = state.to_call
            pot = state.pot
            action, amount = self.current_plan.get_action_for_bet(to_call, pot)

            # 获取 equity 信息（如果策略提供了）
            my_equity = getattr(self, '_last_equity', 0.0)
            pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0.0

            return {
                "decision": {
                    "action": action.value,
                    "amount": int(amount)  # 确保金额为整数
                },
                "strategy_name": self.strategy_name,
                "is_passive": False,
                "my_action": f"{self.current_plan.reasoning} -> {action.value}",
                "plan": self.current_plan.to_dict(),
                "my_equity": my_equity,
                "pot_odds": pot_odds,
                "my_hand_strength": self.current_plan.reasoning,
                "bet_size_hint": getattr(self.current_plan, "bet_size_hint", None),
            }

    def reset(self) -> None:
        with self._lock:
            self.current_plan = None

    def shutdown(self) -> None:
        pass
