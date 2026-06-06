"""ICM 锦标赛感知策略

基于独立筹码模型 (Independent Chip Model) 的锦标赛策略：
- ICM 压力计算：根据剩余人数/奖金结构调整决策阈值
- 泡沫阶段：避免边缘 all-in
- 筹码量感知：短筹紧迫、大筹施压
- 盲注升级意识：即将涨盲时短筹更急
"""

from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionPlan, ActionType
from src.strategies.game_state import GameState
from src.strategies.utils import normalize_hand_string, get_position_code


class ICMStrategy(Strategy):
    """锦标赛感知策略（ICM）"""

    strategy_name = "icm"

    def __init__(self, thinking_timeout: float = 2.0):
        super().__init__(thinking_timeout)
        # ICM 参数
        self._bubble_factor = 1.0  # 泡沫系数：>1 表示更保守
        self._players_remaining = 10
        self._prize_positions = 3  # 奖励圈人数

    def handle_event(self, event_type: str, data: dict) -> None:
        """处理事件，更新 ICM 相关状态"""
        super().handle_event(event_type, data)
        if event_type == "action":
            # 根据动作更新泡沫感知
            pass

    def make_decision(self, state: GameState) -> ActionPlan:
        """ICM 决策"""
        if not state.hole_cards or len(state.hole_cards) < 2:
            return ActionPlan(primary_action=ActionType.CHECK, reasoning="等待发牌",
                              strategy_name=self.strategy_name)

        hand_str = normalize_hand_string(state.hole_cards)
        pos_code = get_position_code(state)

        # 估算剩余人数
        active_players = sum(1 for p in state.players.values() if p.is_active)
        self._players_remaining = max(2, active_players)

        # 计算泡沫系数
        self._bubble_factor = self._calculate_bubble_factor(state)

        # 计算筹码压力
        stack_pressure = self._calculate_stack_pressure(state)

        # 翻牌前决策
        if not state.community_cards:
            return self._preflop_decision(state, hand_str, pos_code, stack_pressure)

        # 翻牌后决策
        return self._postflop_decision(state, hand_str, stack_pressure)

    def _calculate_bubble_factor(self, state: GameState) -> float:
        """
        计算泡沫系数。

        返回值:
            1.0 = 正常（远离泡沫）
            >1.0 = 保守（接近泡沫，避免边缘 all-in）
            <1.0 = 宽松（已进奖励圈，可以更激进）
        """
        remaining = self._players_remaining
        prize_spots = self._prize_positions

        # 接近泡沫（剩余人数接近奖励圈人数）
        if remaining <= prize_spots + 1 and remaining > prize_spots:
            # 在泡沫上！极度保守
            return 1.5
        elif remaining <= prize_spots + 3 and remaining > prize_spots + 1:
            # 接近泡沫
            return 1.3
        elif remaining <= prize_spots:
            # 已进奖励圈，可以更激进
            return 0.8
        elif remaining <= 5:
            return 1.1

        return 1.0

    def _calculate_stack_pressure(self, state: GameState) -> str:
        """
        评估筹码压力等级。

        返回: "deep" / "medium" / "short" / "critical"
        """
        total_chips = state.total_chips
        pot = max(state.pot, 1)
        bb = state.big_blind if hasattr(state, 'big_blind') and state.big_blind > 0 else 2

        bb_count = total_chips / bb

        if bb_count > 40:
            return "deep"
        elif bb_count > 20:
            return "medium"
        elif bb_count > 8:
            return "short"
        else:
            return "critical"

    def _preflop_decision(self, state: GameState, hand_str: str,
                          pos_code: str, stack_pressure: str) -> ActionPlan:
        """翻牌前 ICM 决策"""
        tier = self.range_mgr.get_hand_tier(hand_str)
        in_range = self.range_mgr.is_hand_in_range(hand_str, pos_code)
        pot = state.pot if state.pot > 0 else 6
        to_call = state.to_call

        # === 筹码压力 + ICM 泡沫综合决策 ===

        # 顶级强牌：无论压力如何，都应该进攻
        if tier == 1:
            base_amount = int(pot * 0.75)
            adjusted = self._adjust_for_icm(base_amount, state, stack_pressure)
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=adjusted,
                limit_amount=999999,
                reasoning=f"ICM: 顶级强牌 ({hand_str}) BF={self._bubble_factor:.1f} SP={stack_pressure}",
                strategy_name=self.strategy_name,
            )

        # 强牌
        if tier == 2:
            if to_call == 0:
                # 无人加注 -> RFI
                base_amount = int(pot * 0.66)
                if self._bubble_factor > 1.3:
                    # 泡沫期减小尺度
                    base_amount = int(pot * 0.5)
                adjusted = self._adjust_for_icm(base_amount, state, stack_pressure)
                return ActionPlan(
                    primary_action=ActionType.RAISE,
                    primary_amount=adjusted,
                    limit_amount=999999,
                    reasoning=f"ICM: 强牌RFI ({hand_str}) BF={self._bubble_factor:.1f}",
                    strategy_name=self.strategy_name,
                )
            else:
                # 有人加注
                if self._bubble_factor > 1.3:
                    # 泡沫期：只在赔率极好时跟注
                    return ActionPlan(
                        primary_action=ActionType.CALL,
                        limit_amount=6,
                        fallback_action=ActionType.FOLD,
                        reasoning=f"ICM: 泡沫期强牌谨慎 ({hand_str}) BF={self._bubble_factor:.1f}",
                        strategy_name=self.strategy_name,
                    )
                return ActionPlan(
                    primary_action=ActionType.CALL,
                    limit_amount=8,
                    fallback_action=ActionType.FOLD,
                    reasoning=f"ICM: 强牌跟注 ({hand_str})",
                    strategy_name=self.strategy_name,
                )

        # 中等牌
        if tier == 3:
            if self._bubble_factor > 1.3:
                # 泡沫期：中等牌更紧
                return ActionPlan(
                    primary_action=ActionType.CHECK,
                    fallback_action=ActionType.FOLD,
                    limit_amount=2,
                    reasoning=f"ICM: 泡沫期中等牌弃牌 ({hand_str}) BF={self._bubble_factor:.1f}",
                    strategy_name=self.strategy_name,
                )
            if pos_code in ["LP", "MP"] and to_call <= 4:
                return ActionPlan(
                    primary_action=ActionType.CALL,
                    limit_amount=4,
                    fallback_action=ActionType.FOLD,
                    reasoning=f"ICM: 中等牌位置入池 ({hand_str})",
                    strategy_name=self.strategy_name,
                )
            return ActionPlan(
                primary_action=ActionType.CHECK,
                fallback_action=ActionType.FOLD,
                limit_amount=2,
                reasoning=f"ICM: 中等牌谨慎 ({hand_str})",
                strategy_name=self.strategy_name,
            )

        # 入池范围内
        if in_range:
            if self._bubble_factor > 1.3 and stack_pressure in ("short", "critical"):
                # 泡沫期 + 短筹 = 只玩超强牌
                return ActionPlan(
                    primary_action=ActionType.CHECK,
                    fallback_action=ActionType.FOLD,
                    limit_amount=1,
                    reasoning=f"ICM: 泡沫期短筹弃牌 ({hand_str})",
                    strategy_name=self.strategy_name,
                )
            if to_call <= 3:
                return ActionPlan(
                    primary_action=ActionType.CALL,
                    limit_amount=4,
                    fallback_action=ActionType.FOLD,
                    reasoning=f"ICM: 范围入池 ({hand_str})",
                    strategy_name=self.strategy_name,
                )

        # 短筹紧迫感：即将被盲注吃光时，放宽 all-in 范围
        if stack_pressure == "critical" and self._bubble_factor <= 1.0:
            if tier >= 3 or in_range:
                return ActionPlan(
                    primary_action=ActionType.ALL_IN,
                    limit_amount=999999,
                    reasoning=f"ICM: 短筹全下 ({hand_str}) SP=critical",
                    strategy_name=self.strategy_name,
                )

        # 弱牌
        return ActionPlan(
            primary_action=ActionType.CHECK,
            fallback_action=ActionType.FOLD,
            limit_amount=1,
            reasoning=f"ICM: 弱牌弃牌 ({hand_str}) BF={self._bubble_factor:.1f}",
            strategy_name=self.strategy_name,
        )

    def _postflop_decision(self, state: GameState, hand_str: str,
                           stack_pressure: str) -> ActionPlan:
        """翻牌后 ICM 决策"""
        num_opponents = sum(1 for p in state.players.values()
                           if p.is_active and p.status != "folded" and p.seat_id != state.my_seat_id)
        num_opponents = max(1, num_opponents)

        equity = self.equity_calc.calculate_equity(
            state.hole_cards, state.community_cards, num_opponents
        )
        self._last_equity = equity

        pot = state.pot
        to_call = state.to_call
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0

        # ICM 调整阈值
        call_threshold = pot_odds + 0.05 + (self._bubble_factor - 1.0) * 0.15
        raise_threshold = pot_odds + 0.20 + (self._bubble_factor - 1.0) * 0.10

        # 短筹降低阈值（更急迫）
        if stack_pressure in ("short", "critical"):
            call_threshold -= 0.05
            raise_threshold -= 0.08

        # 超强牌
        if equity > 0.70:
            amount = int(pot * 0.75)
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=amount,
                limit_amount=999999,
                reasoning=f"ICM: 超强牌 ({hand_str}) Eq:{equity:.1%}",
                strategy_name=self.strategy_name,
            )

        # 强牌
        if equity > raise_threshold:
            amount = int(pot * 0.66)
            # 泡沫期减小尺度
            if self._bubble_factor > 1.2:
                amount = int(pot * 0.50)
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=amount,
                reasoning=f"ICM: 强牌 ({hand_str}) Eq:{equity:.1%} BF={self._bubble_factor:.1f}",
                strategy_name=self.strategy_name,
            )

        # 跟注区
        if equity > call_threshold:
            if self._bubble_factor > 1.3 and to_call > pot * 0.3:
                # 泡沫期大注：更紧
                return ActionPlan(
                    primary_action=ActionType.FOLD if to_call > 0 else ActionType.CHECK,
                    reasoning=f"ICM: 泡沫期弃牌 ({hand_str}) Eq:{equity:.1%} BF={self._bubble_factor:.1f}",
                    strategy_name=self.strategy_name,
                )
            return ActionPlan(
                primary_action=ActionType.CALL if to_call > 0 else ActionType.CHECK,
                limit_amount=int(pot * 0.3),
                fallback_action=ActionType.FOLD,
                reasoning=f"ICM: 跟注 ({hand_str}) Eq:{equity:.1%}",
                strategy_name=self.strategy_name,
            )

        # 弱牌
        return ActionPlan(
            primary_action=ActionType.FOLD if to_call > 0 else ActionType.CHECK,
            fallback_action=ActionType.FOLD,
            limit_amount=0,
            reasoning=f"ICM: 弱牌弃牌 ({hand_str}) Eq:{equity:.1%}",
            strategy_name=self.strategy_name,
        )

    def _adjust_for_icm(self, base_amount: int, state: GameState,
                         stack_pressure: str) -> int:
        """根据 ICM 压力调整加注尺度"""
        adjusted = base_amount

        if self._bubble_factor > 1.3:
            adjusted = int(adjusted * 0.7)  # 泡沫期减小
        elif self._bubble_factor < 1.0:
            adjusted = int(adjusted * 1.2)  # 已入圈加大

        if stack_pressure == "deep":
            adjusted = int(adjusted * 1.1)
        elif stack_pressure == "short":
            adjusted = int(adjusted * 0.8)
        elif stack_pressure == "critical":
            adjusted = int(adjusted * 0.6)

        min_raise = state.min_raise if state.min_raise > 0 else 2
        return max(adjusted, min_raise)
