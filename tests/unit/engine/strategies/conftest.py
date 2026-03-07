import pytest
from src.core.game_state import GameState, Player

@pytest.fixture
def empty_state():
    return GameState()

@pytest.fixture
def preflop_state():
    state = GameState()
    state.hole_cards = ["As", "Kh"]
    state.pot = 30
    state.to_call = 20
    state.my_seat_id = 1
    state.current_dealer_seat = 5
    state.players = {i: Player(seat_id=i) for i in range(1, 7)}
    return state

@pytest.fixture
def postflop_state():
    state = GameState()
    state.hole_cards = ["As", "Ks"]
    state.community_cards = ["Ad", "2c", "7h"]
    state.pot = 100
    state.to_call = 50
    state.my_seat_id = 1
    state.current_dealer_seat = 3
    state.players = {i: Player(seat_id=i) for i in range(1, 7)}
    return state

@pytest.fixture
def strong_hand_state():
    state = GameState()
    state.hole_cards = ["As", "Ad"]
    state.pot = 30
    state.to_call = 10
    state.my_seat_id = 1
    state.current_dealer_seat = 5
    state.players = {i: Player(seat_id=i) for i in range(1, 7)}
    return state
