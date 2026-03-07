import pytest
from src.engine.player_analysis import RangeModel

class TestRangeModel:
    """测试贝叶斯范围模型"""
    
    def test_range_filtering_on_heavy_bet(self):
        model = RangeModel()
        initial_count = model.get_active_combos_count()
        
        # 对手重注 (Ratio 2.0)
        model.update_range(action="raise", pot_ratio=2.0)
        
        filtered_count = model.get_active_combos_count()
        assert filtered_count < initial_count * 0.5 

    def test_range_filtering_on_small_bet(self):
        model = RangeModel()
        initial_count = model.get_active_combos_count()
        
        # 对手小注 (Ratio 0.3)
        model.update_range(action="raise", pot_ratio=0.3)
        
        filtered_count = model.get_active_combos_count()
        # 小注对范围的缩紧应该是适度的
        assert filtered_count > initial_count * 0.5
        assert filtered_count < initial_count

    def test_range_narrowing_on_call(self):
        model = RangeModel()
        initial_count = model.get_active_combos_count()
        
        # 对手跟注 (Call 通常惩罚极强和极弱牌)
        model.update_range(action="call", pot_ratio=1.0)
        
        filtered_count = model.get_active_combos_count()
        assert filtered_count < initial_count
        # 跟注不应该像重注那样剧烈收缩范围
        assert filtered_count > initial_count * 0.6

    def test_range_reset_on_fold(self):
        model = RangeModel()
        model.update_range(action="fold", pot_ratio=0)
        assert model.get_active_combos_count() == 0

    def test_progressive_narrowing(self):
        model = RangeModel()
        
        # 连续两个动作应该持续缩紧范围
        model.update_range(action="raise", pot_ratio=0.5)
        count_1 = model.get_active_combos_count()
        
        model.update_range(action="raise", pot_ratio=1.0)
        count_2 = model.get_active_combos_count()
        
        assert count_2 < count_1
