import pytest
import os
from src.engine.player_analysis.manager import PlayerManager
from src.engine.player_analysis.showdown_model import ShowdownAwareRangeModel
from src.engine.player_analysis.stats_model import StatsAwareRangeModel
from src.engine.player_analysis.model import ActionBasedRangeModel

@pytest.fixture
def temp_db_path(tmp_path):
    return str(tmp_path / "test_showdown.db")

class TestShowdownAwareStrategy:
    """测试摊牌感知范围修正策略"""
    
    def test_showdown_bias_calibration(self, temp_db_path):
        manager = PlayerManager(temp_db_path)
        user_id = "bluff_master"
        
        # 0. 预置基础统计 (25% VPIP)
        for _ in range(75): manager.record_hand_played(user_id, False, False)
        for _ in range(25): manager.record_hand_played(user_id, True, True)

        # 1. 模拟多次展示弱牌 (72o, 94s, 53o)
        manager.record_showdown(user_id, "72o", "river", "bluffed large")
        manager.record_showdown(user_id, "94s", "river", "semi-bluff")
        manager.record_showdown(user_id, "53o", "showdown", "junk")
        
        # 2. 获取范围模型 (应触发 ShowdownAwareRangeModel)
        model = manager.get_range_model(user_id)
        assert isinstance(model, ShowdownAwareRangeModel)
        
        # 3. 验证偏差因子 (应该由于经常展示弱牌而小于 1.0)
        assert model.bias_factor < 1.0
        
        # 4. 验证行为差异
        # 使用同 VPIP 但无摊牌历史的 StatsAware 模型作为对照组
        control_model = StatsAwareRangeModel(vpip=0.25, pfr=0.20)
        
        # 同样是重注 (Ratio 2.0)
        model.update_range("raise", 2.0)
        control_model.update_range("raise", 2.0)
        
        # 经过校准的模型应对该玩家的 Raise 动作更“包容”
        # 同样的动作下，诈唬者的残留权重应该更多
        assert model.get_active_combos_count() > control_model.get_active_combos_count()

    def test_value_heavy_player_calibration(self, temp_db_path):
        manager = PlayerManager(temp_db_path)
        user_id = "value_monster"
        
        # 0. 预置基础统计 (25% VPIP)
        for _ in range(75): manager.record_hand_played(user_id, False, False)
        for _ in range(25): manager.record_hand_played(user_id, True, True)

        # 1. 模拟只展示超强牌 (AA, KK, AKs)
        manager.record_showdown(user_id, "AA", "river")
        manager.record_showdown(user_id, "KK", "showdown")
        manager.record_showdown(user_id, "AKs", "showdown")
        
        model = manager.get_range_model(user_id)
        # 偏差因子应大于 1.0
        assert model.bias_factor > 1.0
        
        # 同样动作，收缩应比基础统计模型更剧烈
        control_model = StatsAwareRangeModel(vpip=0.25, pfr=0.20)
        model.update_range("raise", 1.0)
        control_model.update_range("raise", 1.0)
        
        # 实诚者的范围收缩应该更明显
        assert model.get_active_combos_count() < control_model.get_active_combos_count()
