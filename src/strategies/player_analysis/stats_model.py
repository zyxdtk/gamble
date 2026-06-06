import math
from .model import BaseRangeModel

class StatsAwareRangeModel(BaseRangeModel):
    """
    统计感知范围模型：结合玩家 VPIP/PFR 历史数据修正贝叶斯更新。
    """
    def __init__(self, vpip: float = 0.25, pfr: float = 0.20):
        super().__init__()
        self.vpip = vpip
        self.pfr = pfr
        # 初始权重根据 VPIP 进行预调优 (VPIP 越低，初始范围越紧)
        self._initialize_by_stats()

    def _initialize_by_stats(self):
        """根据 VPIP 修正初始权重分布"""
        for combo in self.weights:
            rank = self._get_static_rank(combo)
            # 如果 VPIP 是 10%，则只有排名前 10% 的牌保持高权重
            # 这里简单使用逻辑：如果权重排名低于 VPIP，则大幅惩罚
            # 基准：rank 0.95 (Top), rank 0.2 (Bottom)
            # 我们让权重分布向 VPIP 靠拢
            if rank < (1.0 - self.vpip):
                self.weights[combo] *= 0.1 # 预判该玩家不太可能拿这手牌入池

    def update_range(self, action: str, pot_ratio: float):
        """
        根据动作更新范围，并根据玩家类型修正收缩幅度。
        """
        for combo in self.weights:
            hand_rank = self._get_static_rank(combo)
            
            if action in ["raise", "bet"]:
                # 修正系数：Maniac (VPIP高) 的 Raise 威力较小，Nit (VPIP低) 的 Raise 威力巨大
                # 逻辑：收缩幂次由 pot_ratio * (基准VPIP / 实际VPIP) 决定
                # 假设基准 VPIP 为 0.25
                vpip_multiplier = 0.25 / max(0.05, self.vpip)
                power = pot_ratio * vpip_multiplier
                self.weights[combo] *= math.pow(hand_rank, power)
            elif action == "fold":
                self.weights[combo] = 0.0
            elif action == "call":
                # 跟注逻辑同样可以被 VPIP 修正，此处暂时保持通用
                if hand_rank > 0.9 or hand_rank < 0.3:
                    self.weights[combo] *= 0.7
                else:
                    self.weights[combo] *= 1.2
