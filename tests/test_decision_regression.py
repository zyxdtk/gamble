import pytest
from src.core.game_state import GameState, Player
from src.engine.decision_engine import DecisionEngine

def test_decision_engine_struct():
    engine = DecisionEngine()
    state = GameState()
    state.hole_cards = ["As", "Ks"]
    state.community_cards = ["Ad", "2c", "7h"]
    state.pot = 1000
    
    # Hero is seat 1, Dealer is seat 9
    state.my_seat_id = 1
    state.current_dealer_seat = 9
    state.players = {i: Player(seat_id=i) for i in range(1, 10)}
    
    decision = engine.decide(state)
    
    assert "decision" in decision
    assert "action" in decision["decision"]
    assert "amount" in decision["decision"]
    assert decision["decision"]["action"] in ["CHECK", "CALL", "RAISE", "FOLD", "ALL-IN"]
    print(f"Decision: {decision['decision']}")

def test_exploitative_logic():
    engine = DecisionEngine()
    state = GameState()
    state.hole_cards = ["7s", "2d"]
    state.community_cards = ["Ac", "Kd", "Qh"]
    state.pot = 1000
    state.to_call = 500 # Realistic bet to call
    
    # Add a NIT opponent
    nit = Player(seat_id=2)
    nit.hands_played = 20
    nit.vpip_actions = 2 # 10% VPIP
    nit.pfr_actions = 1 # 5% PFR
    nit.is_active = True
    state.players[2] = nit
    
    decision = engine.decide(state)
    print(f"Against Nit decision: {decision['my_action']} | Equity: {decision['my_equity']}%")
    assert "弃牌" in decision["my_action"] or "过牌" in decision["my_action"]

def test_maniac_logic():
    engine = DecisionEngine()
    state = GameState()
    state.hole_cards = ["Js", "Ts"] # Middle pair or straight draw
    state.community_cards = ["9s", "8d", "2c"]
    state.pot = 2000
    
    # Add a MANIAC opponent
    maniac = Player(seat_id=3)
    maniac.hands_played = 20
    maniac.vpip_actions = 18 # 90% VPIP
    maniac.pfr_actions = 14 # 70% PFR
    maniac.is_active = True
    state.players[3] = maniac
    
    decision = engine.decide(state)
    print(f"Against Maniac decision: {decision['my_action']}")
    # JsTs on 9s8d2c is a straight draw and middle pair potential
    # Against maniac it should be looser
    assert "跟注" in decision["my_action"] or "加注" in decision["my_action"]

if __name__ == "__main__":
    test_decision_engine_struct()
    test_exploitative_logic()
    test_maniac_logic()
    print("All tests passed!")
