from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class ActionType(Enum):
    FOLD = "FOLD"
    CHECK = "CHECK"
    CALL = "CALL"
    RAISE = "RAISE"
    ALL_IN = "ALL_IN"


@dataclass
class ActionPlan:
    primary_action: ActionType = ActionType.CHECK
    primary_amount: int = 0
    
    fallback_action: ActionType = ActionType.FOLD
    fallback_amount: int = 0
    
    call_range_min: int = 0
    call_range_max: int = 0  # 默认为 0，表示不主动跟注
    
    raise_range_min: int = 0
    raise_range_max: int = 999999999
    
    fold_threshold: int = 999999999
    
    confidence: float = 0.5
    reasoning: str = ""
    # 加注尺度提示：策略层向 PlayManager 指示目标加注档位
    # 可选值: "min" | "half_pot" | "pot" | "max" | None (表示使用 primary_amount 精确值)
    bet_size_hint: str | None = None
    
    def get_action_for_bet(self, to_call: int, pot: int) -> tuple[ActionType, int]:
        if to_call == 0:
            if self.primary_action in [ActionType.CHECK, ActionType.RAISE]:
                return self.primary_action, self.primary_amount
            return ActionType.CHECK, 0
        
        if to_call > self.fold_threshold:
            return ActionType.FOLD, 0
        
        if self.call_range_min <= to_call <= self.call_range_max:
            return ActionType.CALL, to_call
        
        if to_call < self.raise_range_min and self.primary_action == ActionType.RAISE:
            return ActionType.RAISE, self.primary_amount
        
        if to_call > self.raise_range_max:
            return self.fallback_action, self.fallback_amount
        
        # 兜底安全性校验：如果有下注，且主要动作为 CHECK，则强制降级到 fallback
        if to_call > 0 and self.primary_action == ActionType.CHECK:
            return self.fallback_action, self.fallback_amount

        return self.primary_action, self.primary_amount

    def to_dict(self) -> dict:
        return {
            "primary_action": self.primary_action.value,
            "primary_amount": self.primary_amount,
            "fallback_action": self.fallback_action.value,
            "fallback_amount": self.fallback_amount,
            "call_range": [self.call_range_min, self.call_range_max],
            "raise_range": [self.raise_range_min, self.raise_range_max],
            "fold_threshold": self.fold_threshold,
            "confidence": self.confidence,
            "reasoning": self.reasoning
        }
