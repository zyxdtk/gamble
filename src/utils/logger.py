import logging
import logging.handlers
import sys
import os
from pathlib import Path

# 日志保存目录
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# 日志文件
APP_LOG = "app.log"
WARN_LOG = "warn.log"

# 日志轮转配置
MAX_BYTES = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 10              # 最多保留 10 个备份

# 全局日志级别（仅影响控制台，文件始终记录全量）
_log_level = logging.WARNING

# 是否已初始化根 logger
_root_initialized = False

FILE_FORMAT = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _setup_root_logger():
    """初始化根 logger，配置 app.log + warn.log + 控制台（仅 WARNING+）"""
    global _root_initialized
    if _root_initialized:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # 根设为 DEBUG，由各 handler 自己控制级别

    # 避免重复添加
    if root.handlers:
        _root_initialized = True
        return

    # 1. 控制台：默认只显示 WARNING+（不干扰 CLI 交互）
    stdout_handler = logging.StreamHandler(sys.stderr)
    stdout_handler.setLevel(_log_level)
    stdout_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(stdout_handler)

    # 2. app.log：记录所有日志（DEBUG+），轮转
    app_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / APP_LOG,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(FILE_FORMAT)
    root.addHandler(app_handler)

    # 3. warn.log：仅 WARNING 及以上，轮转
    warn_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / WARN_LOG,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    warn_handler.setLevel(logging.WARNING)
    warn_handler.setFormatter(FILE_FORMAT)
    root.addHandler(warn_handler)

    _root_initialized = True


def set_log_level(level: str | int):
    """设置控制台日志级别

    Args:
        level: 级别名称（DEBUG/INFO/WARNING/ERROR）或 logging 常量
    """
    global _log_level
    if isinstance(level, str):
        _log_level = getattr(logging, level.upper(), logging.WARNING)
    else:
        _log_level = level

    # 更新根 logger 的控制台 handler
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(_log_level)


def get_logger(name: str, minimal: bool = False) -> logging.Logger:
    """获取 logger 实例

    所有 logger 共享根 logger 的 handler（app.log + warn.log + 控制台）。
    不再为每个模块创建独立日志文件。

    Args:
        name: logger 名称（通常为模块名）
        minimal: 兼容参数，不再使用
    """
    _setup_root_logger()

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # 让所有消息通过，由 handler 过滤

    return logger


# ─── 兼容旧接口 ─────────────────────────────────────────────────────────────
def setup_logger(name: str, log_file: str = "", level=logging.INFO, minimal: bool = False) -> logging.Logger:
    """兼容旧接口，忽略 log_file 参数，统一输出到 app.log"""
    return get_logger(name, minimal=minimal)


# ─── 预定义常用 Logger ───────────────────────────────────────────────────────
bot_logger = get_logger("bot")
brain_logger = get_logger("brain")
table_logger = get_logger("table")
arena_logger = get_logger("arena")
ws_logger = get_logger("ws")
hud_logger = get_logger("hud")

# === 浏览器平台专用调试 Logger ===
# WS 通道：原始帧 + 解析后字段
ws_raw_logger = get_logger("ws_raw")
# DOM 通道：页面解析结果（按钮、筹码、座位等）
dom_logger = get_logger("dom")
# 合并状态：StateManager 输出给上层的最终状态
state_logger = get_logger("merged_state")
