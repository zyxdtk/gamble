from typing import Dict, Optional, Type, List
from .database import PlayerDatabase
from .model import BaseRangeModel, ActionBasedRangeModel
from .stats_model import StatsAwareRangeModel
from .showdown_model import ShowdownAwareRangeModel

class PlayerManager:
    """对手数据融合管理器：处理当前桌子数据与全局历史数据的合并，并维护分玩家范围模型"""
    def __init__(self, db_path: str = "data/players.db"):
        self.db = PlayerDatabase(db_path)
        # 内存中维护本局的实时统计 (Key: user_id)
        self.session_stats: Dict[str, Dict] = {}
        # 维护分玩家的动态范围模型，支持多种策略
        self.opponent_ranges: Dict[str, BaseRangeModel] = {}
        # 维护 Hero 在对手眼中的感知范围模型
        self.hero_perceived_range = ActionBasedRangeModel()

    def record_hand_played(self, user_id: str, is_vpip: bool, is_pfr: bool):
        """记录一手牌的行为 (同步更新内存和持久化层)"""
        # 1. 更新本局内存统计
        if user_id not in self.session_stats:
            self.session_stats[user_id] = {"hands": 0, "vpip_count": 0, "pfr_count": 0}
        
        stats = self.session_stats[user_id]
        stats["hands"] += 1
        if is_vpip: stats["vpip_count"] += 1
        if is_pfr: stats["pfr_count"] += 1

        # 2. 更新全局持久化数据库
        self.db.update_player_stats(user_id, is_vpip, is_pfr)

    def record_showdown(self, user_id: str, hand_string: str, street: str, context: str = ""):
        """记录摊牌信息 (hand_string 需为规范化形式 e.g. 'AKo')"""
        self.db.record_showdown(user_id, hand_string, street, context)

    def get_combined_profiling(self, user_id: str) -> Dict:
        """获取全局画像数据 (由于 record_hand_played 同步更新 DB，DB 即为全局总量)"""
        history = self.db.get_player_stats(user_id)
        if not history:
            return {"vpip": 0, "pfr": 0, "hands": 0}

        total_hands = history["hands"]
        vpip = history["vpip_count"] / total_hands * 100
        pfr = history["pfr_count"] / total_hands * 100

        return {
            "vpip": round(vpip, 1),
            "pfr": round(pfr, 1),
            "hands": total_hands
        }

    def get_session_profiling(self, user_id: str) -> Dict:
        """获取仅限本桌的画像数据"""
        current = self.session_stats.get(user_id, {"hands": 0, "vpip_count": 0, "pfr_count": 0})
        total_hands = current["hands"]
        if total_hands == 0:
            return {"vpip": 0, "pfr": 0, "hands": 0}
            
        vpip = current["vpip_count"] / total_hands * 100
        pfr = current["pfr_count"] / total_hands * 100
        
        return {
            "vpip": round(vpip, 1),
            "pfr": round(pfr, 1),
            "hands": total_hands
        }

    def reset_session(self):
        """换桌或重开局时清空本局统计"""
        self.session_stats.clear()
        self.opponent_ranges.clear()
        self.hero_perceived_range = ActionBasedRangeModel()

    def get_range_model(self, user_id: str) -> BaseRangeModel:
        """获取指定玩家的范围模型 (自动根据统计与摊牌数据选择策略)"""
        if user_id not in self.opponent_ranges:
            # 获取画像和摊牌记录
            stats = self.get_combined_profiling(user_id)
            showdowns = self.db.get_recent_showdowns(user_id)
            
            vpip = stats["vpip"] / 100.0
            pfr = stats["pfr"] / 100.0
            
            if showdowns:
                # 哪怕只有一次摊牌也使用 Showdown 感知模型
                self.opponent_ranges[user_id] = ShowdownAwareRangeModel(
                    vpip=vpip, pfr=pfr, historical_showdowns=showdowns
                )
            elif stats["hands"] >= 20:
                self.opponent_ranges[user_id] = StatsAwareRangeModel(vpip=vpip, pfr=pfr)
            else:
                self.opponent_ranges[user_id] = ActionBasedRangeModel()
        return self.opponent_ranges[user_id]

    def update_opponent_range(self, user_id: str, action: str, pot_ratio: float):
        """更新特定对手的动作驱动范围"""
        model = self.get_range_model(user_id)
        model.update_range(action, pot_ratio)

    def update_hero_perceived_range(self, action: str, pot_ratio: float):
        """更新对手眼中 Hero 的感知范围"""
        self.hero_perceived_range.update_range(action, pot_ratio)
