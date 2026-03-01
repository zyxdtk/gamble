# tests/integration/helpers/log_collector.py
"""
日志收集器。

用于在集成测试中捕获和过滤应用程序日志。
"""

import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from collections import deque


@dataclass
class LogEntry:
    """日志条目。"""
    timestamp: float
    level: str  # INFO, DEBUG, WARNING, ERROR, CRITICAL
    source: str  # 日志来源模块
    message: str


class LogCollector:
    """
    日志收集器。

    捕获应用程序输出，支持按级别和来源过滤。
    """

    LEVEL_PRIORITY = {
        "DEBUG": 0,
        "INFO": 1,
        "WARNING": 2,
        "ERROR": 3,
        "CRITICAL": 4,
    }

    def __init__(self, max_entries: int = 10000, min_level: str = "DEBUG"):
        self.max_entries = max_entries
        self.min_level = min_level
        self._logs: deque = deque(maxlen=max_entries)
        self._filters: List[Callable[[LogEntry], bool]] = []
        self._capture_enabled = False

    def start_capture(self):
        """开始捕获日志。"""
        self._capture_enabled = True

    def stop_capture(self):
        """停止捕获日志。"""
        self._capture_enabled = False

    def add_filter(self, filter_fn: Callable[[LogEntry], bool]):
        """添加日志过滤器。"""
        self._filters.append(filter_fn)

    def collect(self, message: str, level: str = "INFO", source: str = "unknown"):
        """
        收集一条日志。

        通常在应用程序代码中调用，或通过重定向 stdout/stderr 自动捕获。
        """
        if not self._capture_enabled:
            return

        # 检查级别
        if self.LEVEL_PRIORITY.get(level, 0) < self.LEVEL_PRIORITY.get(self.min_level, 0):
            return

        entry = LogEntry(
            timestamp=time.time(),
            level=level,
            source=source,
            message=message.strip() if message else "",
        )

        # 应用过滤器
        for filter_fn in self._filters:
            if not filter_fn(entry):
                return

        self._logs.append(entry)

    def get_logs(
        self,
        min_level: Optional[str] = None,
        source_pattern: Optional[str] = None,
        message_pattern: Optional[str] = None,
        since: Optional[float] = None,
    ) -> List[LogEntry]:
        """
        获取过滤后的日志。

        Args:
            min_level: 最小日志级别
            source_pattern: 来源匹配正则
            message_pattern: 消息匹配正则
            since: 从此时间戳之后
        """
        result = list(self._logs)

        if min_level:
            min_priority = self.LEVEL_PRIORITY.get(min_level, 0)
            result = [log for log in result
                     if self.LEVEL_PRIORITY.get(log.level, 0) >= min_priority]

        if source_pattern:
            pattern = re.compile(source_pattern, re.IGNORECASE)
            result = [log for log in result if pattern.search(log.source)]

        if message_pattern:
            pattern = re.compile(message_pattern, re.IGNORECASE)
            result = [log for log in result if pattern.search(log.message)]

        if since:
            result = [log for log in result if log.timestamp >= since]

        return result

    def get_errors(self) -> List[LogEntry]:
        """获取所有错误日志。"""
        return [log for log in self._logs if log.level in ("ERROR", "CRITICAL")]

    def has_error(self, pattern: str) -> bool:
        """检查是否存在匹配的错误日志。"""
        regex = re.compile(pattern, re.IGNORECASE)
        return any(
            log.level in ("ERROR", "CRITICAL") and regex.search(log.message)
            for log in self._logs
        )

    def has_message(self, pattern: str, min_level: str = "INFO") -> bool:
        """检查是否存在匹配的日志消息。"""
        regex = re.compile(pattern, re.IGNORECASE)
        min_priority = self.LEVEL_PRIORITY.get(min_level, 0)
        return any(
            self.LEVEL_PRIORITY.get(log.level, 0) >= min_priority
            and regex.search(log.message)
            for log in self._logs
        )

    def clear(self):
        """清空日志。"""
        self._logs.clear()

    def get_summary(self) -> dict:
        """获取日志摘要。"""
        levels = {"DEBUG": 0, "INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0}
        sources = {}

        for log in self._logs:
            levels[log.level] = levels.get(log.level, 0) + 1
            sources[log.source] = sources.get(log.source, 0) + 1

        return {
            "total": len(self._logs),
            "levels": levels,
            "top_sources": sorted(sources.items(), key=lambda x: x[1], reverse=True)[:5],
        }
