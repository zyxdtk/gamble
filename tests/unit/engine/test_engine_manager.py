"""
测试 EngineManager 单例管理器
"""
from src.core.game_state import GameState, Player
from src.engine.engine_manager import EngineManager


class TestEngineManagerSingleton:
    def test_singleton_returns_same_instance(self):
        mgr1 = EngineManager()
        mgr2 = EngineManager()
        assert mgr1 is mgr2

    def test_singleton_persists_state(self):
        mgr1 = EngineManager()
        mgr1.create_brain("table1", "range")
        
        mgr2 = EngineManager()
        assert "table1" in mgr2._brains
        
        mgr1.remove_brain("table1")


class TestEngineManagerCreateBrain:
    def test_create_checkorfold_brain(self):
        mgr = EngineManager()
        brain = mgr.create_brain("test_table", "checkorfold")
        
        assert brain is not None
        assert brain.strategy_name == "checkorfold"
        mgr.remove_brain("test_table")

    def test_create_gto_brain(self):
        mgr = EngineManager()
        brain = mgr.create_brain("test_table", "gto")
        
        assert brain is not None
        assert brain.strategy_name == "gto"
        mgr.remove_brain("test_table")

    def test_create_exploitative_brain(self):
        mgr = EngineManager()
        brain = mgr.create_brain("test_table", "exploitative")
        
        assert brain is not None
        assert brain.strategy_name == "exploitative"
        mgr.remove_brain("test_table")

    def test_create_range_based_brain(self):
        mgr = EngineManager()
        brain = mgr.create_brain("test_table", "range")
        
        assert brain is not None
        assert brain.strategy_name == "range"
        mgr.remove_brain("test_table")

    def test_create_invalid_strategy_returns_none(self):
        mgr = EngineManager()
        brain = mgr.create_brain("test_table", "invalid_strategy")
        
        assert brain is None

    def test_create_multiple_brains(self):
        mgr = EngineManager()
        
        brain1 = mgr.create_brain("table1", "checkorfold")
        brain2 = mgr.create_brain("table2", "gto")
        
        assert brain1 is not None
        assert brain2 is not None
        
        assert "table1" in mgr._brains
        assert "table2" in mgr._brains
        
        mgr.remove_brain("table1")
        mgr.remove_brain("table2")


class TestEngineManagerGetDecision:
    def test_get_decision_returns_correct_structure(self):
        mgr = EngineManager()
        mgr.create_brain("test_table", "gto")
        
        state = GameState()
        state.hole_cards = ["As", "Kh"]
        state.pot = 30
        state.to_call = 20
        state.my_seat_id = 1
        state.current_dealer_seat = 5
        state.players = {i: Player(seat_id=i) for i in range(1, 7)}
        
        decision = mgr.get_decision("test_table", state)
        
        assert decision is not None
        assert decision["status"] == "DECIDING"
        assert decision["status"] == "DECIDING"
        assert "action" in decision
        assert "strategy_name" in decision
        
        mgr.remove_brain("test_table")


class TestEngineManagerRemoveBrain:
    def test_remove_existing_brain(self):
        mgr = EngineManager()
        mgr.create_brain("test_table", "checkorfold")
        
        assert "test_table" in mgr._brains
        
        mgr.remove_brain("test_table")
        
        assert "test_table" not in mgr._brains


class TestEngineManagerUpdateBrain:
    def test_update_brain_state(self):
        mgr = EngineManager()
        mgr.create_brain("test_table", "gto")
        
        state = GameState()
        state.hole_cards = ["As", "Kh"]
        state.pot = 50
        state.to_call = 30
        state.my_seat_id = 1
        state.current_dealer_seat = 3
        state.players = {i: Player(seat_id=i) for i in range(1, 7)}
        
        mgr.update_brain("test_table", state)
        
        mgr.remove_brain("test_table")


class TestEngineManagerStrategyDiscovery:
    def test_list_available_strategies(self):
        mgr = EngineManager()
        strategies = mgr.list_available_strategies()
        
        assert "checkorfold" in strategies
        assert "gto" in strategies

    def test_strategy_case_insensitive(self):
        mgr = EngineManager()
        
        brain1 = mgr.create_brain("table1", "GTO")
        brain2 = mgr.create_brain("table2", "Gto")
        
        assert brain1 is not None
        assert brain2 is not None
        assert brain1.strategy_name == "gto"
        assert brain2.strategy_name == "gto"
        
        mgr.remove_brain("table1")
        mgr.remove_brain("table2")
