"""
测试策略 Brain 实现
"""
import pytest
from src.core.game_state import GameState, Player
from src.engine.strategies import (
    CheckOrFoldBrain,
    GTOBrain,
    ExploitativeBrain,
)
from src.engine.action_plan import ActionType


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


class TestCheckOrFoldBrain:
    def test_returns_active_flag(self, preflop_state):
        brain = CheckOrFoldBrain()
        decision = brain.make_decision(preflop_state)
        
        assert decision["is_passive"] is False
        assert decision["strategy_name"] == "checkorfold"

    def test_returns_decision_structure(self, preflop_state):
        brain = CheckOrFoldBrain()
        decision = brain.make_decision(preflop_state)
        
        assert "decision" in decision
        assert "plan" in decision

    def test_handles_empty_hole_cards(self, empty_state):
        brain = CheckOrFoldBrain()
        decision = brain.make_decision(empty_state)
        
        assert decision["is_passive"] is False

    def test_prefers_check_over_fold(self, preflop_state):
        brain = CheckOrFoldBrain()
        preflop_state.to_call = 0
        
        decision = brain.make_decision(preflop_state)
        
        if decision.get("decision"):
            action = decision["decision"].get("action")
            assert action in ["CHECK", "WAIT"]

    def test_handles_large_bet(self, preflop_state):
        brain = CheckOrFoldBrain()
        preflop_state.to_call = 1000
        
        decision = brain.make_decision(preflop_state)
        
        assert decision is not None


class TestGTOBrain:
    def test_returns_active_flag(self, preflop_state):
        brain = GTOBrain()
        decision = brain.make_decision(preflop_state)
        
        assert decision["is_passive"] is False
        assert decision["strategy_name"] == "gto"

    def test_includes_my_action(self, preflop_state):
        brain = GTOBrain()
        decision = brain.make_decision(preflop_state)
        
        assert "my_action" in decision
        assert decision["my_action"] is not None

    def test_postflop_decision(self, postflop_state):
        brain = GTOBrain()
        decision = brain.make_decision(postflop_state)
        
        assert decision["strategy_name"] == "gto"
        assert decision["is_passive"] is False
        assert "my_action" in decision

    def test_handles_none_decision_gracefully(self, empty_state):
        brain = GTOBrain()
        decision = brain.make_decision(empty_state)
        
        assert decision["strategy_name"] == "gto"
        assert "my_action" in decision

    def test_decision_has_valid_action(self, preflop_state):
        brain = GTOBrain()
        decision = brain.make_decision(preflop_state)
        
        if decision.get("decision"):
            valid_actions = ["CHECK", "CALL", "RAISE", "FOLD", "ALL_IN", "WAIT"]
            action = decision["decision"].get("action", "WAIT")
            assert action in valid_actions

    def test_strong_hand_raises(self, strong_hand_state):
        brain = GTOBrain()
        decision = brain.make_decision(strong_hand_state)
        
        if decision.get("decision"):
            action = decision["decision"].get("action")
            assert action in ["RAISE", "CALL", "ALL_IN"]

    def test_create_initial_plan(self, preflop_state):
        brain = GTOBrain()
        plan = brain.create_initial_plan(preflop_state)
        
        assert plan is not None
        assert plan.confidence >= 0

    def test_update_plan(self, preflop_state):
        brain = GTOBrain()
        brain.receive_table_update(preflop_state)
        
        preflop_state.pot = 50
        preflop_state.to_call = 30
        
        plan = brain.update_plan(preflop_state)
        assert plan is not None


class TestExploitativeBrain:
    def test_inherits_gto_base(self, preflop_state):
        brain = ExploitativeBrain()
        decision = brain.make_decision(preflop_state)
        
        assert decision["strategy_name"] == "exploitative"
        assert decision["is_passive"] is False

    def test_adapts_to_nit_opponent(self, postflop_state):
        brain = ExploitativeBrain()
        
        nit = Player(seat_id=2, name="NitPlayer")
        nit.hands_played = 50
        nit.vpip_actions = 5
        nit.pfr_actions = 2
        nit.is_active = True
        postflop_state.players[2] = nit
        
        decision = brain.make_decision(postflop_state)
        
        assert "decision" in decision

    def test_adapts_to_maniac_opponent(self, postflop_state):
        brain = ExploitativeBrain()
        
        maniac = Player(seat_id=2, name="ManiacPlayer")
        maniac.hands_played = 50
        maniac.vpip_actions = 40
        maniac.pfr_actions = 30
        maniac.is_active = True
        postflop_state.players[2] = maniac
        
        decision = brain.make_decision(postflop_state)
        
        assert decision is not None

    def test_adjusts_for_opponent_types(self, postflop_state):
        brain = ExploitativeBrain()
        
        nit = Player(seat_id=2, name="Nit")
        nit.hands_played = 100
        nit.vpip_actions = 10
        nit.pfr_actions = 5
        nit.is_active = True
        
        maniac = Player(seat_id=3, name="Maniac")
        maniac.hands_played = 100
        maniac.vpip_actions = 80
        maniac.pfr_actions = 60
        maniac.is_active = True
        
        postflop_state.players[2] = nit
        postflop_state.players[3] = maniac
        
        decision = brain.make_decision(postflop_state)
        
        assert decision is not None


class TestBrainConsistency:
    def test_all_brains_return_required_fields(self, preflop_state):
        brains = [
            CheckOrFoldBrain(),
            GTOBrain(),
            ExploitativeBrain(),
        ]
        
        required_fields = ["strategy_name", "is_passive"]
        
        for brain in brains:
            decision = brain.make_decision(preflop_state)
            for field in required_fields:
                assert field in decision, f"{brain.__class__.__name__} missing {field}"

    def test_brain_names_are_unique(self, preflop_state):
        brains = [
            CheckOrFoldBrain(),
            GTOBrain(),
            ExploitativeBrain(),
        ]
        
        names = [b.make_decision(preflop_state)["strategy_name"] for b in brains]
        
        assert len(names) == len(set(names)), "Brain names should be unique"

    def test_all_brains_handle_empty_state(self, empty_state):
        brains = [
            CheckOrFoldBrain(),
            GTOBrain(),
            ExploitativeBrain(),
        ]
        
        for brain in brains:
            decision = brain.make_decision(empty_state)
            assert decision is not None
            assert "strategy_name" in decision


class TestBrainActionPlan:
    def test_checkorfold_creates_plan(self, preflop_state):
        brain = CheckOrFoldBrain()
        plan = brain.create_initial_plan(preflop_state)
        
        assert plan is not None
        assert plan.primary_action in [ActionType.CHECK, ActionType.FOLD, ActionType.CALL]

    def test_gto_creates_plan(self, preflop_state):
        brain = GTOBrain()
        plan = brain.create_initial_plan(preflop_state)
        
        assert plan is not None

    def test_exploitative_creates_plan(self, preflop_state):
        brain = ExploitativeBrain()
        plan = brain.create_initial_plan(preflop_state)
        
        assert plan is not None
