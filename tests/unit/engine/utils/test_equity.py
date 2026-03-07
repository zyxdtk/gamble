import pytest
from src.engine.utils.equity import EquityCalculator

class TestEquityCalculator:
    """测试胜率计算器 (EquityCalculator) 核心功能"""

    @pytest.mark.parametrize("hole, board, min_eq, max_eq, desc", [
        # --- 1. 翻前阶段 (Pre-flop) ---
        (["As", "Ad"], [], 0.80, 0.90, "AA 翻前对随机手牌 (胜率应 ~85%)"),
        (["Ks", "Kd"], [], 0.78, 0.88, "KK 翻前对随机手牌 (胜率应 ~82%)"),
        (["Qs", "Js"], [], 0.52, 0.70, "QJs 翻前对随机手牌 (领先但有限)"),
        (["7s", "2d"], [], 0.30, 0.40, "72o 翻前极弱"),

        # --- 2. 翻牌后阶段 (Post-flop) ---
        # A. 绝对领先 (Monster/Overpair)
        (["Ks", "Kd"], ["7h", "2c", "9s"], 0.75, 0.95, "KK 翻后超对面对干燥面 (绝对优势)"),
        (["As", "8s"], ["Ac", "8d", "2h"], 0.88, 1.0, "顶两对 (几乎锁定胜局)"),

        # B. 听牌阶段 (Draws)
        (["As", "Ks"], ["2s", "7s", "Jd"], 0.60, 0.82, "强同花听牌 (虽然没成，但胜率领先随机手牌)"),
        (["Ts", "Jh"], ["8s", "9d", "2c"], 0.45, 0.65, "两头顺听牌 (基于补牌的胜率)"),

        # C. 落后阶段 (Behind)
        (["2s", "3d"], ["Ah", "Kh", "Qc"], 0.10, 0.35, "垃圾牌面对强公共牌 (极低胜率)"),
    ])
    def test_equity_scenarios(self, hole, board, min_eq, max_eq, desc):
        """
        验证各典型场景下的胜率计算精度
        """
        calc = EquityCalculator()
        # 使用 500 次迭代以提升稳定性
        equity = calc.calculate_equity(hole, board, num_opponents=1, iterations=500)
        
        assert min_eq <= equity <= max_eq, f"场景 [{desc}] 胜率异常: 得到 {equity:.2f}, 预期范围 [{min_eq}, {max_eq}]"

    @pytest.mark.parametrize("hole, board, expected_draws", [
        # 1. 同花听牌
        (["As", "Ks"], ["2s", "7s", "Jd"], {"flush_draw": True, "flush_outs": 9}),
        # 2. 两头顺听牌 (OESD)
        (["Ts", "Jh"], ["8s", "9d", "2c"], {"oesd": True, "straight_outs": 8}),
        # 3. 卡顺听牌 (Gutshot)
        (["Ts", "Qh"], ["8s", "9d", "2c"], {"gutshot": True, "straight_outs": 4}),
        # 4. 同花 + 顺子双抽 (Flush + OESD)
        (["6s", "7s"], ["8s", "9s", "2d"], {"flush_draw": True, "oesd": True}),
        # 5. A-low 顺子听牌 (Wheel Draw: A234)
        (["As", "2d"], ["3h", "4s", "Kc"], {"oesd": True, "straight_outs": 8}), 
        # 6. A-high 顺子听牌 (Broadway Draw: TJQK)
        (["Ts", "Jh"], ["Qs", "Kd", "2c"], {"oesd": True, "straight_outs": 8}),
        # 7. 无听牌 (Trash)
        (["2s", "7d"], ["Jc", "4h", "Td"], {"flush_draw": False, "oesd": False, "gutshot": False}),
    ])
    def test_detect_draws_parametrized(self, hole, board, expected_draws):
        """
        全量验证听牌探测逻辑：包括同花、顺子及其各种组合
        """
        calc = EquityCalculator()
        result = calc.detect_draws(hole, board)
        
        for key, value in expected_draws.items():
            assert result[key] == value, f"听牌探测失败 [{key}]: 预期 {value}, 实际 {result[key]}"

    def test_hand_normalization(self):
        """
        测试手牌归一化标识 (如 AKs, AA)
        """
        calc = EquityCalculator()
        assert calc._normalize_hand(["Ah", "Kh"]) == "AKs"
        assert calc._normalize_hand(["As", "Ad"]) == "AA"
        assert calc._normalize_hand(["7s", "2d"]) == "72o"
