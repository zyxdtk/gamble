"""
tests/unit/bot/test_engine_manager.py

测试 EngineManager 的策略动态加载与工厂逻辑：
- 能发现 strategies/ 目录下所有合法策略
- create_brain 按名字实例化正确类型
- 未知策略名返回 None 而不崩溃
- 单例模式：同一进程中只有一个实例
- 策略注册与覆盖
"""
import pytest
from unittest.mock import patch


class TestEngineManagerStrategyDiscovery:
    """EngineManager 自动发现策略的测试。"""

    def _fresh_engine(self):
        """每次测试需要清空单例状态再构造新实例。"""
        from src.engine.engine_manager import EngineManager
        EngineManager._instance = None
        EngineManager._initialized = False
        return EngineManager()

    def test_discovers_range_strategy(self):
        """range 策略应该能被自动发现。"""
        e = self._fresh_engine()
        assert "range" in e.list_available_strategies()

    def test_discovers_gto_strategy(self):
        e = self._fresh_engine()
        assert "gto" in e.list_available_strategies()

    def test_discovers_exploitative_strategy(self):
        e = self._fresh_engine()
        assert "exploitative" in e.list_available_strategies()

    def test_discovers_checkorfold_strategy(self):
        e = self._fresh_engine()
        assert "checkorfold" in e.list_available_strategies()

    def test_discovers_all_four_strategies(self):
        """必须同时发现全部四种策略。"""
        e = self._fresh_engine()
        available = set(e.list_available_strategies())
        assert {"range", "gto", "exploitative", "checkorfold"}.issubset(available)


class TestEngineManagerCreateBrain:
    """EngineManager.create_brain 的工厂行为测试。"""

    def _fresh_engine(self):
        from src.engine.engine_manager import EngineManager
        EngineManager._instance = None
        EngineManager._initialized = False
        return EngineManager()

    def test_create_range_brain_returns_correct_type(self):
        from src.engine.strategies.range import RangeBrain
        e = self._fresh_engine()
        brain = e.create_brain("table_001", "range")
        assert isinstance(brain, RangeBrain)

    def test_create_gto_brain_returns_correct_type(self):
        from src.engine.strategies.gto import GTOBrain
        e = self._fresh_engine()
        brain = e.create_brain("table_002", "gto")
        assert isinstance(brain, GTOBrain)

    def test_create_checkorfold_brain_returns_correct_type(self):
        from src.engine.strategies.checkorfold import CheckOrFoldBrain
        e = self._fresh_engine()
        brain = e.create_brain("table_003", "checkorfold")
        assert isinstance(brain, CheckOrFoldBrain)

    def test_create_exploitative_brain_returns_correct_type(self):
        from src.engine.strategies.exploitative import ExploitativeBrain
        e = self._fresh_engine()
        brain = e.create_brain("table_004", "exploitative")
        assert isinstance(brain, ExploitativeBrain)

    def test_unknown_strategy_returns_none(self):
        """未知策略名不应崩溃，返回 None。"""
        e = self._fresh_engine()
        brain = e.create_brain("table_999", "nonexistent_strategy")
        assert brain is None

    def test_empty_strategy_name_returns_none(self):
        e = self._fresh_engine()
        brain = e.create_brain("table_999", "")
        assert brain is None

    def test_case_insensitive_strategy_lookup(self):
        """策略名应该大小写不敏感。"""
        from src.engine.strategies.range import RangeBrain
        e = self._fresh_engine()
        brain = e.create_brain("table_005", "RANGE")
        assert isinstance(brain, RangeBrain)

    def test_brain_stored_and_retrievable(self):
        """create_brain 后应能通过 get_brain 取回同一实例。"""
        e = self._fresh_engine()
        brain = e.create_brain("table_006", "range")
        assert e.get_brain("table_006") is brain

    def test_remove_brain_cleans_up(self):
        """remove_brain 后 get_brain 应返回 None。"""
        e = self._fresh_engine()
        e.create_brain("table_007", "gto")
        e.remove_brain("table_007")
        assert e.get_brain("table_007") is None

    def test_get_brain_unknown_table_returns_none(self):
        e = self._fresh_engine()
        assert e.get_brain("nonexistent_table") is None


class TestEngineManagerSingleton:
    """EngineManager 单例行为。"""

    def test_two_instantiations_return_same_object(self):
        from src.engine.engine_manager import EngineManager
        EngineManager._instance = None
        EngineManager._initialized = False
        e1 = EngineManager()
        e2 = EngineManager()
        assert e1 is e2

    def test_register_custom_strategy(self):
        """手动注册一个自定义策略，应立即可用。"""
        from src.engine.engine_manager import EngineManager
        from src.engine.brain_base import Brain
        from src.engine.action_plan import ActionPlan, ActionType
        from src.core.game_state import GameState

        class MyTestBrain(Brain):
            strategy_name = "mytest"
            def deep_think(self, state: GameState) -> ActionPlan:
                return ActionPlan(ActionType.CHECK)

        EngineManager._instance = None
        EngineManager._initialized = False
        e = EngineManager()
        e.register_strategy("mytest", MyTestBrain)
        brain = e.create_brain("t_custom", "mytest")
        assert isinstance(brain, MyTestBrain)
