from src.engine.brain_base import Brain
from src.engine.action_plan import ActionPlan, ActionType
from src.core.game_state import GameState
from src.engine.utils import EquityCalculator, RangeManager, get_position_code, normalize_hand_string, get_player_tag
from src.core.utils import get_randomized_amount


class GTOBrain(Brain):
    strategy_name = "gto"
    
    def __init__(self, thinking_timeout: float = 2.0):
        super().__init__(thinking_timeout)
        self.equity_calc = EquityCalculator()
        self.range_mgr = RangeManager()
        self._last_equity = 0.0
        self._last_hand_str = ""
    
    def create_initial_plan(self, state: GameState) -> ActionPlan:
        if not state.hole_cards or len(state.hole_cards) < 2:
            print("[GTO DEBUG] No hole cards, waiting", flush=True)
            return ActionPlan(
                primary_action=ActionType.CHECK,
                reasoning="等待发牌"
            )

        hand_str = normalize_hand_string(state.hole_cards)
        self._last_hand_str = hand_str
        pos_code = get_position_code(state)

        print(f"[GTO DEBUG] Hand: {hand_str}, Position: {pos_code}, to_call: {state.to_call}", flush=True)

        if not state.community_cards:
            plan = self._create_preflop_plan(state, hand_str, pos_code)
            print(f"[GTO DEBUG] Preflop result: {plan.primary_action.value}, {plan.reasoning}", flush=True)
            return plan
        else:
            plan = self._create_postflop_plan(state, hand_str)
            print(f"[GTO DEBUG] Postflop result: {plan.primary_action.value}, equity: {self._last_equity:.2f}", flush=True)
            return plan
    
    def _adjust_preflop_raise(self, base_amount: int, state: GameState, hand_tier: int,
                              pos_code: str) -> int:
        """调整翻牌前加注金额"""
        adjusted = base_amount

        # 根据手牌等级调整
        if hand_tier == 1:
            adjusted = int(adjusted * 1.2)  # 顶级牌加大
        elif hand_tier == 2:
            adjusted = int(adjusted * 1.0)  # 强牌标准
        else:
            adjusted = int(adjusted * 0.8)  # 边缘牌减小

        # 根据位置调整
        if pos_code in ["EP", "UTG"]:
            adjusted = int(adjusted * 0.9)  # 早位置减小
        elif pos_code in ["LP", "BTN", "CO"]:
            adjusted = int(adjusted * 1.1)  # 晚位置加大

        # 根据盲注级别调整
        bb = state.big_blind if hasattr(state, 'big_blind') and state.big_blind > 0 else 2
        if bb >= 5:
            adjusted = int(adjusted * 0.8)  # 高盲注减小

        # 确保不小于最小加注
        min_raise = state.min_raise if state.min_raise > 0 else bb * 2
        return max(adjusted, min_raise)

    def _create_preflop_plan(self, state: GameState, hand_str: str, pos_code: str) -> ActionPlan:
        if pos_code == "BB" and state.to_call <= 0:
            return ActionPlan(
                primary_action=ActionType.CHECK,
                reasoning=f"盲注保护 ({hand_str})"
            )
        
        tier = self.range_mgr.get_hand_tier(hand_str)
        in_range = self.range_mgr.is_hand_in_range(hand_str, pos_code)
        pot = state.pot if state.pot > 0 else 6
        
        if tier == 1:
            base_amount = int(pot * 0.75)
            adjusted_amount = self._adjust_preflop_raise(base_amount, state, tier, pos_code)
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=get_randomized_amount(adjusted_amount),
                call_range_min=0,
                call_range_max=999999999,
                reasoning=f"顶级强牌 ({hand_str})"
            )
        
        if tier == 2:
            if state.to_call <= 2 or pos_code in ["LP", "MP"]:
                base_amount = int(pot * 0.66)
                adjusted_amount = self._adjust_preflop_raise(base_amount, state, tier, pos_code)
                return ActionPlan(
                    primary_action=ActionType.RAISE if state.to_call == 0 else ActionType.CALL,
                    primary_amount=get_randomized_amount(adjusted_amount),
                    call_range_min=0,
                    call_range_max=6,
                    reasoning=f"强牌 ({hand_str})"
                )
            return ActionPlan(
                primary_action=ActionType.CALL,
                call_range_min=0,
                call_range_max=6,
                fallback_action=ActionType.FOLD,
                fold_threshold=6,
                reasoning=f"强牌谨慎 ({hand_str})"
            )
        
        if tier == 3:
            if pos_code in ["LP", "MP"] and state.to_call <= 4:
                return ActionPlan(
                    primary_action=ActionType.CALL,
                    call_range_min=0,
                    call_range_max=4,
                    reasoning=f"中等牌 ({hand_str})"
                )
            return ActionPlan(
                primary_action=ActionType.CALL,
                call_range_min=0,
                call_range_max=2,
                fallback_action=ActionType.FOLD,
                fold_threshold=3,
                reasoning=f"中等牌谨慎 ({hand_str})"
            )
        
        if in_range:
            return ActionPlan(
                primary_action=ActionType.CALL,
                call_range_min=0,
                call_range_max=4,
                fallback_action=ActionType.FOLD,
                fold_threshold=5,
                reasoning=f"入池范围 ({hand_str})"
            )
        
        return ActionPlan(
            primary_action=ActionType.CHECK,
            fallback_action=ActionType.FOLD,
            fold_threshold=1,
            reasoning=f"弱牌弃牌 ({hand_str})"
        )
    
    def _adjust_raise_amount(self, base_amount: int, state: GameState, equity: float, 
                             is_against_nit: bool, is_against_maniac: bool, 
                             is_against_station: bool, num_opponents: int) -> int:
        """根据筹码深度、对手类型等因素调整加注金额"""
        adjusted = base_amount
        
        # 根据对手类型调整
        if is_against_nit:
            # 对紧逼玩家：加大下注（他们只会用强牌跟注）
            adjusted = int(adjusted * 1.3)
        elif is_against_maniac:
            # 对疯子：减小下注（诱导诈唬）
            adjusted = int(adjusted * 0.8)
        elif is_against_station:
            # 对跟注站：加大价值下注
            adjusted = int(adjusted * 1.2)
        
        # 根据筹码深度调整（SPR - Stack to Pot Ratio）
        effective_stack = min(state.total_chips, state.max_bet) if hasattr(state, 'max_bet') else state.total_chips
        if effective_stack > 0:
            spr = effective_stack / (state.pot + 1)
            if spr < 2:  # 短筹码
                adjusted = int(adjusted * 0.7)  # 减小下注，准备全下
            elif spr > 10:  # 深筹码
                adjusted = int(adjusted * 1.1)  # 增大下注，控制底池
        
        # 根据胜率调整
        if equity > 0.80:
            adjusted = int(adjusted * 1.2)  # 超强牌加大下注
        elif equity < 0.55:
            adjusted = int(adjusted * 0.9)  # 边缘牌减小下注
        
        # 根据对手数量调整
        if num_opponents > 2:
            adjusted = int(adjusted * 1.3)  # 多人底池加大下注
        elif num_opponents == 1:
            adjusted = int(adjusted * 0.9)  # 单挑减小下注
        
        # 确保下注不小于最小加注
        min_raise = state.min_raise if state.min_raise > 0 else 2
        return max(adjusted, min_raise)

    def _create_postflop_plan(self, state: GameState, hand_str: str) -> ActionPlan:
        num_opponents = sum(1 for p in state.players.values() if p.is_active and p.status != "folded")
        if num_opponents > 0:
            num_opponents -= 1
        if num_opponents < 1:
            num_opponents = 1

        equity = self.equity_calc.calculate_equity(
            state.hole_cards,
            state.community_cards,
            num_opponents
        )
        self._last_equity = equity
        
        # 保存牌力信息到 state，供剥削策略使用
        state.hand_strength = self.equity_calc.get_hand_strength(state.hole_cards, state.community_cards)

        call_amount = state.to_call
        pot = state.pot
        pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0

        opponents = [p for p in state.players.values() if p.is_active and p.status != "folded"]
        is_against_nit = any(get_player_tag(p) == "紧逼 (Nit/Tight)" for p in opponents)
        is_against_maniac = any(get_player_tag(p) == "疯子 (Maniac)" for p in opponents)
        is_against_station = any(get_player_tag(p) == "跟注站 (Calling Station)" for p in opponents)

        # 调整阈值 - 需要比底池赔率更高的胜率才跟注（考虑隐含赔率不足）
        call_threshold = pot_odds + 0.05  # 增加 5% 安全边际
        raise_threshold = pot_odds + 0.20  # 提高加注阈值

        if is_against_nit:
            call_threshold += 0.10  # 对 Nit 更紧
            raise_threshold += 0.15
        elif is_against_maniac:
            call_threshold -= 0.05  # 对 Maniac 更松（抓诈唬）

        # ── EV 计算 ──────────────────────────────────────────────────────────────
        # 估算对手弃牌率（Fold Equity）
        avg_vpip = 0.0
        active_opps = [p for p in opponents if p.seat_id != state.my_seat_id]
        if active_opps:
            avg_vpip = sum(p.vpip for p in active_opps) / len(active_opps)
        
        street = "preflop" if not state.community_cards else (
            "flop" if len(state.community_cards) <= 3 else
            "turn" if len(state.community_cards) == 4 else "river"
        )
        fold_equity = self.equity_calc.estimate_fold_equity(avg_vpip, 0.0, street)
        
        # 计划加注金额（先用底池的 0.75 倍估算）
        planned_raise = int(pot * 0.75) if pot > 0 else state.min_raise
        ev_result = self.equity_calc.calculate_ev(
            equity=equity, pot=pot, to_call=call_amount,
            raise_amount=planned_raise, fold_equity=fold_equity
        )
        
        print(f"[GTO EV] equity={equity:.2f}, fold_eq={fold_equity:.2f} | "
              f"FOLD:{ev_result['fold_ev']} CALL:{ev_result['call_ev']} "
              f"RAISE:{ev_result['raise_ev']} → best={ev_result['best_action']}({ev_result['best_ev']})",
              flush=True)
        
        # ── 用 EV 最大化求最优加注尺度 ─────────────────────────────────────────
        opt_raise = self.equity_calc.find_optimal_raise_size(
            equity=equity, pot=pot if pot > 0 else 1,
            to_call=call_amount,
            min_raise=state.min_raise if state.min_raise > 0 else 2,
            stack=state.total_chips if state.total_chips > 0 else 999,
            base_fold_equity=fold_equity,
        )
        optimal_amount = opt_raise["optimal_amount"]
        optimal_hint   = opt_raise["bet_size_hint"]
        print(f"[GTO RAISE OPT] 最优尺度: {optimal_hint} = {optimal_amount} chips "
              f"(EV:{opt_raise['optimal_ev']}) | 各档: {opt_raise['ev_by_size']}", flush=True)
        # ─────────────────────────────────────────────────────────────────────────

        # 超强牌：大额价值下注 → 底池注
        if equity > 0.70:
            base_amount = int(pot * 0.75)
            adjusted_amount = self._adjust_raise_amount(base_amount, state, equity, 
                                                        is_against_nit, is_against_maniac, 
                                                        is_against_station, num_opponents)
            # 组合：EV 最优尺度 vs 固定乘数，取较大值（强牌要压榨）
            final_amount = max(adjusted_amount, optimal_amount)
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=get_randomized_amount(final_amount),
                bet_size_hint=optimal_hint,
                reasoning=f"超强牌 ({hand_str}) Equity:{equity:.1%} OptHint:{optimal_hint}"
            )

        # 强牌：标准价值下注 → 半池注
        if equity > raise_threshold + 0.10:
            base_amount = int(pot * 0.66)
            adjusted_amount = self._adjust_raise_amount(base_amount, state, equity, 
                                                        is_against_nit, is_against_maniac, 
                                                        is_against_station, num_opponents)
            # 强牌用 EV 最优尺度
            final_amount = optimal_amount if opt_raise["optimal_ev"] > 0 else adjusted_amount
            return ActionPlan(
                primary_action=ActionType.RAISE,
                primary_amount=get_randomized_amount(final_amount),
                call_range_min=0,
                call_range_max=int(pot * 0.3),
                bet_size_hint=optimal_hint,
                reasoning=f"强牌 ({hand_str}) Equity:{equity:.1%} OptHint:{optimal_hint}"
            )

        # 中等牌：用 EV 驱动决策（核心改进）
        if equity > call_threshold or ev_result["call_ev"] > 0:
            # 特殊情况：EV 为负，直接弃牌（即使胜率勉强够）
            if ev_result["call_ev"] <= 0 and equity < call_threshold + 0.05:
                return ActionPlan(
                    primary_action=ActionType.CHECK,
                    fallback_action=ActionType.FOLD,
                    fold_threshold=int(pot * 0.15),
                    reasoning=f"EV为负弃牌 ({hand_str}) EV:{ev_result['call_ev']}"
                )

            # 对抗跟注站且胜率低：直接弃牌
            if is_against_station and equity < 0.40:
                return ActionPlan(
                    primary_action=ActionType.CHECK,
                    fallback_action=ActionType.FOLD,
                    fold_threshold=int(pot * 0.2),
                    reasoning=f"对抗跟注站弃牌 ({hand_str})"
                )

            # 多人底池且胜率不高：弃牌
            if num_opponents > 2 and equity < 0.35:
                return ActionPlan(
                    primary_action=ActionType.CHECK,
                    fallback_action=ActionType.FOLD,
                    fold_threshold=int(pot * 0.2),
                    reasoning=f"多人底池弱牌弃牌 ({hand_str})"
                )

            # 大注且胜率一般：弃牌
            if call_amount > pot * 0.5 and equity < 0.40:
                return ActionPlan(
                    primary_action=ActionType.CHECK,
                    fallback_action=ActionType.FOLD,
                    fold_threshold=int(pot * 0.2),
                    reasoning=f"大注弃牌 ({hand_str})"
                )

            # 标准跟注
            return ActionPlan(
                primary_action=ActionType.CALL,
                call_range_min=0,
                call_range_max=int(pot * 0.25),  # 收紧跟注范围
                fallback_action=ActionType.FOLD,  # 超过范围直接弃牌
                fold_threshold=int(pot * 0.25),
                reasoning=f"边缘牌跟注 ({hand_str}) Equity: {equity:.1%}"
            )

        # 弱牌：弃牌
        return ActionPlan(
            primary_action=ActionType.CHECK,
            fallback_action=ActionType.FOLD,
            fold_threshold=int(pot * 0.2),
            reasoning=f"弱牌弃牌 ({hand_str}) Equity: {equity:.1%}"
        )
    
    def update_plan(self, state: GameState) -> ActionPlan:
        return self.create_initial_plan(state)
    
    def deep_think(self, state: GameState) -> ActionPlan:
        return self.create_initial_plan(state)
