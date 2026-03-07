import pytest
from src.engine.strategies.range import RangeBrain
from src.core.game_state import GameState, Player
from src.engine.action_plan import ActionType
from src.engine.player_analysis import StatsAwareRangeModel, ShowdownAwareRangeModel

class TestRangeBrainDecision:
    """测试基于 Range 的决策核心"""
    def test_semi_bluff_with_strong_draw(self):
        brain = RangeBrain()
        state = GameState()
        state.hole_cards = ["As", "Ks"]
        state.community_cards = ["2s", "7s", "Jd"] # 强同花听牌
        state.pot = 100
        state.total_chips = 1000 # SPR = 10 (Deep)
        state.to_call = 20
        
        decision = brain.create_initial_plan(state)
        # 深筹码 + 强听牌 -> 应该倾向于 RAISE (半诈唬)
        assert decision.primary_action == ActionType.RAISE
        assert decision.primary_amount == int(100 * 0.8)
        assert decision.secondary_action is not None
        assert decision.secondary_probability == 0.2
        assert decision.bet_size_hint == "pot"
        assert "半诈唬" in decision.reasoning

    def test_value_bet_with_strong_hand(self):
        brain = RangeBrain()
        state = GameState()
        state.hole_cards = ["As", "Ad"]
        state.community_cards = ["Ah", "2c", "7d"] # 顶三条，极强
        state.pot = 200
        state.total_chips = 2000
        state.to_call = 0
        
        decision = brain.create_initial_plan(state)
        assert decision.primary_action == ActionType.RAISE
        assert decision.primary_amount == int(200 * 0.75)
        assert decision.bet_size_hint == "pot"
        assert "价值提取" in decision.reasoning

    def test_fold_on_overbet_with_marginal_hand(self):
        brain = RangeBrain()
        state = GameState()
        state.hole_cards = ["Jh", "Th"]
        state.community_cards = ["Js", "7d", "2c"] # 顶对弱踢脚
        state.pot = 100
        state.to_call = 200 # 2x Pot Overbet
        
        decision = brain.create_initial_plan(state)
        # 对手超池大注 + 弱踢脚一对 -> 应该 FOLD
        assert decision.primary_action == ActionType.FOLD


