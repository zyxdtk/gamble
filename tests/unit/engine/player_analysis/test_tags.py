"""
测试玩家分析标签逻辑
"""
from src.core.game_state import Player
from src.engine.player_analysis import PlayerTag, get_player_tag


class TestGetPlayerTag:
    def test_nit_player(self):
        player = Player(seat_id=1, name="NitPlayer")
        player.hands_played = 100
        player.vpip_actions = 10
        player.pfr_actions = 5
        
        tag = get_player_tag(player)
        assert tag == PlayerTag.NIT

    def test_maniac_player(self):
        player = Player(seat_id=1, name="ManiacPlayer")
        player.hands_played = 100
        player.vpip_actions = 80
        player.pfr_actions = 60
        
        tag = get_player_tag(player)
        assert tag == PlayerTag.MANIAC

    def test_fish_player(self):
        player = Player(seat_id=1, name="FishPlayer")
        player.hands_played = 100
        player.vpip_actions = 35 # 35% < 40% (不再触发 STATION)
        player.pfr_actions = 12 # 12% < 15%
        
        tag = get_player_tag(player)
        assert tag == PlayerTag.FISH

    def test_station_player(self):
        player = Player(seat_id=1, name="StationPlayer")
        player.hands_played = 100
        player.vpip_actions = 55 # > 40% (触发 STATION)
        player.pfr_actions = 5
        
        tag = get_player_tag(player)
        assert tag == PlayerTag.STATION

    def test_tag_player(self):
        player = Player(seat_id=1, name="TAGPlayer")
        player.hands_played = 100
        player.vpip_actions = 20
        player.pfr_actions = 16
        
        tag = get_player_tag(player)
        assert tag == PlayerTag.TAG

    def test_unknown_player(self):
        player = Player(seat_id=1, name="NewPlayer")
        player.hands_played = 0
        
        tag = get_player_tag(player)
        assert tag == PlayerTag.UNKNOWN
