"""
测试胜率计算功能
"""
from src.engine.utils.equity import EquityCalculator


class TestEquityCalculation:
    def test_equity_vs_one_opponent(self):
        calc = EquityCalculator()
        
        hole_cards = ["Ks", "Kd"]
        community_cards = ["7h", "2c", "9s"]
        
        equity = calc.calculate_equity(hole_cards, community_cards, num_opponents=1, iterations=100)
        
        assert equity > 0.5, f"KK should have >50% equity, got {equity:.2%}"

    def test_equity_vs_multiple_opponents(self):
        calc = EquityCalculator()
        
        hole_cards = ["Ks", "Kd"]
        community_cards = ["7h", "2c", "9s"]
        
        equity_multi = calc.calculate_equity(hole_cards, community_cards, num_opponents=3, iterations=100)
        
        assert equity_multi > 0.3, f"KK should have >30% equity vs 3 opponents, got {equity_multi:.2%}"

    def test_equity_preflop(self):
        calc = EquityCalculator()
        
        hole_cards = ["As", "Ad"]
        
        equity = calc.calculate_equity(hole_cards, [], num_opponents=1, iterations=100)
        
        assert equity > 0.7, f"AA should have >70% preflop equity, got {equity:.2%}"


class TestPreflopEquityEstimation:
    def test_aa_preflop_equity(self):
        calc = EquityCalculator()
        
        aa_equity = calc._estimate_preflop_equity(["As", "Ad"])
        assert aa_equity > 0.8, f"AA should have >80% preflop equity, got {aa_equity:.2%}"

    def test_ak_preflop_equity(self):
        calc = EquityCalculator()
        
        ak_equity = calc._estimate_preflop_equity(["As", "Kh"])
        assert 0.5 < ak_equity < 0.7, f"AKo should have 50-70% preflop equity, got {ak_equity:.2%}"

    def test_low_hand_preflop_equity(self):
        calc = EquityCalculator()
        
        low_equity = calc._estimate_preflop_equity(["2s", "7d"])
        assert low_equity < 0.5, f"72o should have <50% preflop equity, got {low_equity:.2%}"

    def test_pair_preflop_equity(self):
        calc = EquityCalculator()
        
        qq_equity = calc._estimate_preflop_equity(["Qs", "Qd"])
        assert qq_equity > 0.7, f"QQ should have >70% preflop equity, got {qq_equity:.2%}"

    def test_suited_hand_preflop_equity(self):
        calc = EquityCalculator()
        
        aks_equity = calc._estimate_preflop_equity(["As", "Ks"])
        assert aks_equity > 0.6, f"AKs should have >60% preflop equity, got {aks_equity:.2%}"


class TestHandNormalization:
    def test_offsuit_hand(self):
        calc = EquityCalculator()
        assert calc._normalize_hand(["As", "Kh"]) == "AKo"

    def test_suited_hand(self):
        calc = EquityCalculator()
        assert calc._normalize_hand(["Ah", "Kh"]) == "AKs"

    def test_suited_hand_same_suit(self):
        calc = EquityCalculator()
        assert calc._normalize_hand(["Ks", "As"]) == "AKs"

    def test_pair(self):
        calc = EquityCalculator()
        assert calc._normalize_hand(["As", "Ad"]) == "AA"

    def test_low_offsuit(self):
        calc = EquityCalculator()
        assert calc._normalize_hand(["7s", "2d"]) == "72o"

    def test_low_suited(self):
        calc = EquityCalculator()
        assert calc._normalize_hand(["7s", "2s"]) == "72s"
