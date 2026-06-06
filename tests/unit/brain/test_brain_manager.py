"""
测试 BrainManager 单例管理器
"""
from src.brain.game_state import GameState, Player
from src.brain.brain_manager import BrainManager


class TestBrainManagerSingleton:
    def test_singleton_returns_same_instance(self):
        mgr1 = BrainManager()
        mgr2 = BrainManager()
        assert mgr1 is mgr2

    def test_singleton_persists_state(self):
        mgr1 = BrainManager()
        mgr1.create_brain("table1", "range")
        
        mgr2 = BrainManager()
        assert "table1" in mgr2._brains
        
        mgr1.remove_brain("table1")


class TestBrainManagerCreateBrain:
    def test_create_checkorfold_brain(self):
        mgr = BrainManager()
        brain = mgr.create_brain("test_table", "checkorfold")
        
        assert brain is not None
        assert brain.strategy_name == "checkorfold"
        mgr.remove_brain("test_table")

    def test_create_gto_brain_as_balanced(self):
        mgr = BrainManager()
        # 验证别名映射: gto -> balanced
        brain = mgr.create_brain("test_table", "gto")
        
        assert brain is not None
        assert brain.strategy_name == "balanced"
        mgr.remove_brain("test_table")

    def test_create_exploitative_brain(self):
        mgr = BrainManager()
        brain = mgr.create_brain("test_table", "exploitative")
        
        assert brain is not None
        assert brain.strategy_name == "exploitative"
        mgr.remove_brain("test_table")

    def test_create_range_brain(self):
        mgr = BrainManager()
        brain = mgr.create_brain("test_table", "range")
        
        assert brain is not None
        assert brain.strategy_name == "range"
        mgr.remove_brain("test_table")

    def test_create_invalid_strategy_returns_none(self):
        mgr = BrainManager()
        brain = mgr.create_brain("test_table", "invalid_strategy")
        
        assert brain is None

    def test_create_multiple_brains(self):
        mgr = BrainManager()
        
        brain1 = mgr.create_brain("table1", "checkorfold")
        brain2 = mgr.create_brain("table2", "balanced")
        
        assert brain1 is not None
        assert brain2 is not None
        
        assert "table1" in mgr._brains
        assert "table2" in mgr._brains
        
        mgr.remove_brain("table1")
        mgr.remove_brain("table2")


class TestBrainManagerGetDecision:
    def test_get_decision_returns_action_plan(self):
        from src.brain.action_plan import ActionPlan
        mgr = BrainManager()
        mgr.create_brain("test_table", "balanced")
        
        state = GameState()
        state.hole_cards = ["As", "Kh"]
        state.pot = 30
        state.to_call = 20
        
        plan = mgr.get_decision("test_table", state)
        
        assert plan is not None
        assert isinstance(plan, ActionPlan)
        
        mgr.remove_brain("test_table")


class TestBrainManagerRemoveBrain:
    def test_remove_existing_brain(self):
        mgr = BrainManager()
        mgr.create_brain("test_table", "checkorfold")
        
        assert "test_table" in mgr._brains
        
        mgr.remove_brain("test_table")
        
        assert "test_table" not in mgr._brains


class TestBrainManagerUpdateBrain:
    def test_update_brain_via_handle_event(self):
        mgr = BrainManager()
        mgr.create_brain("test_table", "balanced")
        
        # 验证 handle_event 调用不报错
        mgr.update_brain("test_table", "action", {"user_id": "p1", "action": "CALL"})
        
        mgr.remove_brain("test_table")


class TestBrainManagerStrategyDiscovery:
    def test_list_available_strategies(self):
        mgr = BrainManager()
        strategies = mgr.list_available_strategies()
        
        assert "checkorfold" in strategies
        assert "balanced" in strategies # 不再是 gto

    def test_strategy_case_insensitive(self):
        mgr = BrainManager()
        
        brain1 = mgr.create_brain("table1", "BALANCED")
        brain2 = mgr.create_brain("table2", "Balanced")
        
        assert brain1 is not None
        assert brain2 is not None
        assert brain1.strategy_name == "balanced"
        assert brain2.strategy_name == "balanced"
        
        mgr.remove_brain("table1")
        mgr.remove_brain("table2")
