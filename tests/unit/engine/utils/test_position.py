"""
测试位置计算与手牌规范化工具
"""
from src.core.game_state import GameState, Player
from src.engine.utils.position import (
    get_position_code,
    normalize_hand_string
)


class TestGetPositionCode:
    def _create_state(self, my_seat: int, dealer_seat: int, num_players: int = 6) -> GameState:
        state = GameState()
        state.my_seat_id = my_seat
        state.current_dealer_seat = dealer_seat
        state.players = {i: Player(seat_id=i) for i in range(1, num_players + 1)}
        return state

    def test_button_position(self):
        state = self._create_state(1, 1)
        code = get_position_code(state)
        assert code == "LP"

    def test_small_blind_position(self):
        state = self._create_state(2, 1)
        code = get_position_code(state)
        assert code == "SB"

    def test_big_blind_position(self):
        state = self._create_state(3, 1)
        code = get_position_code(state)
        assert code == "BB"

    def test_early_position(self):
        state = self._create_state(4, 1)
        code = get_position_code(state)
        assert code in ["EP", "MP"]

    def test_middle_position(self):
        state = self._create_state(5, 1)
        code = get_position_code(state)
        assert code in ["EP", "MP", "LP"]

    def test_cutoff_position(self):
        state = self._create_state(6, 1)
        code = get_position_code(state)
        assert code == "LP"

    def test_returns_all_for_missing_info(self):
        state = GameState()
        code = get_position_code(state)
        assert code == "ALL"


class TestNormalizeHandString:
    def test_offsuit_hand(self):
        result = normalize_hand_string(["As", "Kh"])
        assert result == "AKo"

    def test_suited_hand(self):
        result = normalize_hand_string(["Ah", "Kh"])
        assert result == "AKs"

    def test_pair(self):
        result = normalize_hand_string(["As", "Ad"])
        assert result == "AA"

    def test_order_independence(self):
        result1 = normalize_hand_string(["As", "Kh"])
        result2 = normalize_hand_string(["Kh", "As"])
        assert result1 == result2

    def test_low_hand(self):
        result = normalize_hand_string(["7s", "2d"])
        assert result == "72o"

    def test_empty_hand(self):
        result = normalize_hand_string([])
        assert result == "XX"

    def test_single_card(self):
        result = normalize_hand_string(["As"])
        assert result == "XX"

    def test_invalid_card(self):
        result = normalize_hand_string(["invalid", "card"])
        assert result == "XX"
