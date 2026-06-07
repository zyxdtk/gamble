"""
人类延迟模拟
正态分布 + 随机抖动的人类延迟模拟
"""
import asyncio
import random
import os
import yaml
from ...utils.logger import bot_logger

# 配置缓存
_config = None


def _load_config() -> dict:
    global _config
    if _config is not None:
        return _config
    config_path = os.path.join(os.getcwd(), "config", "settings.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                _config = yaml.safe_load(f) or {}
        except Exception:
            _config = {}
    else:
        _config = {}
    return _config


# 动作类型对应的延迟倍率
_ACTION_MULTIPLIERS = {
    "fold": 0.7,
    "check": 0.8,
    "call": 0.9,
    "raise": 1.2,
    "bet": 1.1,
    "all_in": 1.5,
    "action": 1.0,
    "poll": 0.5,
    "default": 1.0,
}


async def human_delay(action_type: str = "default"):
    """
    模拟人类操作延迟，使用正态分布 + 随机抖动

    Args:
        action_type: 动作类型，用于调整延迟倍率
    """
    cfg = _load_config()
    anti_ban = cfg.get("strategy", {}).get("anti_ban", {})

    min_sec = anti_ban.get("min_action_delay", 0.1)
    max_sec = anti_ban.get("max_action_delay", 1.0)
    jitter = anti_ban.get("jitter_amount", 0.05)

    # 根据动作类型调整延迟范围
    multiplier = _ACTION_MULTIPLIERS.get(action_type, 1.0)
    min_sec *= multiplier
    max_sec *= multiplier

    # 正态分布：均值取中间，3σ 覆盖范围
    mean = (min_sec + max_sec) / 2
    sigma = (max_sec - min_sec) / 6 if max_sec > min_sec else 0.01

    delay = random.gauss(mean, sigma)
    delay = max(min_sec, min(max_sec, delay))

    # 增加微小抖动
    if jitter > 0:
        delay += random.uniform(-jitter, jitter)
        delay = max(min_sec, delay)

    bot_logger.debug(f"[DELAY] {action_type}: waiting {delay:.2f}s")
    await asyncio.sleep(delay)
