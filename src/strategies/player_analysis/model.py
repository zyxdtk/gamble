from typing import Dict, List, Optional
import math
import random
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

    def sample_combo(self, exclude_cards: Optional[List[str]] = None) -> Optional[List[str]]:
        """按权重采样一个起手牌组合，返回具体两张牌（排除已知牌）。

        用于范围对抗 equity 计算：蒙特卡洛时用推断范围采样对手手牌，而非随机。
        返回 None 表示无可用组合（调用方应回退到随机采样）。
        """
        exclude = set(exclude_cards or [])
        valid_combos: List[tuple] = []
        valid_weights: List[float] = []

        for combo, weight in self.weights.items():
            if weight <= 0:
                continue
            cards = self._combo_to_cards(combo, exclude)
            if cards:
                valid_combos.append((combo, cards))
                valid_weights.append(weight)

        if not valid_combos:
            return None

        idx = random.choices(range(len(valid_combos)), weights=valid_weights, k=1)[0]
        return valid_combos[idx][1]

    def _combo_to_cards(self, combo: str, exclude: set) -> Optional[List[str]]:
        """将组合字符串（如 'AKs'）转为具体两张牌，排除已知牌。"""
        suits = "shdc"
        r1, r2 = combo[0], combo[1]

        if len(combo) == 2:  # 对子
            available = [s for s in suits if r1 + s not in exclude and r2 + s not in exclude]
            if len(available) < 2:
                return None
            chosen = random.sample(available, 2)
            return [r1 + chosen[0], r2 + chosen[1]]

        suited = combo[2] == "s"
        if suited:
            for s in suits:
                if r1 + s not in exclude and r2 + s not in exclude:
                    return [r1 + s, r2 + s]
            return None
        else:
            for s1 in suits:
                for s2 in suits:
                    if s1 == s2:
                        continue
                    c1, c2 = r1 + s1, r2 + s2
                    if c1 not in exclude and c2 not in exclude:
                        return [c1, c2]
            return None

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
