from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import random


class ActionType(Enum):
    FOLD = "FOLD"
    CHECK = "CHECK"
    CALL = "CALL"
    RAISE = "RAISE"
    ALL_IN = "ALL_IN"


@dataclass
class ActionPlan:
    """
    行动计划：Brain 根据当前状态预设的行动方案。
    支持混合策略 (Mixed Strategy) 和 ReplayPoker 固定尺度。
    """
    primary_action: ActionType = ActionType.CHECK
    primary_amount: int = 0
    
    # 混合策略支持
    secondary_action: Optional[ActionType] = None
    secondary_amount: int = 0
    secondary_probability: float = 0.0 # 执行备选动作的概率 (0.0-1.0)
    
    # 尺度建议 (应对 ReplayPoker 按钮: "min", "half_pot", "pot", "max")
    bet_size_hint: Optional[str] = None
    
    # 安全与性能参数
    limit_amount: int = 0             # 允许执行计划动作的最大 to_call 金额 (安全阈值)
    fallback_action: ActionType = ActionType.FOLD # 超过安全阈值后的强制退守动作
    fallback_amount: int = 0
    
    # 决策元数据
    confidence: float = 1.0
    reasoning: str = "默认免费看牌"

    def get_action_for_bet(self, to_call: int, pot: int) -> tuple[ActionType, int]:
        """
        根据当前环境做出最终裁决：
        1. 安全检测
        2. 混合策略机率决策
        """
        # A. 安全检测：如果对手下注超过我们的承受上限，强制退守 (通常为 FOLD)
        if to_call > self.limit_amount:
            return self.fallback_action, self.fallback_amount

        # B. 混合策略决策：如果定义了备选动作，按概率随机挑选
        chosen_action = self.primary_action
        chosen_amount = self.primary_amount
        
        if self.secondary_action and random.random() < self.secondary_probability:
            chosen_action = self.secondary_action
            chosen_amount = self.secondary_amount

        # C. 兜底逻辑：如果计划是 CHECK 但不得不平扣（to_call > 0），
        # 除非它是备选动作或主动作已选定为 CALL/RAISE，否则降级
        if to_call > 0 and chosen_action == ActionType.CHECK:
            return self.fallback_action, self.fallback_amount

        return chosen_action, chosen_amount

    def to_dict(self) -> dict:
        return {
            "primary_action": self.primary_action.value,
            "primary_amount": self.primary_amount,
            "secondary_action": self.secondary_action.value if self.secondary_action else None,
            "secondary_amount": self.secondary_amount,
            "secondary_probability": self.secondary_probability,
            "bet_size_hint": self.bet_size_hint,
            "limit_amount": self.limit_amount,
            "fallback_action": self.fallback_action.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning
        }
