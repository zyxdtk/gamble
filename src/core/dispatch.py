"""
调度注册表 — 将 (platform, game) 映射到 runner 函数。

各 runner 统一接受 SessionConfig 参数，
main() 通过 get_runner() 查找并执行。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from src.utils.cli_player import PilotMode


@dataclass
class SessionConfig:
    """会话配置 — 描述一次完整的游戏会话"""
    platform: str           # "arena" | "browser"
    game: str               # "ring" | "mtt" | "sng" | "competition"
    pilot: PilotMode        # 人类参与程度
    strategy: str           # 策略名称
    platform_kwargs: Dict[str, Any] = field(default_factory=dict)
    game_kwargs: Dict[str, Any] = field(default_factory=dict)


# runner 工厂类型
RunnerFactory = Callable[[SessionConfig], Awaitable[None]]

# 注册表
_RUNNER_REGISTRY: Dict[Tuple[str, str], RunnerFactory] = {}


def register_runner(platform: str, game: str):
    """装饰器：注册 runner 到调度注册表"""
    def decorator(func: RunnerFactory) -> RunnerFactory:
        _RUNNER_REGISTRY[(platform, game)] = func
        return func
    return decorator


def get_runner(platform: str, game: str) -> Optional[RunnerFactory]:
    """查找 runner，未找到返回 None"""
    return _RUNNER_REGISTRY.get((platform, game))


def list_runners() -> Dict[Tuple[str, str], str]:
    """列出所有已注册的 runner（调试用）"""
    return {k: v.__name__ for k, v in _RUNNER_REGISTRY.items()}
