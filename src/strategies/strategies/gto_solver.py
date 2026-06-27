"""
GTO Solver 策略：基于预计算GTO表的查表策略

核心思路：
1. Preflop：根据位置+手牌查表，获取 raise/call/fold 概率分布
2. Postflop：根据 equity bucket + 场景(主动/面对下注/面对加注)查表
3. ActionPlan.secondary_action + secondary_probability 表达GTO混合策略
4. 表外场景 fallback 到基类 _get_balanced_plan()

数据来源：config/gto_tables.yaml
"""
from __future__ import annotations

import os
import random
from typing import Dict, List, Optional, Tuple

import yaml

from ..strategy_base import Strategy
from ..action_plan import ActionPlan, ActionType
from ..game_state import GameState
from ..utils import EquityCalculator, PreflopRangeManager, get_position_code, normalize_hand_string
from ..utils.game_utils import get_randomized_amount


# ── 数据加载 ─────────────────────────────────────────────

_GTO_TABLES: Optional[dict] = None


def _load_gto_tables() -> dict:
    """加载并缓存GTO预计算表"""
    global _GTO_TABLES
    if _GTO_TABLES is not None:
        return _GTO_TABLES

    config_path = os.path.join(os.getcwd(), "config", "gto_tables.yaml")
    if not os.path.exists(config_path):
        _GTO_TABLES = {}
        return _GTO_TABLES

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            _GTO_TABLES = yaml.safe_load(f) or {}
    except Exception:
        _GTO_TABLES = {}

    return _GTO_TABLES


# ── 位置映射工具 ──────────────────────────────────────────

def _map_pos_to_gto(pos_code: str) -> str:
    """将内部位置代码映射到GTO表的位置键"""
    mapping = {
        "UTG": "UTG", "EP": "UTG",
        "MP": "MP",
        "CO": "CO",
        "LP": "BTN", "BTN": "BTN",
        "SB": "SB",
        "BB": "BB",
    }
    return mapping.get(pos_code, "MP")


def _is_in_position(state: GameState) -> bool:
    """判断我们是否在位置上(IP)"""
    my_seat = state.my_seat_id
    dealer_seat = state.current_dealer_seat
    if my_seat is None or dealer_seat is None:
        return False
    # 简化判断：BTN/CO 对 UTG/MP = IP
    pos_code = get_position_code(state)
    return pos_code in ("BTN", "CO", "LP")


def _facing_position_key(state: GameState) -> str:
    """判断对手开池的位置（用于 vs_open 查表）"""
    # 找最近一个加注的对手的位置
    pos_code = get_position_code(state)
    # 如果无法精确判断对手位置，用通用映射
    # 简化：根据自己位置推断
    if pos_code in ("BB",):
        # BB面对的开池，看pot大小推断
        pot = state.pot
        to_call = state.to_call
        if to_call <= 2:
            return "facing_SB"
        # 根据底池大小粗判
        open_size = to_call
        bb = state.big_blind if hasattr(state, 'big_blind') and state.big_blind > 0 else 2
        open_bb = open_size / bb
        if open_bb <= 3:
            return "facing_BTN"
        elif open_bb <= 4:
            return "facing_CO"
        else:
            return "facing_UTG"
    return "facing_CO"  # 默认


def _equity_to_bucket(equity: float) -> str:
    """将 equity 映射到 GTO 表的 bucket 名"""
    if equity >= 0.80:
        return "monster"
    if equity >= 0.65:
        return "strong"
    if equity >= 0.50:
        return "medium"
    if equity >= 0.35:
        return "weak"
    return "air"


def _detect_draw_type(state: GameState) -> Optional[str]:
    """检测当前是否有听牌，返回听牌类型"""
    if not state.hand_strength:
        return None
    draws = state.hand_strength.get("draws", {})
    if draws.get("flush_draw"):
        street = "flop" if len(state.community_cards) <= 3 else "turn"
        return f"flush_draw_{street}"
    if draws.get("oesd"):
        return "oesd_flop"
    if draws.get("gutshot"):
        return "gutshot_flop"
    return None


# ── 策略主类 ──────────────────────────────────────────────

