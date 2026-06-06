import asyncio
import numpy as np
import yaml
import os
from ..utils.logger import bot_logger

# 全局配置缓存
_config = None

def _load_config():
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

async def human_delay(min_sec=None, max_sec=None):
    """
    模拟人类点击延迟，优先从 settings.yaml 读取 anti_ban 配置。
    """
    cfg = _load_config()
    anti_ban = cfg.get("strategy", {}).get("anti_ban", {})
    
    # 优先级：显式传入参数 > 配置文件 > 默认值
    m_sec = min_sec if min_sec is not None else anti_ban.get("min_action_delay", 0.1)
    x_sec = max_sec if max_sec is not None else anti_ban.get("max_action_delay", 0.5)
    
    mean = (m_sec + x_sec) / 2
    sigma = (x_sec - m_sec) / 6 if x_sec > m_sec else 0.01
    
    delay = np.random.normal(mean, sigma)
    delay = max(m_sec, min(x_sec, delay))
    
    # 增加微小抖动
    jitter = anti_ban.get("jitter_amount", 0.05)
    if jitter > 0:
        delay += np.random.uniform(-jitter, jitter)
        delay = max(m_sec, delay)

    bot_logger.debug(f"[DELAY] Waiting {delay:.2f}s...")
    await asyncio.sleep(delay)
