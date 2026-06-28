from __future__ import annotations
import random

from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionPlan, ActionType
from src.strategies.game_state import GameState
from src.strategies.utils import (
    get_position_code,
    normalize_hand_string,
)
from src.strategies.utils.game_utils import get_randomized_amount
from src.strategies.utils.tactical_calc import TacticalCalculator
from src.strategies.player_analysis import get_player_tag
from src.utils.diagnostics import log_exception_with_traceback, safe_call

import logging
tag_logger = logging.getLogger("tag_strategy")


class TightAggressiveStrategy(Strategy):
    """
    紧凶策略 (Tight Aggressive, TAG)

    德州扑克最经典稳健的长期盈利打法。"紧"指入池范围窄，"凶"指入池后主动下注施压。

    核心特征（与现有策略的差异）：
    - 翻前严格按位置范围入池（目标 VPIP 18-22%），前位极紧、后位放宽
    - 翻后以价值下注为主：强牌才下注，中等牌控制底池，弱牌果断弃牌
    - 极少诈唬，仅在后位/单对手/干牌面低频率偶发
    - 面对强抵抗收缩范围（被加注后趋于保守，只玩真正强牌）
    - 听牌仅按直接赔率决策，不追潜在赔率（保守）
    - 3-bet/4-bet 范围收紧，只玩价值组合
    """

    strategy_name = "tag"
    strategy_version = 1

    # TAG 翻后价值下注阈值（比 Balanced 更选择性，确保下注时真有牌）
    VALUE_BET_THRESHOLD = 0.66
    # 超强牌阈值（可以大尺度或全下）
    NUTS_THRESHOLD = 0.78
    # 偶发诈唬频率
    BLUFF_FREQUENCY = 0.15

    def __init__(self, thinking_timeout: float = 2.0):
        super().__init__(thinking_timeout)

    def make_decision(self, state: GameState) -> ActionPlan:
        """TAG 决策入口：翻前紧范围 + 翻后价值导向"""
        self._last_equity = 0.0
        self._last_ev = 0.0
        if not state.hole_cards or len(state.hole_cards) < 2:
            plan = ActionPlan(primary_action=ActionType.CHECK, reasoning="等待发牌")
            plan.strategy_name = self.strategy_name
            return plan

        hand_str = normalize_hand_string(state.hole_cards)
        self._last_hand_str = hand_str
        pos_code = get_position_code(state)
        self._compute_tactical_context(state)

        if not state.community_cards:
            plan = self._create_preflop_tag_plan(state, hand_str, pos_code)
        else:
            plan = self._create_postflop_tag_plan(state, hand_str)

        plan.strategy_name = self.strategy_name
        plan.my_equity = self._last_equity
        plan.ev = self._last_ev
        return plan

    # ------------------------------------------------------------------
    # 翻前：严格位置范围 + 价值加注 + 收紧的 3-bet 防守
    # ------------------------------------------------------------------
    def _create_preflop_tag_plan(
        self, state: GameState, hand_str: str, pos_code: str
    ) -> ActionPlan:
        tier = self.range_mgr.get_hand_tier(hand_str)
        pot = state.pot if state.pot > 0 else 6
        to_call = state.to_call
        bb = state.big_blind if state.big_blind > 0 else 2

        # BB 免费看牌
        if pos_code == "BB" and to_call <= 0:
            return ActionPlan(ActionType.CHECK, reasoning=f"TAG 盲注过牌 ({hand_str})")

        # --- Tier 1: 顶级强牌 (AA/KK/QQ/JJ/AK) 永远加注 ---
        if tier == 1:
            base = int(pot * 0.75)
            adj = self._adjust_preflop_raise(base, state, tier, pos_code)
            # 面对大加注（3-bet）：TAG 只用 AA/KK 4-bet，其余跟注
            if to_call > bb * 6:
                if hand_str in ("AA", "KK"):
                    four_bet = int(to_call * 2.5)
                    return ActionPlan(
                        ActionType.RAISE,
                        primary_amount=get_randomized_amount(four_bet),
                        limit_amount=999999,
                        reasoning=f"TAG 4-bet 价值 ({hand_str})",
                    )
                if hand_str in ("QQ", "JJ", "AKs", "AKo"):
                    return ActionPlan(
                        ActionType.CALL,
                        limit_amount=bb * 15,
                        fallback_action=ActionType.FOLD,
                        reasoning=f"TAG 强牌跟注 3-bet ({hand_str})",
                    )
            return ActionPlan(
                ActionType.RAISE,
                primary_amount=get_randomized_amount(adj),
                limit_amount=999999,
                reasoning=f"TAG 价值加注 ({hand_str})",
            )

        # --- Tier 2: 强牌 (TT/99/AQ/AJ/KQ) ---
        if tier == 2:
            # 无人加注：RFI
            if to_call <= 0:
                # 前位标准尺度，后位稍大
                base = int(pot * 0.66) if pos_code in ("EP", "UTG", "MP") else int(pot * 0.75)
                adj = self._adjust_preflop_raise(base, state, tier, pos_code)
                return ActionPlan(
                    ActionType.RAISE,
                    primary_amount=get_randomized_amount(adj),
                    reasoning=f"TAG RFI 加注 ({hand_str})",
                )
            # 面对小加注：后位选择性 3-bet，其余跟注
            if to_call <= bb * 4:
                if pos_code in ("LP", "BTN", "CO") and hand_str in (
                    "TT",
                    "99",
                    "AQs",
                    "AQo",
                ):
                    three_bet = int(to_call * 3)
                    return ActionPlan(
                        ActionType.RAISE,
                        primary_amount=get_randomized_amount(three_bet),
                        limit_amount=bb * 12,
                        secondary_action=ActionType.CALL,
                        secondary_probability=0.4,
                        reasoning=f"TAG 后位 3-bet ({hand_str})",
                    )
                return ActionPlan(
                    ActionType.CALL,
                    limit_amount=bb * 8,
                    fallback_action=ActionType.FOLD,
                    reasoning=f"TAG 强牌跟注 ({hand_str})",
                )
            # 面对大加注：TAG 严格，弃牌
            return ActionPlan(
                ActionType.FOLD,
                fallback_action=ActionType.FOLD,
                reasoning=f"TAG 面对大加注弃牌 ({hand_str})",
            )

        # --- Tier 3: 中等牌 仅后位/盲注防守 ---
        if tier == 3:
            if pos_code in ("LP", "BTN", "CO"):
                if to_call <= 0:
                    base = int(pot * 0.66)
                    adj = self._adjust_preflop_raise(base, state, tier, pos_code)
                    return ActionPlan(
                        ActionType.RAISE,
                        primary_amount=get_randomized_amount(adj),
                        reasoning=f"TAG 后位偷盲 ({hand_str})",
                    )
                if to_call <= bb * 3:
                    return ActionPlan(
                        ActionType.CALL,
                        limit_amount=bb * 4,
                        fallback_action=ActionType.FOLD,
                        reasoning=f"TAG 后位跟注 ({hand_str})",
                    )
            # SB 防守（补注便宜）
            if pos_code == "SB" and to_call <= bb:
                return ActionPlan(
                    ActionType.CALL,
                    limit_amount=bb,
                    fallback_action=ActionType.FOLD,
                    reasoning=f"TAG SB 防守 ({hand_str})",
                )
            return ActionPlan(
                ActionType.FOLD,
                fallback_action=ActionType.FOLD,
                reasoning=f"TAG 中等牌弃牌 ({hand_str})",
            )

        # --- Tier 4 / 不在范围：弃牌（仅 SB 极便宜时宽防守，后位偶发偷盲） ---
        if pos_code == "SB" and to_call <= max(1, bb // 2):
            return ActionPlan(
                ActionType.CALL,
                limit_amount=bb,
                fallback_action=ActionType.FOLD,
                reasoning=f"TAG SB 极宽防守 ({hand_str})",
            )

        # 后位偶发偷盲（9 人桌偷盲价值高，频率克制）
        if (
            to_call <= 0
            and pos_code in ("BTN", "CO")
            and random.random() < 0.20
        ):
            base = int(pot * 0.75)
            adj = self._adjust_preflop_raise(base, state, tier, pos_code)
            return ActionPlan(
                ActionType.RAISE,
                primary_amount=get_randomized_amount(adj),
                reasoning=f"TAG 后位偷盲 ({hand_str})",
            )

        return ActionPlan(
            ActionType.FOLD if to_call > 0 else ActionType.CHECK,
            fallback_action=ActionType.FOLD,
            limit_amount=0,
            reasoning=f"TAG 弱牌弃牌 ({hand_str})",
        )

    # ------------------------------------------------------------------
    # 翻后：价值导向 + 底池控制 + 极少诈唬
    # ------------------------------------------------------------------
    def _get_opponent_range_model(self, state: GameState):
        """获取主要对手的范围模型，用于范围对抗 equity 计算。

        选取活跃对手中数据最充分的一个。无数据时返回 None（回退随机）。
        """
        opponents = [
            p for p in state.players.values()
            if p.is_active and p.status != "folded" and p.seat_id != state.my_seat_id
        ]
        if not opponents:
            return None
        # 优先选有 user_id 的对手
        for opp in opponents:
            uid = getattr(opp, "user_id", None)
            if uid:
                model = self.player_mgr.get_range_model(uid)
                # 检查范围是否已被实质性更新（权重总和非初始值）
                if model and model.get_active_combos_count() < 168.0:
                    return model
        return None

    def _get_hero_tightness(self) -> float:
        """评估 Hero 在对手眼中的紧凑度。

        combos 少 → Hero 被感知为紧（只玩强牌）→ 诈唬更有效
        combos 多 → Hero 被感知为松 → 诈唬效果差
        返回值约 1.0 为中性，>1 紧，<1 松。
        """
        try:
            combos = self.player_mgr.hero_perceived_range.get_active_combos_count()
            if combos <= 0:
                return 1.0
            return max(0.3, min(3.0, 169.0 / combos))
        except Exception as e:
            # 静默回退到 1.0 之前是 bug：get_active_combos_count 抛错时无法定位
            log_exception_with_traceback(
                tag_logger, e,
                "[tag] _evaluate_perceived_tightness 异常，回退到中性 1.0",
                op="hero_perceived_range.get_active_combos_count",
            )
            return 1.0

    def _create_postflop_tag_plan(
        self, state: GameState, hand_str: str
    ) -> ActionPlan:
        # ─── 顶层保护 ───
        # _create_postflop_tag_plan 内部调用了 equity/fold_equity/get_hand_strength
        # 等多个易错方法，任一抛异常都会被 cli_player 静默吞掉
        # 这里用 safe_call 包装，把所有 traceback 暴露到日志
        try:
            return self._create_postflop_tag_plan_impl(state, hand_str)
        except Exception as e:
            log_exception_with_traceback(
                tag_logger, e,
                f"[tag] _create_postflop_tag_plan 未捕获异常，回退到 fold (hand={hand_str})",
                hand=hand_str,
                street=TacticalCalculator.calc_street(state),
                pot=getattr(state, "pot", "?"),
                to_call=getattr(state, "to_call", "?"),
                my_seat_id=getattr(state, "my_seat_id", "?"),
            )
            # 兜底：返回 fold（让 cli_player 走 heuristic_default 一致路径）
            return ActionPlan(
                ActionType.FOLD,
                fallback_action=ActionType.FOLD,
                reasoning=f"TAG 异常兜底弃牌 ({hand_str})",
            )

    def _create_postflop_tag_plan_impl(
        self, state: GameState, hand_str: str
    ) -> ActionPlan:
        """_create_postflop_tag_plan 的实际实现，由外层 try/except 保护"""
        num_opponents = TacticalCalculator.calc_num_opponents(state)
        if num_opponents < 1:
            num_opponents = 1

        # 范围对抗 equity：优先用对手推断范围采样，而非随机
        # 模拟人类"对手加注→范围收紧→我的 JJ 胜率下降"的思考过程
        # ─── _get_opponent_range_model 可能抛异常 ───
        opp_range_model = safe_call(
            self._get_opponent_range_model, state,
            default=None,
            logger=tag_logger,
            op_name="_get_opponent_range_model",
            hand=hand_str,
            num_opponents=num_opponents,
        )
        if opp_range_model is not None:
            equity = self.equity_calc.calculate_equity_vs_range(
                state.hole_cards, state.community_cards,
                opp_range_model, num_opponents,
            )
        else:
            equity = self.equity_calc.calculate_equity(
                state.hole_cards, state.community_cards, num_opponents
            )
        self._last_equity = equity
        state.hand_strength = self.equity_calc.get_hand_strength(
            state.hole_cards, state.community_cards
        )

        call_amount = state.to_call
        pot = state.pot
        pot_odds = TacticalCalculator.calc_pot_odds(state)
        spr = TacticalCalculator.calc_spr(state)
        street = TacticalCalculator.calc_street(state)

        # 对手类型分析
        opponents = [
            p
            for p in state.players.values()
            if p.is_active
            and p.status != "folded"
            and p.seat_id != state.my_seat_id
        ]
        is_against_station = any(
            get_player_tag(p) == "跟注站 (Calling Station)" for p in opponents
        )
        is_against_nit = any(
            get_player_tag(p) == "紧逼 (Nit/Tight)" for p in opponents
        )
        is_against_maniac = any(
            get_player_tag(p) == "疯子 (Maniac)" for p in opponents
        )

        # 战术上下文（位置/牌面纹理，供诈唬条件使用）
        tc = state.tactical_context
        pos_code = tc.position_code if tc else get_position_code(state)
        board_texture = tc.board_texture if tc else {}
        board_wetness = board_texture.get("wetness", 0.5) if board_texture else 0.5

        # EV 计算（与 Balanced/Aggressive 保持一致，供日志/HUD 使用）
        # ─── sum(p.vpip for p in active_opps) 裸露求和可能抛异常 ───
        active_opps = [p for p in opponents if p.seat_id != state.my_seat_id]
        if active_opps:
            try:
                avg_vpip = sum(p.vpip for p in active_opps) / len(active_opps)
            except Exception as e:
                log_exception_with_traceback(
                    tag_logger, e,
                    "[tag] active_opps vpip 求和异常，回退到 0.3",
                    hand=hand_str,
                    street=street,
                )
                avg_vpip = 0.3
        else:
            avg_vpip = 0.3
        # ─── estimate_fold_equity 裸露调用可能抛异常 ───
        fold_equity = safe_call(
            self.equity_calc.estimate_fold_equity, avg_vpip, 0.0, street,
            default=0.0,
            logger=tag_logger,
            op_name="estimate_fold_equity",
            hand=hand_str, avg_vpip=avg_vpip, street=street,
        )
        planned_raise = int(pot * 0.6) if pot > 0 else state.min_raise
        ev_result = self.equity_calc.calculate_ev(
            equity=equity, pot=pot, to_call=call_amount,
            raise_amount=planned_raise, fold_equity=fold_equity,
        )
        call_ev = ev_result.get("call_ev", 0)
        self._last_ev = call_ev

        # TAG 阈值：偏保守、价值导向
        value_bet_threshold = self.VALUE_BET_THRESHOLD
        call_threshold = pot_odds + 0.08  # 比 Balanced 更紧

        # SPR 调整
        if spr < 2.0:
            call_threshold -= 0.05
            value_bet_threshold -= 0.05
        elif spr > 15.0:
            call_threshold += 0.05

        # 对手类型调整（TAG 核心：针对性价值）
        if is_against_station:
            # 跟注站用差牌跟注，放宽价值下注
            value_bet_threshold -= 0.08
        elif is_against_nit:
            # 紧逼下注是真的，收紧跟注
            call_threshold += 0.08
        elif is_against_maniac:
            # 疯子乱诈唬，放宽跟注抓诈
            call_threshold -= 0.05

        # 街道调整：越往后越保守
        if street == "river":
            value_bet_threshold += 0.03
            call_threshold += 0.03
        elif street == "flop":
            call_threshold -= 0.02  # 翻牌可以略宽看发展

        pot_odds_pct = pot_odds * 100

        # --- 1. 超强牌：大尺度价值下注，river 坚果可全下 ---
        if equity > self.NUTS_THRESHOLD:
            base = int(pot * 0.75) if is_against_station else int(pot * 0.66)
            adj = self._adjust_raise_amount(
                base,
                state,
                equity,
                is_against_nit,
                is_against_maniac,
                is_against_station,
                num_opponents,
            )
            # river 坚果 + 短中筹码：全下价值
            if street == "river" and equity > 0.92 and spr < 4:
                plan = ActionPlan(
                    ActionType.ALL_IN,
                    reasoning=f"TAG 坚果全下 ({hand_str}) Eq:{equity:.1%}",
                )
                plan.my_equity = equity
                plan.pot_odds = pot_odds
                return plan
            plan = ActionPlan(
                ActionType.RAISE,
                primary_amount=get_randomized_amount(adj),
                reasoning=f"TAG 价值下注 ({hand_str}) Eq:{equity:.1%} PO:{pot_odds_pct:.1f}%",
            )
            plan.my_equity = equity
            plan.pot_odds = pot_odds
            return plan

        # --- 2. 强牌：价值下注，但面对下注时控制底池 ---
        if equity > value_bet_threshold:
            base = int(pot * 0.66)
            adj = self._adjust_raise_amount(
                base,
                state,
                equity,
                is_against_nit,
                is_against_maniac,
                is_against_station,
                num_opponents,
            )
            if call_amount > 0:
                # 面对下注：单对手/高 equity/对跟注站 → 加注价值；其余跟注控池
                should_raise = (
                    (is_against_station and equity > value_bet_threshold + 0.05)
                    or (num_opponents == 1 and equity > value_bet_threshold + 0.03)
                    or equity > value_bet_threshold + 0.10
                )
                if should_raise:
                    plan = ActionPlan(
                        ActionType.RAISE,
                        primary_amount=get_randomized_amount(adj),
                        reasoning=f"TAG 价值加注 ({hand_str}) Eq:{equity:.1%}",
                    )
                else:
                    plan = ActionPlan(
                        ActionType.CALL,
                        limit_amount=int(pot * 0.4),
                        fallback_action=ActionType.FOLD,
                        reasoning=f"TAG 强牌跟注控池 ({hand_str}) Eq:{equity:.1%}",
                    )
            else:
                plan = ActionPlan(
                    ActionType.RAISE,
                    primary_amount=get_randomized_amount(adj),
                    reasoning=f"TAG 强牌价值 ({hand_str}) Eq:{equity:.1%}",
                )
            plan.my_equity = equity
            plan.pot_odds = pot_odds
            return plan

        # --- 3. 中等牌：底池控制（check/call 而非 bet） ---
        if equity > call_threshold:
            # 多人底池更谨慎
            if num_opponents > 2 and equity < 0.45:
                if call_amount > 0:
                    plan = ActionPlan(
                        ActionType.FOLD,
                        fallback_action=ActionType.FOLD,
                        reasoning=f"TAG 多人池中等牌弃 ({hand_str}) Eq:{equity:.1%}",
                    )
                else:
                    plan = ActionPlan(
                        ActionType.CHECK,
                        fallback_action=ActionType.FOLD,
                        reasoning=f"TAG 多人池过牌 ({hand_str})",
                    )
                plan.my_equity = equity
                plan.pot_odds = pot_odds
                return plan
            # 面对大注弃牌
            if call_amount > pot * 0.6 and equity < 0.50:
                plan = ActionPlan(
                    ActionType.FOLD,
                    fallback_action=ActionType.FOLD,
                    reasoning=f"TAG 面对大注弃牌 ({hand_str})",
                )
                plan.my_equity = equity
                plan.pot_odds = pot_odds
                return plan
            # 正常：跟注控池，不加注
            plan = ActionPlan(
                ActionType.CALL if call_amount > 0 else ActionType.CHECK,
                limit_amount=int(pot * 0.2),
                fallback_action=ActionType.FOLD,
                reasoning=f"TAG 中等牌控池 ({hand_str}) Eq:{equity:.1%} PO:{pot_odds:.1%}",
            )
            plan.my_equity = equity
            plan.pot_odds = pot_odds
            return plan

        # --- 4. 听牌：按直接赔率 + 坚果/底端区分 ---
        hs = state.hand_strength or {}
        draws = hs.get("draws", {}) if isinstance(hs, dict) else {}
        has_flush_draw = draws.get("flush_draw", False)
        has_oesd = draws.get("oesd", False)
        has_gutshot = draws.get("gutshot", False)
        is_nut_flush = draws.get("nut_flush_draw", False)
        is_low_flush = draws.get("low_flush_draw", False)

        if (has_flush_draw or has_oesd) and call_amount > 0:
            # 直接赔率判断（TAG 保守，不看潜在赔率）
            draw_equity = 0.20 if has_flush_draw else 0.17
            if has_flush_draw and has_oesd:
                draw_equity = 0.34  # combo draw
            # 坚果同花听：满额 equity（买中即坚果，可略激进）
            # 底端同花听：反向隐含赔率折扣（买中可能被更大同花压制）
            if is_low_flush and not is_nut_flush:
                draw_equity *= 0.55
            if draw_equity > pot_odds + 0.03:
                draw_label = (
                    ("NUT_FD" if is_nut_flush else ("LOW_FD" if is_low_flush else ("FD" if has_flush_draw else "")))
                    + ("OESD" if has_oesd else "")
                )
                draw_label = (
                    ("FD" if has_flush_draw else "")
                    + ("OESD" if has_oesd else "")
                )
                plan = ActionPlan(
                    ActionType.CALL,
                    limit_amount=int(pot * 0.3),
                    fallback_action=ActionType.FOLD,
                    reasoning=f"TAG 听牌赔率跟注 ({hand_str}) {draw_label}",
                )
                plan.my_equity = equity
                plan.pot_odds = pot_odds
                return plan
            plan = ActionPlan(
                ActionType.FOLD,
                fallback_action=ActionType.FOLD,
                reasoning=f"TAG 听牌赔率不足弃牌 ({hand_str})",
            )
            plan.my_equity = equity
            plan.pot_odds = pot_odds
            return plan

        if has_gutshot and call_amount == 0:
            plan = ActionPlan(
                ActionType.CHECK,
                fallback_action=ActionType.FOLD,
                reasoning=f"TAG 卡顺免费过牌 ({hand_str})",
            )
            plan.my_equity = equity
            plan.pot_odds = pot_odds
            return plan

        # --- 5. 弱牌：弃牌，极少诈唬 ---
        # TAG 唯一诈唬场景：单对手 + 翻牌 + 后位主动 + 干牌面 + 中等 SPR
        # 诈唬频率随 Hero 形象动态调整：被感知为紧→诈唬更有效（提高频率）
        hero_tightness = self._get_hero_tightness()
        dynamic_bluff_freq = self.BLUFF_FREQUENCY * hero_tightness
        if (
            call_amount == 0
            and num_opponents == 1
            and street == "flop"
            and equity < 0.30
            and spr > 6
            and pos_code in ("LP", "BTN", "CO")
            and board_wetness < 0.4
            and random.random() < dynamic_bluff_freq
        ):
            base = int(pot * 0.5)
            plan = ActionPlan(
                ActionType.RAISE,
                primary_amount=get_randomized_amount(base),
                bet_size_hint="half_pot",
                reasoning=f"TAG 偶发诈唬 ({hand_str}) Eq:{equity:.1%} 形象:{hero_tightness:.1f}",
            )
            plan.my_equity = equity
            plan.pot_odds = pot_odds
            return plan

        # 默认弃牌
        plan = ActionPlan(
            ActionType.FOLD if call_amount > 0 else ActionType.CHECK,
            fallback_action=ActionType.FOLD,
            limit_amount=0,
            reasoning=f"TAG 弱牌弃牌 ({hand_str}) Eq:{equity:.1%} PO:{pot_odds_pct:.1f}%",
        )
        plan.my_equity = equity
        plan.pot_odds = pot_odds
        return plan
