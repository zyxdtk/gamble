import os
import pytest
from src.engine.player_analysis.manager import PlayerManager
from src.core.game_state import Player

class TestPlayerInformationBase:
    @pytest.fixture
    def temp_db_path(self, tmp_path):
        return str(tmp_path / "test_players.db")

    def test_player_user_id_extension(self):
        player = Player(seat_id=1, user_id="user_123", name="Leon")
        assert player.user_id == "user_123"
        assert player.name == "Leon"

    def test_manager_persistence_and_fusion(self, temp_db_path):
        manager = PlayerManager(temp_db_path)
        user_id = "pro_player_1"

        # 第 1 局：VPIP + PFR
        manager.record_hand_played(user_id, is_vpip=True, is_pfr=True)
        # 第 2 局：仅 VPIP
        manager.record_hand_played(user_id, is_vpip=True, is_pfr=False)
        
        # 验证本局内存统计
        session_stats = manager.get_session_profiling(user_id)
        assert session_stats["hands"] == 2
        assert session_stats["vpip"] == 100.0
        assert session_stats["pfr"] == 50.0

        # 验证全局统计 (DB)
        global_stats = manager.get_combined_profiling(user_id)
        assert global_stats["hands"] == 2

        # 模拟重启（新建管理器指向同一个 DB）
        manager_reboot = PlayerManager(temp_db_path)
        
        # 验证从 DB 加载的历史数据
        history_stats = manager_reboot.get_combined_profiling(user_id)
        assert history_stats["hands"] == 2

        # 在新 Session 中继续记录
        manager_reboot.record_hand_played(user_id, is_vpip=False, is_pfr=False)
        
        # 验证全局融合后的数据 (3 手牌，2 VPIP, 1 PFR)
        combined = manager_reboot.get_combined_profiling(user_id)
        assert combined["hands"] == 3
        assert combined["vpip"] == 66.7
        assert combined["pfr"] == 33.3

        # 验证新 Session 本桌统计 (只有 1 手牌)
        new_session = manager_reboot.get_session_profiling(user_id)
        assert new_session["hands"] == 1
        assert new_session["vpip"] == 0.0

    def test_manager_reset_session(self, temp_db_path):
        manager = PlayerManager(temp_db_path)
        user_id = "anonymous"
        
        manager.record_hand_played(user_id, True, True)
        assert manager.session_stats[user_id]["hands"] == 1
        
        manager.reset_session()
        assert user_id not in manager.session_stats
    def test_manager_per_player_range_independence(self, temp_db_path):
        manager = PlayerManager(temp_db_path)
        p1_id, p2_id = "user_1", "user_2"
        
        # 更新玩家 A 的范围 (大注)
        manager.update_opponent_range(p1_id, "raise", 2.0)
        # 获取玩家 B 的范围 (应保持初始状态)
        r1 = manager.get_range_model(p1_id).get_active_combos_count()
        r2 = manager.get_range_model(p2_id).get_active_combos_count()
        
        assert r1 < r2
        assert r2 > 160 # 初始接 169

    def test_manager_hero_perceived_range(self, temp_db_path):
        manager = PlayerManager(temp_db_path)
        initial_hero = manager.hero_perceived_range.get_active_combos_count()
        
        manager.update_hero_perceived_range("raise", 1.5)
        filtered_hero = manager.hero_perceived_range.get_active_combos_count()
        
        assert filtered_hero < initial_hero
        # 确保不影响任何对手
        assert manager.get_range_model("any_bot").get_active_combos_count() > initial_hero * 0.99
