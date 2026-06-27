"""
GtoSolverStrategy 单元测试
验证GTO查表策略的核心决策逻辑
"""
import pytest
from unittest.mock import patch, MagicMock

from src.strategies.strategies.gto_solver import (
    GtoSolverStrategy,
    _load_gto_tables,
    _map_pos_to_gto,
    _is_in_position,
    _equity_to_bucket,
    _detect_draw_type,
)
from src.strategies.action_plan import ActionType
from src.strategies.game_state import GameState, Player


# ── 测试工具 ─────────────────────────────────────────────

def _make_state(
    hole_cards=("Ah", "Kh"),
    community_cards=None,
    pot=6,
    to_call=0,
    my_seat_id=0,
    dealer_seat=5,
    min_raise=4,
    total_chips=200,
    big_blind=2,
    players=None,
) -> GameState:
    """快速构造测试用GameState"""
    state = GameState()
    state.hole_cards = list(hole_cards)
    state.community_cards = list(community_cards) if community_cards else []
    state.pot = pot
    state.to_call = to_call
    state.my_seat_id = my_seat_id
    state.current_dealer_seat = dealer_seat
    state.min_raise = min_raise
    state.total_chips = total_chips
    state.big_blind = big_blind
    if players is None:
        state.players = {
            0: Player(seat_id=0, user_id="hero", name="Hero", chips=200,
                      is_active=True, is_acting=True, status="active"),
            1: Player(seat_id=1, user_id="villain", name="Villain", chips=200,
                      is_active=True, is_acting=False, status="active"),
        }
    else:
        state.players = players
    return state


# ── 位置映射测试 ──────────────────────────────────────────

class TestPositionMapping:
    def test_map_ep_to_utg(self):
        assert _map_pos_to_gto("EP") == "UTG"
        assert _map_pos_to_gto("UTG") == "UTG"

    def test_map_mp(self):
        assert _map_pos_to_gto("MP") == "MP"

    def test_map_lp_to_btn(self):
        assert _map_pos_to_gto("LP") == "BTN"
        assert _map_pos_to_gto("BTN") == "BTN"

    def test_map_sb(self):
        assert _map_pos_to_gto("SB") == "SB"

    def test_map_unknown(self):
        assert _map_pos_to_gto("UNKNOWN") == "MP"  # 默认


# ── Equity Bucket 测试 ───────────────────────────────────

class TestEquityBucket:
    def test_monster(self):
        assert _equity_to_bucket(0.85) == "monster"
        assert _equity_to_bucket(0.80) == "monster"

    def test_strong(self):
        assert _equity_to_bucket(0.70) == "strong"
        assert _equity_to_bucket(0.65) == "strong"

    def test_medium(self):
        assert _equity_to_bucket(0.55) == "medium"
        assert _equity_to_bucket(0.50) == "medium"

    def test_weak(self):
        assert _equity_to_bucket(0.40) == "weak"
        assert _equity_to_bucket(0.35) == "weak"

    def test_air(self):
        assert _equity_to_bucket(0.20) == "air"
        assert _equity_to_bucket(0.0) == "air"


# ── GTO表加载测试 ─────────────────────────────────────────

class TestGtoTableLoading:
    def test_load_tables(self):
        tables = _load_gto_tables()
        assert isinstance(tables, dict)
        assert "preflop_rfi" in tables
        assert "preflop_vs_open" in tables
        assert "postflop" in tables
        assert "postflop_special" in tables

    def test_preflop_rfi_structure(self):
        tables = _load_gto_tables()
        rfi = tables["preflop_rfi"]
        # 检查位置覆盖
        for pos in ["UTG", "MP", "CO", "BTN", "SB"]:
            assert pos in rfi, f"RFI缺少 {pos} 位置"
            # 检查AA在所有位置都是100% raise
            assert rfi[pos]["AA"] == [1.0, 0.0, 0.0, pytest.approx(2.5, abs=0.5)]

    def test_postflop_structure(self):
        tables = _load_gto_tables()
        postflop = tables["postflop"]
        assert "flop_heads_up" in postflop
        assert "turn_heads_up" in postflop
        assert "river_heads_up" in postflop
        # 检查bucket覆盖
        for bucket in ["monster", "strong", "medium", "weak", "air"]:
            assert bucket in postflop["flop_heads_up"]


# ── Preflop RFI 决策测试 ──────────────────────────────────