class GtoSolverStrategy(Strategy):
    """
    GTO查表策略

    基于预计算GTO表做决策，核心差异：
    - Preflop：概率化的 raise/call/fold 混合策略（而非确定性分层）
    - Postflop：基于 equity bucket 的行动频率分布
    - ActionPlan.secondary_action 表达GTO混合策略
    """

    strategy_name = "gto_solver"

    def __init__(self, thinking_timeout: float = 2.0):
        super().__init__(thinking_timeout)
        self._gto_tables = _load_gto_tables()

    # ── 主入口 ─────────────────────────────────────────

    def make_decision(self, state: GameState) -> ActionPlan:
        if not state.hole_cards or len(state.hole_cards) < 2:
            plan = ActionPlan(primary_action=ActionType.CHECK, reasoning="等待发牌")
            plan.strategy_name = self.strategy_name
            return plan

        hand_str = normalize_hand_string(state.hole_cards)
        self._last_hand_str = hand_str
        self._last_equity = 0.0

        if not state.community_cards:
            plan = self._preflop_decision(state, hand_str)
        else:
            plan = self._postflop_decision(state, hand_str)

        plan.strategy_name = self.strategy_name
        plan.my_equity = self._last_equity
        return plan

    # ── Preflop 决策 ──────────────────────────────────

    def _preflop_decision(self, state: GameState, hand_str: str) -> ActionPlan:
        pos_code = get_position_code(state)
        gto_pos = _map_pos_to_gto(pos_code)

        # BB 特殊处理：check选项
        if pos_code == "BB" and state.to_call <= 0:
            return ActionPlan(ActionType.CHECK, reasoning=f"BB盲注保护 ({hand_str})")

        # 场景判断：RFI vs 面对开池
        if state.to_call <= 0:
            # 无人加注 → RFI 策略
            return self._preflop_rfi(state, hand_str, gto_pos)
        else:
            # 面对加注 → vs_open 策略
            return self._preflop_vs_open(state, hand_str, pos_code)

    def _preflop_rfi(self, state: GameState, hand_str: str, gto_pos: str) -> ActionPlan:
        """翻前主动开池(RFI)查表决策"""
        rfi_table = self._gto_tables.get("preflop_rfi", {})
        pos_table = rfi_table.get(gto_pos, {})

        if hand_str not in pos_table:
            # 表外手牌：根据手牌等级做 RFI 决策（RFI 只能 raise 或 fold，不 call）
            return self._rfi_fallback(state, hand_str, gto_pos)

        probs = pos_table[hand_str]
        raise_prob, call_prob, fold_prob, raise_size_bb = probs

        bb = state.big_blind if hasattr(state, 'big_blind') and state.big_blind > 0 else 2
        pot = state.pot if state.pot > 0 else bb * 3  # 默认底池 = SB+BB
        raise_amount = int(raise_size_bb * bb)

        # 根据概率分布构建 ActionPlan（GTO混合策略）
        return self._build_mixed_action_plan(
            raise_prob=raise_prob,
            call_prob=call_prob,
            fold_prob=fold_prob,
            raise_amount=raise_amount,
            to_call=state.to_call,
            pot=pot,
            reasoning=f"RFI {gto_pos} ({hand_str}) R:{raise_prob:.0%}/C:{call_prob:.0%}/F:{fold_prob:.0%}"
        )

    def _rfi_fallback(self, state: GameState, hand_str: str, gto_pos: str) -> ActionPlan:
        """RFI 表外手牌的 fallback：根据手牌等级和位置决定 raise 或 fold（RFI 不 call）"""
        tier = self.range_mgr.get_hand_tier(hand_str)
        bb = state.big_blind if hasattr(state, 'big_blind') and state.big_blind > 0 else 2
        pot = state.pot if state.pot > 0 else bb * 3

        if tier == 1:
            # 顶级强牌：总是开池
            raise_amount = int(pot * 0.75)
            return self._build_mixed_action_plan(
                raise_prob=0.9, call_prob=0.0, fold_prob=0.1,
                raise_amount=raise_amount, to_call=state.to_call,
                pot=pot, reasoning=f"RFI {gto_pos} 强牌开池 ({hand_str})"
            )
        elif tier == 2:
            # 强牌：高频开池
            raise_amount = int(pot * 0.66)
            return self._build_mixed_action_plan(
                raise_prob=0.7, call_prob=0.0, fold_prob=0.3,
                raise_amount=raise_amount, to_call=state.to_call,
                pot=pot, reasoning=f"RFI {gto_pos} 较强牌开池 ({hand_str})"
            )
        elif tier == 3:
            # 中等牌：位置好则混合开池，否则弃牌
            if gto_pos in ("BTN", "CO", "SB"):
                raise_amount = int(pot * 0.5)
                return self._build_mixed_action_plan(
                    raise_prob=0.45, call_prob=0.0, fold_prob=0.55,
                    raise_amount=raise_amount, to_call=state.to_call,
                    pot=pot, reasoning=f"RFI {gto_pos} 位置开池 ({hand_str})"
                )
            return ActionPlan(ActionType.FOLD, reasoning=f"RFI {gto_pos} 弃牌 ({hand_str})")
        else:
            # 弱牌：弃牌
            return ActionPlan(ActionType.FOLD, reasoning=f"RFI {gto_pos} 弃牌 ({hand_str})")

    def _preflop_vs_open(self, state: GameState, hand_str: str, pos_code: str) -> ActionPlan:
        """翻前面对开池(vs open)查表决策"""
        vs_table = self._gto_tables.get("preflop_vs_open", {})

        # 确定面对的位置
        facing_key = _facing_position_key(state)
        facing_pos_table = vs_table.get(facing_key, {})

        # 判断IP/OOP
        if pos_code == "BB":
            pos_type = "BB"
        elif _is_in_position(state):
            pos_type = "IP"
        else:
            pos_type = "BB"  # OOP默认用BB表（最接近的OOP场景）

        pos_table = facing_pos_table.get(pos_type, {})

        if hand_str not in pos_table:
            # BB防守：检查赔率后决定
            if pos_code == "BB":
                return self._bb_defense_decision(state, hand_str)
            return self._get_balanced_plan(state)

        probs = pos_table[hand_str]
        three_bet_prob, call_prob, fold_prob, three_bet_size_x = probs

        # 3bet尺度 = 对手open * three_bet_size_x
        open_amount = state.to_call
        three_bet_amount = int(open_amount * three_bet_size_x)

        return self._build_mixed_action_plan(
            raise_prob=three_bet_prob,
            call_prob=call_prob,
            fold_prob=fold_prob,
            raise_amount=three_bet_amount,
            to_call=state.to_call,
            pot=state.pot,
            reasoning=f"vs_open {facing_key} {pos_type} ({hand_str}) 3b:{three_bet_prob:.0%}/C:{call_prob:.0%}/F:{fold_prob:.0%}"
        )

    def _bb_defense_decision(self, state: GameState, hand_str: str) -> ActionPlan:
        """BB防守策略：基于赔率的宽跟注"""
        bb_defense = self._gto_tables.get("bb_defense", {})
        facing_key = _facing_position_key(state)
        defense_config = bb_defense.get(facing_key, {"min_call_equity": 0.30, "defense_freq": 0.50})

        min_call_equity = defense_config.get("min_call_equity", 0.30)

        # 计算底池赔率
        to_call = state.to_call
        pot = state.pot
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0

        # 估算胜率（BB防守时用简化估算）
        equity = self.equity_calc._estimate_preflop_equity(state.hole_cards)
        tier = self.range_mgr.get_hand_tier(hand_str)

        # 强牌：3bet或跟注
        if tier <= 2:
            if equity > 0.60:
                return ActionPlan(
                    ActionType.RAISE,
                    primary_amount=get_randomized_amount(int(to_call * 3)),
                    secondary_action=ActionType.CALL,
                    secondary_probability=0.3,
                    reasoning=f"BB防守3bet ({hand_str})"
                )
            return ActionPlan(ActionType.CALL, reasoning=f"BB强牌跟注 ({hand_str})")

        # 中等牌：赔率合适就跟注
        if equity >= min_call_equity and pot_odds < equity + 0.05:
            return ActionPlan(
                ActionType.CALL,
                limit_amount=int(pot * 0.25),
                fallback_action=ActionType.FOLD,
                reasoning=f"BB赔率跟注 ({hand_str}) Eq:{equity:.0%}"
            )

        # 弱牌：弃牌
        return ActionPlan(
            ActionType.CHECK,
            fallback_action=ActionType.FOLD,
            limit_amount=0,
            reasoning=f"BB弃牌 ({hand_str})"
        )

    # ── Postflop 决策 ─────────────────────────────────

    def _postflop_decision(self, state: GameState, hand_str: str) -> ActionPlan:
        """翻后基于 equity bucket 的查表决策"""
        # 1. 计算equity
        num_opponents = sum(1 for p in state.players.values() if p.is_active and p.status != "folded")
        if num_opponents > 0:
            num_opponents -= 1
        if num_opponents < 1:
            num_opponents = 1

        equity = self.equity_calc.calculate_equity(state.hole_cards, state.community_cards, num_opponents)
        self._last_equity = equity
        state.hand_strength = self.equity_calc.get_hand_strength(state.hole_cards, state.community_cards)

        # 2. 检查听牌特殊场景
        draw_type = _detect_draw_type(state)
        if draw_type and equity < 0.50:
            draw_plan = self._draw_decision(state, hand_str, draw_type, equity)
            if draw_plan:
                return draw_plan

        # 3. 确定场景
        is_multi_way = num_opponents > 1
        street = "flop" if len(state.community_cards) <= 3 else ("turn" if len(state.community_cards) == 4 else "river")

        # 4. 查表
        bucket = _equity_to_bucket(equity)
        postflop_table = self._gto_tables.get("postflop", {})

        # 选择场景表
        if street == "flop":
            scenario_key = "flop_multi_way" if is_multi_way else "flop_heads_up"
        elif street == "turn":
            scenario_key = "turn_heads_up"
        else:
            scenario_key = "river_heads_up"

        scenario_table = postflop_table.get(scenario_key, {})
        bucket_data = scenario_table.get(bucket, {})

        if not bucket_data:
            return self._get_balanced_plan(state)

        # 5. 判断面对什么行动
        to_call = state.to_call
        pot = state.pot

        if to_call <= 0:
            # 主动下注场景
            action_key = "bet_first"
        else:
            # 判断是面对下注还是加注（简化：如果to_call > pot*0.5视为大注/加注）
            if to_call > pot * 0.5:
                action_key = "facing_raise"
            else:
                action_key = "facing_bet"

        action_probs = bucket_data.get(action_key)
        if not action_probs:
            # fallback到facing_bet
            action_key = "facing_bet" if to_call > 0 else "bet_first"
            action_probs = bucket_data.get(action_key)
            if not action_probs:
                return self._get_balanced_plan(state)

        raise_prob, call_prob, fold_prob, raise_size_pot_ratio = action_probs

        # 6. SPR + 位置调整
        raise_prob, call_prob, fold_prob, raise_size_pot_ratio = self._apply_adjustments(
            state, raise_prob, call_prob, fold_prob, raise_size_pot_ratio
        )

        # 7. 计算加注金额
        raise_amount = int(pot * raise_size_pot_ratio) if pot > 0 else state.min_raise

        # 8. 构建混合策略
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0
        ev_result = self.equity_calc.calculate_ev(equity, pot, to_call, raise_amount, 0.0)

        return self._build_mixed_action_plan(
            raise_prob=raise_prob,
            call_prob=call_prob,
            fold_prob=fold_prob,
            raise_amount=raise_amount,
            to_call=to_call,
            pot=pot,
            reasoning=f"{street} {bucket} ({hand_str}) Eq:{equity:.0%} PO:{pot_odds:.0%} R:{raise_prob:.0%}/C:{call_prob:.0%}/F:{fold_prob:.0%}"
        )

    def _draw_decision(self, state: GameState, hand_str: str, draw_type: str, equity: float) -> Optional[ActionPlan]:
        """听牌半诈唬查表决策"""
        draws_table = self._gto_tables.get("postflop_special", {}).get("draws", {})
        draw_data = draws_table.get(draw_type)
        if not draw_data:
            return None

        to_call = state.to_call
        pot = state.pot

        if to_call <= 0:
            action_key = "bet_first"
        else:
            action_key = "facing_bet"

        action_probs = draw_data.get(action_key)
        if not action_probs:
            return None

        raise_prob, call_prob, fold_prob, raise_size_pot_ratio = action_probs
        raise_amount = int(pot * raise_size_pot_ratio) if pot > 0 else state.min_raise

        return self._build_mixed_action_plan(
            raise_prob=raise_prob,
            call_prob=call_prob,
            fold_prob=fold_prob,
            raise_amount=raise_amount,
            to_call=to_call,
            pot=pot,
            reasoning=f"draw {draw_type} ({hand_str}) Eq:{equity:.0%} 半诈唬"
        )

    # ── 调整系数 ──────────────────────────────────────

    def _apply_adjustments(
        self, state: GameState,
        raise_prob: float, call_prob: float, fold_prob: float,
        raise_size_ratio: float
    ) -> Tuple[float, float, float, float]:
        """应用 SPR + 位置 + 对手类型调整"""
        special = self._gto_tables.get("postflop_special", {})

        # SPR 调整
        effective_stack = state.total_chips
        pot = state.pot if state.pot > 0 else 1
        spr = effective_stack / pot

        if spr < 2:
            spr_key = "low_spr"
        elif spr <= 6:
            spr_key = "mid_spr"
        else:
            spr_key = "high_spr"

        spr_adj = special.get("spr_adjustment", {}).get(spr_key, {})
        bluff_mult = spr_adj.get("bluff_multiplier", 1.0)
        value_mult = spr_adj.get("value_bet_multiplier", 1.0)

        # 位置调整
        if _is_in_position(state):
            pos_adj = special.get("position_adjustment", {}).get("in_position", {})
        else:
            pos_adj = special.get("position_adjustment", {}).get("out_of_position", {})

        bluff_mult *= pos_adj.get("bluff_multiplier", 1.0)
        value_mult *= pos_adj.get("value_bet_multiplier", 1.0)
        size_mult = pos_adj.get("bet_size_multiplier", 1.0)

        # 应用调整：raise包含价值加注和bluff，fold是bluff的替代
        # 价值加注部分按value_mult调整，bluff部分按bluff_mult调整
        # 简化处理：raise_prob整体调整
        # 如果equity高（价值牌），用value_mult；equity低（bluff），用bluff_mult
        bucket = _equity_to_bucket(self._last_equity)
        if bucket in ("monster", "strong"):
            raise_prob *= value_mult
        else:
            raise_prob *= bluff_mult

        # 尺度调整
        raise_size_ratio *= size_mult

        # 重新归一化
        total = raise_prob + call_prob + fold_prob
        if total > 0:
            raise_prob /= total
            call_prob /= total
            fold_prob /= total

        return raise_prob, call_prob, fold_prob, raise_size_ratio

    # ── 混合策略构建 ──────────────────────────────────

    def _build_mixed_action_plan(
        self,
        raise_prob: float,
        call_prob: float,
        fold_prob: float,
        raise_amount: int,
        to_call: int,
        pot: int,
        reasoning: str
    ) -> ActionPlan:
        """
        根据GTO概率分布构建ActionPlan

        核心逻辑：
        - 选择概率最高的行动作为 primary_action
        - 概率次高的作为 secondary_action（GTO混合策略）
        - secondary_probability = 次高/最高 的相对概率
        """
        # 确保概率归一化
        total = raise_prob + call_prob + fold_prob
        if total <= 0:
            return ActionPlan(ActionType.CHECK, reasoning=reasoning)

        raise_prob /= total
        call_prob /= total
        fold_prob /= total

        # 按概率排序
        actions = [
            (ActionType.RAISE, raise_amount, raise_prob),
            (ActionType.CALL if to_call > 0 else ActionType.CHECK, to_call, call_prob),
            (ActionType.FOLD if to_call > 0 else ActionType.CHECK, 0, fold_prob),
        ]
        actions.sort(key=lambda x: x[2], reverse=True)

        primary_action, primary_amount, primary_prob = actions[0]
        secondary_action, secondary_amount, secondary_prob = actions[1]

        # primary_amount 修正
        if primary_action == ActionType.RAISE:
            primary_amount = max(primary_amount, raise_amount)
            primary_amount = get_randomized_amount(primary_amount)
        elif primary_action == ActionType.CALL:
            primary_amount = to_call

        # 构建ActionPlan
        plan = ActionPlan(
            primary_action=primary_action,
            primary_amount=primary_amount,
        )

        # GTO混合策略：如果有次高概率行动且概率 > 0
        if secondary_prob > 0.05 and secondary_action != primary_action:
            plan.secondary_action = secondary_action
            plan.secondary_amount = secondary_amount if secondary_action == ActionType.RAISE else 0
            # secondary_probability = 在选择非primary行动时的条件概率
            # 即：P(secondary | not primary) = secondary_prob / (1 - primary_prob)
            if primary_prob < 1.0:
                plan.secondary_probability = min(1.0, secondary_prob / (1.0 - primary_prob))
            else:
                plan.secondary_probability = 0.0

        # limit_amount 和 fallback
        if primary_action == ActionType.RAISE:
            plan.limit_amount = 999999
        elif primary_action == ActionType.CALL:
            plan.limit_amount = max(to_call * 3, int(pot * 0.5))
            plan.fallback_action = ActionType.FOLD
        else:
            plan.limit_amount = 0
            plan.fallback_action = ActionType.FOLD

        # 计算EV和pot_odds用于reasoning
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0
        plan.pot_odds = pot_odds
        plan.reasoning = reasoning

        return plan
