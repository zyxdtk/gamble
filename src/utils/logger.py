import logging
import sys
import os
from pathlib import Path

# 配置日志保存目录
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

class CustomFormatter(logging.Formatter):
    """自定义格式化，增加颜色支持"""
    
    # 颜色代码
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    cyan = "\x1b[36;20m"
    green = "\x1b[32;20m"
    reset = "\x1b[0m"
    
    # 格式模板
    format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: cyan + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)

def setup_logger(name: str, log_file: str = "app.log", level=logging.INFO, minimal: bool = False):
    """配置并返回一个 logger 实例"""
    logger = logging.getLogger(name)
    
    # 如果已经配置过，直接返回
    if logger.handlers:
        return logger
        
    logger.setLevel(level)

    # 1. 控制台 Handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    if minimal:
        stdout_handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        stdout_handler.setFormatter(CustomFormatter())
    logger.addHandler(stdout_handler)

    # 2. 文件 Handler
    file_path = LOG_DIR / log_file
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger

# 预定义常用模块的 Logger
bot_logger = setup_logger("bot", "bot.log")
brain_logger = setup_logger("brain", "brain.log")
table_logger = setup_logger("table", "table.log")
arena_logger = setup_logger("arena", "arena.log")
ws_logger = setup_logger("ws", "websocket.log")
hud_logger = setup_logger("hud", "hud.log", minimal=True)

# === 浏览器平台专用调试 Logger ===
# WS 通道：原始帧 + 解析后字段
ws_raw_logger = setup_logger("ws_raw", "websocket.log", level=logging.DEBUG)
# DOM 通道：页面解析结果（按钮、筹码、座位等）
dom_logger = setup_logger("dom", "dom.log", level=logging.DEBUG)
# 合并状态：StateManager 输出给上层的最终状态
state_logger = setup_logger("merged_state", "merged_state.log", level=logging.DEBUG)
