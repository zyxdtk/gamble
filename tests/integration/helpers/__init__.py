# tests/integration/helpers/__init__.py
"""
集成测试辅助工具。

提供浏览器状态监听、日志捕获、测试报告生成等功能。
"""

from .browser_monitor import BrowserMonitor
from .log_collector import LogCollector
from .test_reporter import TestReporter

__all__ = [
    "BrowserMonitor",
    "LogCollector",
    "TestReporter",
]