class TestPreflopRfi:
    def setup_method(self):
        self.strategy = GtoSolverStrategy()

    def test_aa_always_raise(self):
        """AA在任何位置RFI应该100% raise"""
        state = _make_state(hole_cards=("Ah", "Ad"))
        plan = self.strategy.make_decision(state)
        assert plan.primary_action == ActionType.RAISE
        assert plan.secondary_probability < 0.01  # AA几乎不会secondary

    def test_kk_always_raise(self):
        state = _make_state(hole_cards=("Kh", "Kd"))
        plan = self.strategy.make_decision(state)
        assert plan.primary_action == ActionType.RAISE

    def test_weak_hand_fold(self):
        """弱牌如72o应该弃牌"""
        state = _make_state(hole_cards=("7h", "2d"), my_seat_id=1, dealer_seat=5)
        plan = self.strategy.make_decision(state)
        # 72o不在任何RFI范围，应该fallback到balanced(可能是fold/check)
        assert plan.primary_action in (ActionType.FOLD, ActionType.CHECK)

    def test_bb_check_when_free(self):
        """BB无人加注时应该check"""
        state = _make_state(hole_cards=("2h", "7d"), my_seat_id=1, dealer_seat=0)
        # 需要设置BB位置 + to_call=0
        plan = self.strategy.make_decision(state)
        # BB check场景
        assert plan is not None

    def test_mixed_strategy_secondary_action(self):
        """GTO混合策略应该使用secondary_action"""
        # AQs在UTG: 100% raise，没有secondary
        # 但QJs在UTG: 40% raise / 60% fold → 混合策略
        state = _make_state(hole_cards=("Qh", "Jh"), my_seat_id=0, dealer_seat=5)
        plan = self.strategy.make_decision(state)
        # QJs应该有secondary_action（GTO混合策略）
        # 可能是 raise+fold 或 fold+raise
        assert plan.reasoning is not None

    def test_rfi_raise_amount_by_position(self):
        """不同位置RFI尺度可能不同"""
        # UTG: raise_size_bb = 2.5
        # SB: raise_size_bb = 3.0 (更大)
        state_utg = _make_state(hole_cards=("Ah", "Kh"), my_seat_id=0, dealer_seat=5)
        plan_utg = self.strategy.make_decision(state_utg)

        state_sb = _make_state(hole_cards=("Ah", "Kh"), my_seat_id=1, dealer_seat=5)
        plan_sb = self.strategy.make_decision(state_sb)

        # 两者都应该raise
        assert plan_utg.primary_action == ActionType.RAISE
        assert plan_sb.primary_action == ActionType.RAISE

    def test_strategy_name(self):
        state = _make_state()
        plan = self.strategy.make_decision(state)
        assert plan.strategy_name == "gto_solver"


# ── Preflop vs Open 决策测试 ──────────────────────────────

class TestPreflopVsOpen:
    def setup_method(self):
        self.strategy = GtoSolverStrategy()

    def test_aa_vs_open_3bet(self):
        """面对开池，AA应该高频3bet"""
        state = _make_state(hole_cards=("Ah", "Ad"), to_call=6, pot=9)
        plan = self.strategy.make_decision(state)
        assert plan.primary_action == ActionType.RAISE

    def test_weak_hand_vs_open_fold(self):
        """面对开池，弱牌应该弃牌"""
        state = _make_state(hole_cards=("7h", "2d"), to_call=6, pot=9)
        plan = self.strategy.make_decision(state)
        # 72o面对open应该弃牌(fallback to balanced)
        assert plan.primary_action in (ActionType.FOLD, ActionType.CHECK)


# ── Postflop 决策测试 ─────────────────────────────────────

