from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
import threading

from .game_state import GameState
from .action_plan import ActionPlan, ActionType
from .player_analysis import PlayerManager, get_player_tag
from .utils import EquityCalculator, PreflopRangeManager, get_position_code, normalize_hand_string
from .utils.game_utils import get_randomized_amount


class Strategy(ABC):
    """
    策略引擎基类：感知与决策分离架构
    """
    strategy_name: str = "base"

    def __init__(self, thinking_timeout: float = 10.0):
        self.thinking_timeout = thinking_timeout
        self.player_mgr = PlayerManager()
        self.equity_calc = EquityCalculator()
        self.range_mgr = PreflopRangeManager()
        self._lock = threading.Lock()
        self._last_equity = 0.0
        self._last_hand_str = ""

    def handle_event(self, event_type: str, data: dict) -> None:
        """
        感知接口：处理对局事件（如：发牌、对手动作、摊牌）
        策略子类可以在此执行预判定或更新内部状态缓存
        """
        if event_type == "action":
            # 默认同步到选手管理器
            self.player_mgr.update_opponent_range(
                data.get("user_id"), 
                data.get("action"), 
                data.get("pot_ratio", 0.0)
            )
        elif event_type == "showdown":
            self.player_mgr.record_showdown(
                data.get("user_id"), 
                data.get("hand_str"), 
                data.get("street")
            )

    @abstractmethod
    def make_decision(self, state: GameState) -> ActionPlan:
        """
        决策接口：当需要 Hero 做出动作时触发
        子类必须实现具体策略逻辑并返回 ActionPlan
        """
        pass

    def _get_balanced_plan(self, state: GameState) -> ActionPlan:
        """通用的平衡型（GTO 近似）决策生成逻辑，供各策略子类填充或作为基准"""
        self._last_equity = 0.0 # [FIX] 重置胜率缓存，防止 Preflop 显示旧数据
        if not state.hole_cards or len(state.hole_cards) < 2:
            plan = ActionPlan(primary_action=ActionType.CHECK, reasoning="等待发牌")
            plan.strategy_name = self.strategy_name
            return plan

        hand_str = normalize_hand_string(state.hole_cards)
        self._last_hand_str = hand_str
        pos_code = get_position_code(state)

        if not state.community_cards:
            plan = self._create_preflop_balanced_plan(state, hand_str, pos_code)
        else:
            plan = self._create_postflop_balanced_plan(state, hand_str)
        
        plan.strategy_name = self.strategy_name
        plan.my_equity = self._last_equity
        return plan

    def _create_preflop_balanced_plan(self, state: GameState, hand_str: str, pos_code: str) -> ActionPlan:
        if pos_code == "BB" and state.to_call <= 0:
            plan = ActionPlan(ActionType.CHECK, reasoning=f"盲注保护 ({hand_str})")
            plan.strategy_name = self.strategy_name
            return plan
        
        tier = self.range_mgr.get_hand_tier(hand_str)
        in_range = self.range_mgr.is_hand_in_range(hand_str, pos_code)
        pot = state.pot if state.pot > 0 else 6
        
        if tier == 1:
            base_amount = int(pot * 0.75)
            adjusted_amount = self._adjust_preflop_raise(base_amount, state, tier, pos_code)
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=get_randomized_amount(adjusted_amount),
                limit_amount=999999,
                reasoning=f"顶级强牌 ({hand_str})"
            )
        
        if tier == 2:
            if state.to_call <= 2 or pos_code in ["LP", "MP"]:
                base_amount = int(pot * 0.66)
                adjusted_amount = self._adjust_preflop_raise(base_amount, state, tier, pos_code)
                return ActionPlan(
                    primary_action=ActionType.RAISE if state.to_call == 0 else ActionType.CALL,
                    primary_amount=get_randomized_amount(adjusted_amount),
                    limit_amount=6,
                    reasoning=f"强牌 ({hand_str})"
                )
            return ActionPlan(ActionType.CALL, limit_amount=6, fallback_action=ActionType.FOLD, reasoning=f"强牌谨慎 ({hand_str})")
        
        if tier == 3:
            if pos_code in ["LP", "MP"] and state.to_call <= 4:
                return ActionPlan(ActionType.CALL, limit_amount=4, reasoning=f"中等牌 ({hand_str})")
            return ActionPlan(ActionType.CALL, limit_amount=3, fallback_action=ActionType.FOLD, reasoning=f"中等牌谨慎 ({hand_str})")
        
        if in_range:
            return ActionPlan(ActionType.CALL, limit_amount=5, fallback_action=ActionType.FOLD, reasoning=f"入池范围 ({hand_str})")
        
        return ActionPlan(ActionType.CHECK, fallback_action=ActionType.FOLD, limit_amount=1, reasoning=f"弱牌弃牌 ({hand_str})")

    def _get_aggressive_plan(self, state: GameState) -> ActionPlan:
        """激进型决策生成逻辑：更高频率的加注与 3-bet。"""
        self._last_equity = 0.0 # [FIX] 重置胜率缓存
        if not state.hole_cards or len(state.hole_cards) < 2:
            return ActionPlan(primary_action=ActionType.CHECK, reasoning="等待发牌")

        hand_str = normalize_hand_string(state.hole_cards)
        pos_code = get_position_code(state)

        if not state.community_cards:
            plan = self._create_preflop_aggressive_plan(state, hand_str, pos_code)
        else:
            # 翻牌后暂时复用平衡型，但可以根据需要进一步激进化
            plan = self._create_postflop_balanced_plan(state, hand_str)
        
        plan.strategy_name = self.strategy_name
        plan.my_equity = self._last_equity
        return plan

    def _create_preflop_aggressive_plan(self, state: GameState, hand_str: str, pos_code: str) -> ActionPlan:
        # [RFI 逻辑] 如果没有人加注，且在位置范围内，必须 RAISE
        in_range = self.range_mgr.is_hand_in_range(hand_str, pos_code)
        tier = self.range_mgr.get_hand_tier(hand_str)
        pot = state.pot if state.pot > 0 else 6
        to_call = state.to_call

        # 第一优先级：顶级强牌 (AA, KK, QQ, JJ, AK)
        if tier == 1:
            base_amount = int(pot * 1.0) # 尺度更大
            adjusted_amount = self._adjust_preflop_raise(base_amount, state, tier, pos_code)
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=get_randomized_amount(adjusted_amount),
                limit_amount=999999,
                reasoning=f"Aggressive: 顶级强牌挤压 ({hand_str})"
            )

        # 第二优先级：强牌 (TT, 99, AQs, AQo, AJs)
        if tier == 2:
            # 如果没人加注 -> RFI Raise
            if to_call <= 0:
                base_amount = int(pot * 0.75)
                adjusted_amount = self._adjust_preflop_raise(base_amount, state, tier, pos_code)
                return ActionPlan(ActionType.RAISE, primary_amount=get_randomized_amount(adjusted_amount), reasoning=f"Aggressive: RFI 加注 ({hand_str})")
            
            # 如果有人加注 -> 3-bet (LP/BTN) 或 跟注
            if pos_code in ["LP", "BTN", "SB"]:
                base_amount = int(to_call * 3) # 3-bet 尺度
                return ActionPlan(ActionType.RAISE, primary_amount=get_randomized_amount(base_amount), limit_amount=15, 
                                  secondary_action=ActionType.CALL, secondary_probability=0.3, reasoning=f"Aggressive: 位置挤压 3-bet ({hand_str})")
            
            return ActionPlan(ActionType.CALL, limit_amount=16, fallback_action=ActionType.FOLD, reasoning=f"Aggressive: 强牌跟注 ({hand_str})")

        # 第三优先级：中等牌及在范围内的牌
        if tier == 3 or in_range:
            # 如果没人加注 -> RFI Raise (后位) 或 Call (前位)
            if to_call <= 0:
                if pos_code in ["LP", "BTN", "CO", "SB", "BB"]:
                    base_amount = int(pot * 1.0) # 面对 Limper 尺度拉满
                    return ActionPlan(ActionType.RAISE, primary_amount=get_randomized_amount(base_amount), reasoning=f"Aggressive: 惩罚平入/抢盲 ({hand_str})")
                return ActionPlan(ActionType.CALL, limit_amount=2, reasoning=f"Aggressive: 范围入池 ({hand_str})")
            
            # 如果有人加注 -> 仅当赔率合适时跟注，不轻易弃牌
            if to_call <= 12: # 提升跟注门槛到 6BB (适应 ReplayPoker 激进环境)
                return ActionPlan(ActionType.CALL, limit_amount=12, fallback_action=ActionType.FOLD, reasoning=f"Aggressive: 范围跟注 ({hand_str})")

        # 盲注位防守
        if pos_code == "BB" and to_call > 0 and to_call <= 6:
            return ActionPlan(ActionType.CALL, limit_amount=6, fallback_action=ActionType.FOLD, reasoning=f"Aggressive: 盲注防守 ({hand_str})")

        return ActionPlan(ActionType.CHECK, fallback_action=ActionType.FOLD, limit_amount=1, reasoning=f"Aggressive: 弱牌弃牌 ({hand_str})")

    def _create_postflop_balanced_plan(self, state: GameState, hand_str: str) -> ActionPlan:
        num_opponents = sum(1 for p in state.players.values() if p.is_active and p.status != "folded")
        if num_opponents > 0: num_opponents -= 1
        if num_opponents < 1: num_opponents = 1

        equity = self.equity_calc.calculate_equity(state.hole_cards, state.community_cards, num_opponents)
        self._last_equity = equity
        state.hand_strength = self.equity_calc.get_hand_strength(state.hole_cards, state.community_cards)

        call_amount = state.to_call
        pot = state.pot
        pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0
        effective_stack = state.total_chips
        spr = effective_stack / pot if pot > 0 else 20
        
        call_threshold = pot_odds + 0.05
        raise_threshold = pot_odds + 0.20
        
        if spr < 2.0:
            call_threshold -= 0.10
            raise_threshold -= 0.15
        elif spr > 12.0:
            call_threshold += 0.08
            raise_threshold += 0.10

        opponents = [p for p in state.players.values() if p.is_active and p.status != "folded"]
        is_against_nit = any(get_player_tag(p) == "紧逼 (Nit/Tight)" for p in opponents)
        is_against_maniac = any(get_player_tag(p) == "疯子 (Maniac)" for p in opponents)
        is_against_station = any(get_player_tag(p) == "跟注站 (Calling Station)" for p in opponents)

        if is_against_nit:
            call_threshold += 0.10
            raise_threshold += 0.15
        elif is_against_maniac:
            call_threshold -= 0.05

        active_opps = [p for p in opponents if p.seat_id != state.my_seat_id]
        avg_vpip = sum(p.vpip for p in active_opps) / len(active_opps) if active_opps else 0.3
        street = "flop" if len(state.community_cards) <= 3 else ("turn" if len(state.community_cards) == 4 else "river")
        fold_equity = self.equity_calc.estimate_fold_equity(avg_vpip, 0.0, street)
        
        planned_raise = int(pot * 0.75) if pot > 0 else state.min_raise
        ev_result = self.equity_calc.calculate_ev(equity=equity, pot=pot, to_call=call_amount, raise_amount=planned_raise, fold_equity=fold_equity)
        
        opt_raise = self.equity_calc.find_optimal_raise_size(
            equity=equity, pot=pot if pot > 0 else 1,
            to_call=call_amount,
            min_raise=state.min_raise if state.min_raise > 0 else 2,
            stack=state.total_chips if state.total_chips > 0 else 999,
            base_fold_equity=fold_equity,
        )
        optimal_amount = opt_raise["optimal_amount"]
        optimal_hint   = opt_raise["bet_size_hint"]

        # 预计算 pot_odds 和 ev 用于返回
        pot_odds_pct = pot_odds * 100
        call_ev = ev_result.get("call_ev", 0)

        if equity > 0.70:
            base_amount = int(pot * 0.75)
            adjusted_amount = self._adjust_raise_amount(base_amount, state, equity, is_against_nit, is_against_maniac, is_against_station, num_opponents)
            final_amount = max(adjusted_amount, optimal_amount)
            plan = ActionPlan(ActionType.RAISE, primary_amount=get_randomized_amount(final_amount), bet_size_hint=optimal_hint, reasoning=f"超强牌 ({hand_str}) Eq:{equity:.1%} PO:{pot_odds_pct:.1f}% EV:{call_ev:.1f}")
            plan.my_equity = equity
            plan.pot_odds = pot_odds
            plan.ev = call_ev
            return plan

        if equity > raise_threshold + 0.10:
            base_amount = int(pot * 0.66)
            adjusted_amount = self._adjust_raise_amount(base_amount, state, equity, is_against_nit, is_against_maniac, is_against_station, num_opponents)
            final_amount = optimal_amount if opt_raise["optimal_ev"] > 0 else adjusted_amount
            sec_action = ActionType.CALL if state.to_call > 0 else ActionType.CHECK
            plan = ActionPlan(ActionType.RAISE, primary_amount=get_randomized_amount(final_amount), secondary_action=sec_action, secondary_probability=0.1, bet_size_hint=optimal_hint, reasoning=f"强牌 ({hand_str}) Eq:{equity:.1%} PO:{pot_odds_pct:.1f}% EV:{call_ev:.1f}")
            plan.my_equity = equity
            plan.pot_odds = pot_odds
            plan.ev = call_ev
            return plan

        if equity > call_threshold or call_ev > 0:
            if call_ev <= 0 and equity < call_threshold + 0.05:
                plan = ActionPlan(ActionType.CHECK, fallback_action=ActionType.FOLD, limit_amount=0, reasoning=f"EV为负弃牌 ({hand_str}) EV:{call_ev:.2f}")
                plan.my_equity = equity
                plan.pot_odds = pot_odds
                plan.ev = call_ev
                return plan
            if is_against_station and equity < 0.40:
                plan = ActionPlan(ActionType.CHECK, fallback_action=ActionType.FOLD, limit_amount=0, reasoning=f"对抗跟注站弃牌 ({hand_str})")
                plan.my_equity = equity
                plan.pot_odds = pot_odds
                plan.ev = call_ev
                return plan
            # [IMPROVE] 多人底池决策：综合考虑胜率、赔率和期望收益
            if num_opponents > 2 and equity < 0.35:
                # 计算底池赔率
                pot_odds_ratio = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 1.0
                # 期望收益 = 胜率 * (底池 + 跟注额) - 跟注额
                expected_value = equity * (pot + call_amount) - call_amount
                # 如果赔率低且期望收益为负，才弃牌
                if pot_odds_ratio > equity + 0.05 and expected_value < -call_amount * 0.1:
                    reason = f"多人底池弱牌弃牌 ({hand_str}) Eq:{equity:.1%} PO:{pot_odds_ratio:.1%} EV:{expected_value:.1f}"
                    plan = ActionPlan(ActionType.CHECK, fallback_action=ActionType.FOLD, limit_amount=0, reasoning=reason)
                    plan.my_equity = equity
                    plan.pot_odds = pot_odds_ratio
                    plan.ev = expected_value
                    return plan
            if call_amount > pot * 0.5 and equity < 0.40:
                plan = ActionPlan(ActionType.CHECK, fallback_action=ActionType.FOLD, limit_amount=0, reasoning=f"大注弃牌 ({hand_str})")
                plan.my_equity = equity
                plan.pot_odds = pot_odds
                plan.ev = call_ev
                return plan
            reason = f"边缘牌跟注 ({hand_str}) Eq:{equity:.1%} PO:{pot_odds:.1%} EV:{call_ev:.1f}"
            plan = ActionPlan(ActionType.CALL, limit_amount=int(pot * 0.25), fallback_action=ActionType.FOLD, reasoning=reason)
            plan.my_equity = equity
            plan.pot_odds = pot_odds
            plan.ev = call_ev
            return plan

        plan = ActionPlan(ActionType.FOLD if call_amount > 0 else ActionType.CHECK, fallback_action=ActionType.FOLD, limit_amount=0, reasoning=f"弱牌弃牌 ({hand_str}) Eq:{equity:.1%} PO:{pot_odds_pct:.1f}%")
        plan.my_equity = equity
        plan.pot_odds = pot_odds
        plan.ev = call_ev
        return plan

    def _adjust_preflop_raise(self, base_amount: int, state: GameState, hand_tier: int,
                               pos_code: str) -> int:
        """调整翻牌前加注金额"""
        adjusted = base_amount
        if hand_tier == 1: adjusted = int(adjusted * 1.2)
        elif hand_tier == 2: adjusted = int(adjusted * 1.0)
        else: adjusted = int(adjusted * 0.8)

        if pos_code in ["EP", "UTG"]: adjusted = int(adjusted * 0.9)
        elif pos_code in ["LP", "BTN", "CO"]: adjusted = int(adjusted * 1.1)

        bb = state.big_blind if hasattr(state, 'big_blind') and state.big_blind > 0 else 2
        min_raise = state.min_raise if state.min_raise > 0 else bb * 2
        return max(adjusted, min_raise)

    def _adjust_raise_amount(self, base_amount: int, state: GameState, equity: float, 
                             is_against_nit: bool, is_against_maniac: bool, 
                             is_against_station: bool, num_opponents: int) -> int:
        adjusted = base_amount
        if is_against_nit: adjusted = int(adjusted * 1.3)
        elif is_against_maniac: adjusted = int(adjusted * 0.8)
        elif is_against_station: adjusted = int(adjusted * 1.2)
        
        effective_stack = state.total_chips 
        if effective_stack > 0:
            spr = effective_stack / (state.pot + 1)
            if spr < 2: adjusted = int(adjusted * 0.7)
            elif spr > 10: adjusted = int(adjusted * 1.1)
        
        if equity > 0.80: adjusted = int(adjusted * 1.2)
        elif equity < 0.55: adjusted = int(adjusted * 0.9)
        
        if num_opponents > 2: adjusted = int(adjusted * 1.3)
        elif num_opponents == 1: adjusted = int(adjusted * 0.9)
        
        min_raise = state.min_raise if state.min_raise > 0 else 2
        return max(adjusted, min_raise)

    def reset(self) -> None:
        """重置内部对局状态"""
        pass

    def shutdown(self) -> None:
        """清理资源"""
        pass
