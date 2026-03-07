import pytest
from src.engine.player_analysis.stats_model import StatsAwareRangeModel
from src.engine.player_analysis.model import ActionBasedRangeModel

class TestStatsAwareRangeModel:
    """测试统计感知范围模型"""
    
    def test_nit_vs_maniac_narrowing(self):
        # 1. Nit 玩家 (VPIP 10%)
        nit_model = StatsAwareRangeModel(vpip=0.10, pfr=0.08)
        # 2. 标准玩家 (VPIP 25%)
        std_model = StatsAwareRangeModel(vpip=0.25, pfr=0.20)
        # 3. Maniac 玩家 (VPIP 60%)
        maniac_model = StatsAwareRangeModel(vpip=0.60, pfr=0.50)
        
        # 记录初始值 (由于 Prior 不同，初始 Count 肯定不同)
        i_nit = nit_model.get_active_combos_count()
        i_std = std_model.get_active_combos_count()
        i_maniac = maniac_model.get_active_combos_count()
        
        # 同样是 1.0 倍底池下注
        nit_model.update_range("raise", 1.0)
        std_model.update_range("raise", 1.0)
        maniac_model.update_range("raise", 1.0)
        
        # 计算保留率 (Retention Rate)
        r_nit = nit_model.get_active_combos_count() / i_nit
        r_std = std_model.get_active_combos_count() / i_std
        r_maniac = maniac_model.get_active_combos_count() / i_maniac
        
        # 核心逻辑验证：
        # Nit 的保留率应该最低 (收缩最快)
        # Maniac 的保留率应该最高 (收缩最慢，因为他的 Raise 比较“水”)
        assert r_nit < r_std
        assert r_std < r_maniac
        print(f"Retention Rates - Nit: {r_nit:.2%}, Std: {r_std:.2%}, Maniac: {r_maniac:.2%}")

    def test_initial_prior_by_vpip(self):
        # 验证初始权重预分配
        nit_model = StatsAwareRangeModel(vpip=0.10)
        maniac_model = StatsAwareRangeModel(vpip=0.60)
        
        # 因为 Nit 初始范围根据 VPIP 过滤了，所以它的初始总权重应该明显小
        assert nit_model.get_active_combos_count() < maniac_model.get_active_combos_count()
