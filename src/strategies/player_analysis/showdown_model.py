import math
from typing import List, Dict
from .stats_model import StatsAwareRangeModel

class ShowdownAwareRangeModel(StatsAwareRangeModel):
    """
    摊牌感知范围模型：利用历史 Showdown 真实牌力修正预测偏差。
    """
    def __init__(self, vpip: float = 0.25, pfr: float = 0.20, historical_showdowns: List[Dict] = None):
        super().__init__(vpip, pfr)
        # 偏差系数：1.0 表示正常，>1.0 表示比预期更紧，<1.0 表示比预期更松（诈唬多）
        self.bias_factor = 1.0
        if historical_showdowns:
            self._calibrate_by_showdowns(historical_showdowns)

    def _calibrate_by_showdowns(self, showdowns: List[Dict]):
        """根据历史摊牌校准偏差因子"""
        if not showdowns:
            return
            
        total_surprise = 0.0
        for sd in showdowns:
            hand = sd["hand"]
            actual_rank = self._get_static_rank(hand)
            
            # 这里简单逻辑：如果经常展示 < 0.3 的牌力却进行了强动作，说明是个诈唬者
            # 这里的 context 目前暂未解析，简化为对所有展示牌力的平均偏差。
            # 期待平均牌力应该是 >= 0.5 (入池后的中位数)
            expected_rank = 0.5
            total_surprise += (actual_rank - expected_rank)
            
        # 综合偏差：如果平均展示牌力低于 0.5，则 bias_factor 减小
        avg_deviation = total_surprise / len(showdowns)
        # 映射逻辑：avg_deviation 在 [-0.3, 0.3] 之间变化
        # 如果对手总是展示坚果 (+0.3)，bias 提升，读牌更紧
        # 如果对手总是展示垃圾 (-0.3)，bias 降低，读牌更松
        # 优化：增强偏差影响，使其能覆盖 [0.2, 3.0]
        self.bias_factor = 1.0 + (avg_deviation * 4.0)
        self.bias_factor = max(0.1, min(5.0, self.bias_factor))

    def update_range(self, action: str, pot_ratio: float):
        """
        更新范围，并融合 VPIP 统计与 Showdown 偏差修正。
        """
        for combo in self.weights:
            hand_rank = self._get_static_rank(combo)
            
            if action in ["raise", "bet"]:
                vpip_multiplier = 0.25 / max(0.05, self.vpip)
                # 最终幂次 = 尺度 * 统计修正 * Showdown偏差修正
                # 如果 bias_factor < 1.0 (诈唬多)，则幂次降低，认为对手手里弱牌可能性更高
                power = pot_ratio * vpip_multiplier * self.bias_factor
                self.weights[combo] *= math.pow(hand_rank, power)
            elif action == "fold":
                self.weights[combo] = 0.0
            elif action == "call":
                if hand_rank > 0.9 or hand_rank < 0.3:
                    self.weights[combo] *= 0.7
                else:
                    self.weights[combo] *= 1.2