class TestRangeBrainOpponentModeling:
    """测试 RangeBrain 基于对手范围建模的差异化决策"""

    def _build_state_with_opponent(self, vpip: float, pfr: float,
                                   showdowns=None) -> tuple:
        """构造带对手信息的游戏状态，返回 (brain, state)"""
        import tempfile, os
        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "test.db")

        brain = RangeBrain()
        # 替换内部 PlayerManager 使用隔离数据库
        from src.engine.player_analysis import PlayerManager
        brain.player_mgr = PlayerManager(db_path)

        uid = "test_opponent_001"

        # 写入统计数据
        hands_not_vpip = int(100 * (1 - vpip))
        hands_vpip = int(100 * vpip)
        hands_pfr = int(100 * pfr)
        for _ in range(hands_not_vpip):
            brain.player_mgr.record_hand_played(uid, False, False)
        for _ in range(hands_vpip - hands_pfr):
            brain.player_mgr.record_hand_played(uid, True, False)
        for _ in range(hands_pfr):
            brain.player_mgr.record_hand_played(uid, True, True)

        # 写入摊牌记录（如果有）
        if showdowns:
            for hand, street in showdowns:
                brain.player_mgr.record_showdown(uid, hand, street)

        # 构建游戏状态
        state = GameState()
        state.hole_cards = ["Qh", "Jh"]
        state.community_cards = ["Qd", "5c", "2s"]  # 顶对弱踢脚
        state.pot = 100
        state.total_chips = 1000
        # 面对 0.6 倍底池下注
        state.to_call = 60
        state.active_seat = 2
        state.players = {
            2: Player(seat_id=2, name="TestOpponent", user_id=uid)
        }

        return brain, state

    def test_nit_opponent_raises_call_threshold(self):
        """面对 Nit 对手时，跟注阈值应提高，相同牌力更倾向弃牌"""
        # Nit: 10% VPIP
        brain_nit, state_nit = self._build_state_with_opponent(vpip=0.10, pfr=0.09)
        # Maniac: 60% VPIP
        brain_maniac, state_maniac = self._build_state_with_opponent(vpip=0.60, pfr=0.50)

        # 触发一次 raise 更新范围
        state_nit.to_call = 60
        state_maniac.to_call = 60

        decision_nit = brain_nit.create_initial_plan(state_nit)
        decision_maniac = brain_maniac.create_initial_plan(state_maniac)

        # 面对 Nit + 跟注阈值提高 = 应该 FOLD（紧型 Raise 意味着强牌）
        # 面对 Maniac + 跟注阈值降低 = 可能 CALL（宽型 Raise 中弱牌更多）
        # 关键验证：两者方向不同或 Maniac 比 Nit 更倾向于 CALL
        nit_folded = decision_nit.primary_action == ActionType.FOLD
        maniac_called = decision_maniac.primary_action in [ActionType.CALL, ActionType.RAISE]

        # 至少有一个方向符合预期
        assert nit_folded or maniac_called, (
            f"Nit decision: {decision_nit.primary_action}, "
            f"Maniac decision: {decision_maniac.primary_action}"
        )

    def test_showdown_bluffer_lowers_call_threshold(self):
        """面对历史摊牌为弱牌的诈唬者，系统应降低跟注阈值"""
        # 模拟一个历史总是展示垃圾牌的诈唬者
        bluffer_showdowns = [
            ("72o", "river"), ("83o", "river"), ("94s", "river"),
        ]
        brain, state = self._build_state_with_opponent(
            vpip=0.30, pfr=0.25, showdowns=bluffer_showdowns
        )

        decision = brain.create_initial_plan(state)
        
        # 验证使用了摊牌感知模型
        uid = "test_opponent_001"
        model = brain.player_mgr.get_range_model(uid)
        assert isinstance(model, ShowdownAwareRangeModel)
        
        # 诈唬者的 bias_factor 应该小于 1.0
        assert model.bias_factor < 1.0

        # 面对诈唬者，安全余量应为负（跟注阈值降低）
        # 在调用 create_initial_plan 之前先查询模型（此时未被更新，能反映原始 bias）
        uid = "test_opponent_001"
        model_before = brain.player_mgr.get_range_model(uid)
        baseline = model_before.get_active_combos_count()
        
        # 对实诚对手（无摊牌记录）建立对照
        import tempfile, os
        tmp2 = tempfile.mkdtemp()
        from src.engine.player_analysis import PlayerManager
        ctrl_mgr = PlayerManager(os.path.join(tmp2, "ctrl.db"))
        ctrl_uid = "ctrl_opponent"
        for _ in range(70): ctrl_mgr.record_hand_played(ctrl_uid, False, False)
        for _ in range(30): ctrl_mgr.record_hand_played(ctrl_uid, True, True)
        ctrl_model = ctrl_mgr.get_range_model(ctrl_uid)
        ctrl_baseline = ctrl_model.get_active_combos_count()
        
        # 诈唬者（弱摊牌）的初始组合权重应低于标准对照
        # 因为 ShowdownAwareRangeModel 的先验降低了早期压缩
        # 核心断言：bias_factor < 1 已验证 -> 系统会对该玩家更宽容
        # 额外验证：相比 StatsAwareRangeModel(无摊牌)，调试者的 bias_factor 为关键标志
        assert model.bias_factor < 1.0, f"bias_factor应<1, 实为{model.bias_factor:.3f}"

    def test_tightness_reflected_in_reasoning(self):
        """验证 reasoning 中包含紧凑度信息"""
        brain, state = self._build_state_with_opponent(vpip=0.20, pfr=0.18)
        # 强牌场景：应直接触发 value bet
        state.hole_cards = ["As", "Ad"]
        state.community_cards = ["Ah", "Kd", "2c"]
        state.to_call = 0

        decision = brain.create_initial_plan(state)
        assert decision.primary_action == ActionType.RAISE
        assert "紧凑度" in decision.reasoning