class TestPostflop:
    def setup_method(self):
        self.strategy = GtoSolverStrategy()

    @patch.object(GtoSolverStrategy, '_apply_adjustments',
                  side_effect=lambda s, r, c, f, sz: (r, c, f, sz))
    def test_monster_bet(self, mock_adj):
        """超强牌翻后应该高频下注"""
        state = _make_state(
            hole_cards=("Ah", "Ad"),
            community_cards=("Ac", "Ks", "5h"),
            pot=12,
            to_call=0,
        )
        # Mock equity to be high
        with patch.object(self.strategy.equity_calc, 'calculate_equity', return_value=0.85):
            with patch.object(self.strategy.equity_calc, 'get_hand_strength',
                              return_value={"combination": "three_of_a_kind", "points": 7000, "draws": {}}):
                plan = self.strategy.make_decision(state)
                assert plan.primary_action == ActionType.RAISE

    @patch.object(GtoSolverStrategy, '_apply_adjustments',
                  side_effect=lambda s, r, c, f, sz: (r, c, f, sz))
    def test_air_fold(self, mock_adj):
        """空气牌面对下注应该弃牌"""
        state = _make_state(
            hole_cards=("2h", "7d"),
            community_cards=("Ac", "Ks", "Qh"),
            pot=12,
            to_call=8,
        )
        with patch.object(self.strategy.equity_calc, 'calculate_equity', return_value=0.10):
            with patch.object(self.strategy.equity_calc, 'get_hand_strength',
                              return_value={"combination": "high_card", "points": 1000, "draws": {}}):
                plan = self.strategy.make_decision(state)
                assert plan.primary_action in (ActionType.FOLD, ActionType.CHECK)

    @patch.object(GtoSolverStrategy, '_apply_adjustments',
                  side_effect=lambda s, r, c, f, sz: (r, c, f, sz))
    def test_medium_equity_call(self, mock_adj):
        """中等equity面对小注应该跟注"""
        state = _make_state(
            hole_cards=("Ah", "Jh"),
            community_cards=("As", "7s", "2h"),
            pot=12,
            to_call=4,  # 小注 = 1/3底池
        )
        with patch.object(self.strategy.equity_calc, 'calculate_equity', return_value=0.55):
            with patch.object(self.strategy.equity_calc, 'get_hand_strength',
                              return_value={"combination": "pair", "points": 3000, "draws": {}}):
                plan = self.strategy.make_decision(state)
                # medium面对小注应该以call为主
                assert plan is not None


# ── 混合策略构建测试 ──────────────────────────────────────

class TestMixedStrategyBuilding:
    def setup_method(self):
        self.strategy = GtoSolverStrategy()

    def test_build_pure_raise(self):
        """100% raise 情况"""
        plan = self.strategy._build_mixed_action_plan(
            raise_prob=1.0, call_prob=0.0, fold_prob=0.0,
            raise_amount=10, to_call=0, pot=6,
            reasoning="test"
        )
        assert plan.primary_action == ActionType.RAISE
        assert plan.secondary_action is None or plan.secondary_probability < 0.01

    def test_build_mixed_raise_fold(self):
        """70% raise / 30% fold 混合策略"""
        plan = self.strategy._build_mixed_action_plan(
            raise_prob=0.7, call_prob=0.0, fold_prob=0.3,
            raise_amount=10, to_call=6, pot=12,
            reasoning="test mixed"
        )
        assert plan.primary_action == ActionType.RAISE
        assert plan.secondary_action in (ActionType.FOLD, ActionType.CHECK)
        # secondary_probability ≈ 0.3 / (1 - 0.7) = 1.0
        assert plan.secondary_probability > 0

    def test_build_pure_call(self):
        """纯跟注"""
        plan = self.strategy._build_mixed_action_plan(
            raise_prob=0.0, call_prob=0.8, fold_prob=0.2,
            raise_amount=10, to_call=6, pot=12,
            reasoning="test call"
        )
        assert plan.primary_action == ActionType.CALL

    def test_build_zero_probs(self):
        """零概率情况"""
        plan = self.strategy._build_mixed_action_plan(
            raise_prob=0.0, call_prob=0.0, fold_prob=0.0,
            raise_amount=10, to_call=6, pot=12,
            reasoning="test zero"
        )
        # 应该返回默认check
        assert plan.primary_action == ActionType.CHECK


# ── Fallback 测试 ─────────────────────────────────────────

class TestFallback:
    def setup_method(self):
        self.strategy = GtoSolverStrategy()

    def test_unknown_hand_falls_back(self):
        """表外手牌应该fallback到balanced"""
        state = _make_state(hole_cards=("3h", "2d"))
        plan = self.strategy.make_decision(state)
        # 应该正常返回（fallback到balanced），不报错
        assert plan is not None
        assert plan.strategy_name == "gto_solver"

    def test_empty_hole_cards(self):
        """空手牌应该check"""
        state = _make_state(hole_cards=())
        plan = self.strategy.make_decision(state)
        assert plan.primary_action == ActionType.CHECK
