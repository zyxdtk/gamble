from typing import Dict, List
import math
from abc import ABC, abstractmethod

class BaseRangeModel(ABC):
    """
    范围模型基类，定义统一接口
    """
    def __init__(self):
        self.combos_169 = self._generate_169_combos()
        self.weights = {combo: 1.0 for combo in self.combos_169}

    def _generate_169_combos(self) -> List[str]:
        ranks = "AKQJT98765432"
        combos = []
        for i in range(len(ranks)):
            for j in range(i, len(ranks)):
                if i == j:
                    combos.append(ranks[i] + ranks[j])
                else:
                    combos.append(ranks[i] + ranks[j] + "s")
                    combos.append(ranks[i] + ranks[j] + "o")
        return combos

    @abstractmethod
    def update_range(self, action: str, pot_ratio: float):
        pass

    def get_active_combos_count(self) -> float:
        return sum(self.weights.values())

    def _get_static_rank(self, combo: str) -> float:
        """起手牌静态相对排名 (演示版)"""
        top_hands = ["AA", "KK", "QQ", "JJ", "AKs", "AKo", "TT", "AQs", "AQo"]
        if combo in top_hands:
            return 0.95
        if "A" in combo or "K" in combo:
            return 0.7
        if combo[0] == combo[1]: # Pairs
            return 0.6
        return 0.2


class ActionBasedRangeModel(BaseRangeModel):
    """
    基础动作驱动范围模型 (原 RangeModel)
    """
    def update_range(self, action: str, pot_ratio: float):
        for combo in self.weights:
            hand_rank = self._get_static_rank(combo)
            
            if action in ["raise", "bet"]:
                power = pot_ratio
                self.weights[combo] *= math.pow(hand_rank, power)
            elif action == "fold":
                self.weights[combo] = 0.0
            elif action == "call":
                if hand_rank > 0.9 or hand_rank < 0.3:
                    self.weights[combo] *= 0.7
                else:
                    self.weights[combo] *= 1.2
