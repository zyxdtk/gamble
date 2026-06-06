from __future__ import annotations
from typing import Dict, Optional, Type
import importlib
import os
import yaml

from .strategy_base import Strategy
from .game_state import GameState
from .action_plan import ActionPlan
from ..utils.logger import brain_logger


class StrategyManager:
    _instance: Optional['StrategyManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, thinking_timeout: float = 2.0):
        if StrategyManager._initialized:
            return
        StrategyManager._initialized = True
        
        self.thinking_timeout = thinking_timeout
        self._strategies: Dict[str, Strategy] = {}
        self._strategy_registry: Dict[str, Type[Strategy]] = {}
        
        self._load_settings()
        self._discover_strategies()
    
    def _load_settings(self) -> None:
        config_path = os.path.join(os.getcwd(), "config", "settings.yaml")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    strategy_cfg = data.get("strategy", {})
                    self.thinking_timeout = strategy_cfg.get("thinking_timeout", 2.0)
            except Exception:
                pass
    
    def _discover_strategies(self) -> None:
        strategies_dir = os.path.join(os.path.dirname(__file__), "strategies")
        if not os.path.exists(strategies_dir):
            return
        
        for filename in os.listdir(strategies_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                module_name = filename[:-3]
                try:
                    module = importlib.import_module(
                        f".strategies.{module_name}", 
                        package="src.strategies"
                    )
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and issubclass(attr, Strategy) and 
                            attr is not Strategy and getattr(attr, "__module__", "") == module.__name__):
                            strategy_key = module_name.lower().replace("_", "")
                            self._strategy_registry[strategy_key] = attr
                except Exception:
                    pass
    
    def register_strategy(self, name: str, strategy_class: Type[Strategy]) -> None:
        self._strategy_registry[name.lower()] = strategy_class
    
    def create_strategy(self, table_id: str, strategy_type: str) -> Optional[Strategy]:
        strategy_key = strategy_type.lower().replace("_", "").replace("-", "")
        
        # 别名映射
        if strategy_key == "gto":
            strategy_key = "balanced"
            
        strategy_class = self._strategy_registry.get(strategy_key)
        if strategy_class is None:
            return None
        
        strategy = strategy_class(thinking_timeout=self.thinking_timeout)
        self._strategies[table_id] = strategy
        return strategy
    
    def get_strategy(self, table_id: str) -> Optional[Strategy]:
        return self._strategies.get(table_id)
    
    def remove_strategy(self, table_id: str) -> None:
        strategy = self._strategies.pop(table_id, None)
        if strategy:
            strategy.shutdown()
    
    def update_strategy(self, table_id: str, event_type: str, data: dict) -> None:
        strategy = self._strategies.get(table_id)
        if strategy:
            strategy.handle_event(event_type, data)
    
    def get_decision(self, table_id: str, state: GameState) -> Optional[ActionPlan]:
        strategy = self._strategies.get(table_id)
        if strategy:
            return strategy.make_decision(state)
        return None
    
    def reset_strategy(self, table_id: str) -> None:
        strategy = self._strategies.get(table_id)
        if strategy:
            strategy.reset()
    
    def list_available_strategies(self) -> list[str]:
        return list(self._strategy_registry.keys())
    
    def shutdown_all(self) -> None:
        for strategy in self._strategies.values():
            strategy.shutdown()
        self._strategies.clear()