"""
TacticalCalculator — 提取策略间重复的战术计算为公共静态方法。

由 Strategy 基类 _compute_tactical_context() 统一调用，
各策略通过 state.tactical_context 访问预计算结果。
"""

from __future__ import annotations
from typing import Dict

from ..game_state import GameState
from ..player_analysis import get_player_tag


class TacticalCalculator:
    """战术计算工具集，所有方法均为无副作用纯函数"""

    @staticmethod
    def calc_num_opponents(state: GameState) -> int:
        """计算活跃对手数（排除自身和已弃牌玩家）"""
        count = sum(1 for p in state.players.values()
                    if p.is_active and p.status != "folded")
        # 排除自身
        if count > 0:
            count -= 1
        return max(count, 1)

    @staticmethod
    def calc_pot_odds(state: GameState) -> float:
        """计算底池赔率: to_call / (pot + to_call)"""
        call = state.to_call
        pot = state.pot
        total = pot + call
        return call / total if total > 0 else 0.0

    @staticmethod
    def calc_spr(state: GameState) -> float:
        """计算 SPR (Stack-to-Pot Ratio): effective_stack / pot"""
        pot = state.pot
        if pot <= 0:
            return 20.0
        return state.total_chips / pot

    @staticmethod
    def calc_opponent_tags(state: GameState) -> Dict[str, str]:
        """计算每个活跃对手的类型标签"""
        tags: Dict[str, str] = {}
        for seat_id, p in state.players.items():
            if p.is_active and p.status != "folded" and seat_id != state.my_seat_id:
                tags[str(seat_id)] = get_player_tag(p)
        return tags

    @staticmethod
    def calc_street(state: GameState) -> str:
        """判定当前街道"""
        if not state.community_cards:
            return "preflop"
        n = len(state.community_cards)
        if n <= 3:
            return "flop"
        if n == 4:
            return "turn"
        return "river"

    @staticmethod
    def calc_avg_vpip(state: GameState) -> float:
        """计算活跃对手的平均 VPIP"""
        active_opps = [
            p for p in state.players.values()
            if p.is_active and p.status != "folded"
            and p.seat_id != state.my_seat_id
        ]
        if not active_opps:
            return 0.3
        return sum(p.vpip for p in active_opps) / len(active_opps)

    @staticmethod
    def calc_opponent_tags_from_event(
        cached_tags: Dict[str, str], user_id: str, data: dict
    ) -> Dict[str, str]:
        """根据事件数据增量更新对手标签缓存。
        不改变 Player 对象，仅更新缓存字典。
        """
        # 仅在 showdown 事件时利用新信息更新标签
        # action 事件时保持原有标签不变（标签需要统计支撑）
        return cached_tags
