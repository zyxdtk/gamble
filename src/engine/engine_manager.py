from __future__ import annotations
from typing import Dict, Optional, Type
import importlib
import os
import yaml

from .brain_base import Brain
from ..core.game_state import GameState


class EngineManager:
    _instance: Optional['EngineManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, thinking_timeout: float = 2.0):
        if EngineManager._initialized:
            return
        EngineManager._initialized = True
        
        self.thinking_timeout = thinking_timeout
        self._brains: Dict[str, Brain] = {}
        self._strategy_registry: Dict[str, Type[Brain]] = {}
        
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
                        package="src.engine"
                    )
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and issubclass(attr, Brain) and attr is not Brain):
                            strategy_key = module_name.lower().replace("_", "")
                            self._strategy_registry[strategy_key] = attr
                except Exception:
                    pass
    
    def register_strategy(self, name: str, brain_class: Type[Brain]) -> None:
        self._strategy_registry[name.lower()] = brain_class
    
    def create_brain(self, table_id: str, strategy_type: str) -> Optional[Brain]:
        strategy_key = strategy_type.lower().replace("_", "").replace("-", "")
        
        brain_class = self._strategy_registry.get(strategy_key)
        if brain_class is None:
            return None
        
        brain = brain_class(thinking_timeout=self.thinking_timeout)
        self._brains[table_id] = brain
        return brain
    
    def get_brain(self, table_id: str) -> Optional[Brain]:
        return self._brains.get(table_id)
    
    def remove_brain(self, table_id: str) -> None:
        brain = self._brains.pop(table_id, None)
        if brain:
            brain.shutdown()
    
    def update_brain(self, table_id: str, state: GameState) -> None:
        brain = self._brains.get(table_id)
        if brain:
            brain.receive_table_update(state)
    
    def get_decision(self, table_id: str, state: GameState) -> Optional[dict]:
        brain = self._brains.get(table_id)
        if brain:
            return brain.make_decision(state)
        return None
    
    def reset_brain(self, table_id: str) -> None:
        brain = self._brains.get(table_id)
        if brain:
            brain.reset()
    
    def list_available_strategies(self) -> list[str]:
        return list(self._strategy_registry.keys())
    
    def shutdown_all(self) -> None:
        for brain in self._brains.values():
            brain.shutdown()
        self._brains.clear()
