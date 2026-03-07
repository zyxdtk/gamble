"""
测试手牌范围管理
"""
from src.engine.utils.preflop_range import PreflopRangeManager


class TestPreflopRangeManager:
    def test_singleton(self):
        mgr1 = PreflopRangeManager()
        mgr2 = PreflopRangeManager()
        assert mgr1 is mgr2

    def test_get_range_ep(self):
        mgr = PreflopRangeManager()
        
        range_result = mgr.get_range("EP")
        
        assert isinstance(range_result, list)
        assert "AA" in range_result

    def test_get_range_mp(self):
        mgr = PreflopRangeManager()
        
        range_result = mgr.get_range("MP")
        
        assert isinstance(range_result, list)
        assert "AA" in range_result

    def test_get_range_lp(self):
        mgr = PreflopRangeManager()
        
        range_result = mgr.get_range("LP")
        
        assert isinstance(range_result, list)
        assert "AA" in range_result

    def test_get_range_sb(self):
        mgr = PreflopRangeManager()
        
        range_result = mgr.get_range("SB")
        
        assert isinstance(range_result, list)

    def test_get_range_bb(self):
        mgr = PreflopRangeManager()
        
        range_result = mgr.get_range("BB")
        
        assert isinstance(range_result, list)

    def test_get_range_unknown_returns_all(self):
        mgr = PreflopRangeManager()
        
        range_result = mgr.get_range("UNKNOWN")
        
        assert isinstance(range_result, list)


class TestIsHandInRange:
    def test_hand_in_range_true(self):
        mgr = PreflopRangeManager()
        
        result = mgr.is_hand_in_range("AA", "EP")
        
        assert result is True

    def test_hand_in_range_false(self):
        mgr = PreflopRangeManager()
        
        result = mgr.is_hand_in_range("72o", "EP")
        
        assert result is False

    def test_premium_hands_in_ep(self):
        mgr = PreflopRangeManager()
        
        assert mgr.is_hand_in_range("AA", "EP") is True
        assert mgr.is_hand_in_range("KK", "EP") is True


class TestHandTier:
    def test_tier1_premium_pairs(self):
        mgr = PreflopRangeManager()
        
        assert mgr.get_hand_tier("AA") == 1
        assert mgr.get_hand_tier("KK") == 1
        assert mgr.get_hand_tier("QQ") == 1
        assert mgr.get_hand_tier("JJ") == 1

    def test_tier1_premium_cards(self):
        mgr = PreflopRangeManager()
        
        assert mgr.get_hand_tier("AKs") == 1
        assert mgr.get_hand_tier("AKo") == 1

    def test_tier2_hands(self):
        mgr = PreflopRangeManager()
        
        assert mgr.get_hand_tier("TT") == 2
        assert mgr.get_hand_tier("99") == 2
        assert mgr.get_hand_tier("AQs") == 2
        assert mgr.get_hand_tier("AQo") == 2

    def test_tier3_hands(self):
        mgr = PreflopRangeManager()
        
        assert mgr.get_hand_tier("88") == 3
        assert mgr.get_hand_tier("77") == 3
        assert mgr.get_hand_tier("ATs") == 3

    def test_tier4_weak_hands(self):
        mgr = PreflopRangeManager()
        
        assert mgr.get_hand_tier("72o") == 4
        assert mgr.get_hand_tier("53o") == 4
