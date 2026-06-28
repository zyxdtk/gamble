from __future__ import annotations
import os
import yaml
from typing import Dict, List


class PreflopRangeManager:
    """
    翻牌前范围管理器
    提供基于位置的翻牌前手牌范围查询和分级
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ranges = None
            cls._instance._load_ranges()
        return cls._instance

    def _load_ranges(self) -> None:
        self._ranges = self._load_from_yaml()
        if not self._ranges:
            self._ranges = self._get_fallback_ranges()

    def _load_from_yaml(self) -> Dict[str, List[str]]:
        config_path = os.path.join(os.getcwd(), "config", "preflop_ranges.yaml")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    return data.get("ranges", {})
            except Exception as e:
                # 之前是 silent pass：YAML 损坏/编码错误都无法定位
                import logging
                from src.utils.diagnostics import log_exception_with_traceback
                log_exception_with_traceback(
                    logging.getLogger("preflop_range"), e,
                    f"[preflop_range] 加载 {config_path} 失败，回退到默认范围",
                    config_path=config_path,
                )
        return {}

    def _get_fallback_ranges(self) -> Dict[str, List[str]]:
        """
        获取默认的翻牌前范围
        基于标准扑克理论的范围划分
        """
        # 极早期位置 (UTG/UTG+1) - 最紧的范围
        ep_range = [
            # 口袋对
            "AA", "KK", "QQ", "JJ", "TT", "99",
            # 同花大牌
            "AKs", "AQs", "AJs", "ATs",
            "KQs", "KJs",
            "QJs",
            # 非同花大牌
            "AKo", "AQo"
        ]

        # 早期位置 (MP/MP+1)
        mp_range = ep_range + [
            # 口袋对
            "88", "77",
            # 同花
            "A9s", "A8s",
            "KTs", "QTs", "JTs", "T9s",
            # 非同花
            "AJo"
        ]

        # 中期位置 (CO/HJ)
        mp2_range = mp_range + [
            # 口袋对
            "66", "55",
            # 同花
            "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
            "K9s", "K8s", "K7s",
            "Q9s", "J9s", "98s", "87s",
            # 非同花
            "KQo", "KJo", "QJo"
        ]

        # 后期位置 (BTN) - 最宽的范围
        lp_range = mp2_range + [
            # 口袋对
            "44", "33", "22",
            # 同花
            "K6s", "K5s", "K4s", "K3s", "K2s",
            "Q8s", "Q7s", "Q6s", "Q5s",
            "J8s", "T8s", "97s", "76s", "65s", "54s",
            # 非同花
            "KTo", "QTo", "JTo",
            # 更多同花连牌
            "T7s", "96s", "86s", "75s", "64s"
        ]

        # 小盲位置 - 较宽，因为已经投入盲注
        sb_range = mp2_range + [
            "44", "33", "22",
            "K6s", "K5s", "K4s",
            "Q8s", "Q7s", "J8s", "T8s", "98s", "87s", "76s", "65s",
            "KTo", "QTo", "JTo"
        ]

        # 大盲位置 - 最宽，因为已经投入大盲，有位置劣势但赔率好
        bb_range = lp_range + [
            # 更宽的范围用于防守
            "A9o", "A8o", "A7o", "A6o", "A5o", "A4o", "A3o", "A2o",
            "K9o", "K8o", "K7o",
            "Q9o", "Q8o",
            "J9o", "T9o"
        ]

        return {
            "EP": ep_range,      # 极早期位置 (UTG)
            "MP": mp_range,      # 早期位置 (MP)
            "MP2": mp2_range,    # 中期位置 (HJ/CO)
            "LP": lp_range,      # 后期位置 (BTN)
            "SB": sb_range,      # 小盲
            "BB": bb_range,      # 大盲
            "ALL": lp_range      # 默认使用最宽范围
        }

    def get_range(self, position: str) -> List[str]:
        """获取指定位置的范围"""
        return self._ranges.get(position, self._ranges.get("ALL", []))

    def is_hand_in_range(self, hand_str: str, position: str) -> bool:
        """检查手牌是否在指定位置的范围内"""
        return hand_str in self.get_range(position)

    def get_hand_tier(self, hand_str: str) -> int:
        """
        获取手牌等级
        Tier 1: 顶级强牌 (AA, KK, QQ, JJ, AK)
        Tier 2: 强牌 (TT-99, AQ, AJ, KQ)
        Tier 3: 中等牌 (88-77, AT, KJ, QJ, JT, AJo, KQo)
        Tier 4: 弱牌 (其他)
        """
        tier1 = [
            "AA", "KK", "QQ", "JJ",
            "AKs", "AKo"
        ]

        tier2 = [
            "TT", "99",
            "AQs", "AQo",
            "AJs",
            "KQs", "KQo"
        ]

        tier3 = [
            "88", "77", "66", "55",
            "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
            "KJs", "KTs", "K9s", "K8s", "K7s",
            "QJs", "QTs", "Q9s", "Q8s",
            "JTs", "J9s", "J8s",
            "T9s", "T8s", "98s", "97s",
            "87s", "86s", "76s", "75s",
            "65s", "64s", "54s",
            "AJo", "KJo", "QJo",
            "KTo", "QTo", "JTo"
        ]

        if hand_str in tier1:
            return 1
        if hand_str in tier2:
            return 2
        if hand_str in tier3:
            return 3
        return 4

    def get_hand_strength_description(self, hand_str: str) -> str:
        """获取手牌强度描述"""
        tier = self.get_hand_tier(hand_str)
        descriptions = {
            1: "顶级强牌",
            2: "强牌",
            3: "中等牌",
            4: "弱牌"
        }
        return descriptions.get(tier, "未知")

    def can_play_from_position(self, hand_str: str, position: str, to_call: int = 0, pot: int = 0) -> dict:
        """
        综合判断某手牌是否可以在某位置玩
        返回包含建议动作的字典
        """
        in_range = self.is_hand_in_range(hand_str, position)
        tier = self.get_hand_tier(hand_str)

        result = {
            "can_play": False,
            "action": "fold",
            "reason": "",
            "tier": tier,
            "in_range": in_range
        }

        # 顶级强牌 - 任何位置都可以玩
        if tier == 1:
            result["can_play"] = True
            result["action"] = "raise"
            result["reason"] = "顶级强牌，任何位置都玩"
            return result

        # 强牌
        if tier == 2:
            result["can_play"] = True
            if to_call == 0:
                result["action"] = "raise"
                result["reason"] = "强牌，无人加注时加注"
            else:
                result["action"] = "call"
                result["reason"] = "强牌，有人加注时跟注"
            return result

        # 中等牌 - 只在范围内时玩
        if tier == 3 and in_range:
            result["can_play"] = True
            if to_call == 0:
                result["action"] = "raise" if position in ["LP", "SB", "BB"] else "call"
                result["reason"] = "中等牌，后位可玩"
            else:
                # 计算赔率
                pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0
                if pot_odds < 0.15:  # 赔率好
                    result["action"] = "call"
                    result["reason"] = "中等牌，赔率好可跟注"
                else:
                    result["action"] = "fold"
                    result["reason"] = "中等牌，赔率不好弃牌"
            return result

        # 弱牌或不在范围内
        if in_range:
            result["reason"] = "在范围内但牌力弱"
        else:
            result["reason"] = "不在该位置范围内"

        return result
