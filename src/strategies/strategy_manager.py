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
        self._latest_versions: Dict[str, int] = {}  # base_name -> max version

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
                            self._register_strategy_class(strategy_key, attr)
                except Exception:
                    pass

    def _register_strategy_class(self, base_key: str, strategy_class: Type[Strategy]) -> None:
        """注册策略类，同时注册版本化 key 和裸名 key（指向最新版本）"""
        version = getattr(strategy_class, 'strategy_version', 1)

        # 版本化 key，如 "gto_v1"
        versioned_key = f"{base_key}_v{version}"
        self._strategy_registry[versioned_key] = strategy_class

        # 更新最新版本跟踪
        if base_key not in self._latest_versions or version > self._latest_versions[base_key]:
            self._latest_versions[base_key] = version
            # 裸名 key 始终指向最新版本
            self._strategy_registry[base_key] = strategy_class

        # 注册别名（如 gto_solver 的 "gto" 别名）
        for alias in getattr(strategy_class, 'strategy_aliases', []) or []:
            alias_key = alias.lower().replace("-", "")
            self._strategy_registry[alias_key] = strategy_class
            self._strategy_registry[f"{alias_key}_v{version}"] = strategy_class

    def register_strategy(self, name: str, strategy_class: Type[Strategy]) -> None:
        self._register_strategy_class(name.lower(), strategy_class)

    def create_strategy(self, table_id: str, strategy_type: str) -> Optional[Strategy]:
        strategy_key = strategy_type.lower().replace("-", "")

        # 支持 _v 后缀的版本化查找，如 "gto_v1"
        # 也支持裸名 "gto" 自动解析到最新版本
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
        """返回版本化名称列表（如 gto_v1, range_v1, ...）"""
        result = []
        for base_key, version in self._latest_versions.items():
            for v in range(1, version + 1):
                result.append(f"{base_key}_v{v}")
        return result

    def shutdown_all(self) -> None:
        for strategy in self._strategies.values():
            strategy.shutdown()
        self._strategies.clear()