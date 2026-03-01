# tests/integration/helpers/test_reporter.py
"""
测试报告生成器。

用于生成集成测试的详细报告。
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from pathlib import Path


@dataclass
class TestReport:
    """测试报告数据结构。"""
    test_name: str
    start_time: float
    end_time: Optional[float] = None
    duration_sec: float = 0.0
    success: bool = False
    error_messages: List[str] = field(default_factory=list)
    browser_states: List[Dict[str, Any]] = field(default_factory=list)
    action_log: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def finalize(self, success: bool, errors: List[str] = None):
        """完成报告。"""
        self.end_time = time.time()
        self.duration_sec = round(self.end_time - self.start_time, 2)
        self.success = success
        if errors:
            self.error_messages.extend(errors)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return asdict(self)


class TestReporter:
    """
    测试报告生成器。

    收集测试过程中的各种数据，生成结构化报告。
    """

    def __init__(self, output_dir: str = "./data/test_reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._current_report: Optional[TestReport] = None

    def start_test(self, test_name: str) -> TestReport:
        """开始一个新的测试报告。"""
        self._current_report = TestReport(
            test_name=test_name,
            start_time=time.time(),
        )
        return self._current_report

    def record_action(self, action: str, details: Dict[str, Any] = None):
        """记录一个动作。"""
        if self._current_report:
            entry = {
                "timestamp": time.time(),
                "action": action,
                "details": details or {},
            }
            self._current_report.action_log.append(entry)

    def record_browser_state(self, state: Dict[str, Any]):
        """记录浏览器状态。"""
        if self._current_report:
            state_copy = {"timestamp": time.time(), **state}
            self._current_report.browser_states.append(state_copy)

    def add_error(self, error: str):
        """添加错误信息。"""
        if self._current_report:
            self._current_report.error_messages.append(error)

    def finalize_test(self, success: bool) -> TestReport:
        """完成当前测试。"""
        if not self._current_report:
            raise RuntimeError("No test is currently running")

        self._current_report.finalize(success)
        return self._current_report

    def save_report(self, report: TestReport = None) -> str:
        """
        保存报告到文件。

        Returns:
            保存的文件路径
        """
        report = report or self._current_report
        if not report:
            raise RuntimeError("No report to save")

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{report.test_name}_{timestamp}.json"
        filepath = self.output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

        return str(filepath)

    def generate_summary(self, reports: List[TestReport]) -> Dict[str, Any]:
        """生成多个测试的摘要。"""
        total = len(reports)
        passed = sum(1 for r in reports if r.success)
        failed = total - passed

        total_duration = sum(r.duration_sec for r in reports)

        return {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "success_rate": round(passed / total * 100, 2) if total > 0 else 0,
            "total_duration_sec": round(total_duration, 2),
            "test_results": [
                {
                    "name": r.test_name,
                    "success": r.success,
                    "duration_sec": r.duration_sec,
                    "errors": len(r.error_messages),
                }
                for r in reports
            ],
        }

    def print_report(self, report: TestReport):
        """打印报告到控制台。"""
        print("\n" + "=" * 60)
        print(f"  测试报告: {report.test_name}")
        print("=" * 60)
        print(f"  状态: {'✅ 通过' if report.success else '❌ 失败'}")
        print(f"  耗时: {report.duration_sec:.2f} 秒")
        print(f"  动作数: {len(report.action_log)}")
        print(f"  状态记录: {len(report.browser_states)}")

        if report.error_messages:
            print(f"\n  错误 ({len(report.error_messages)}):")
            for i, error in enumerate(report.error_messages[:5], 1):
                print(f"    {i}. {error}")
            if len(report.error_messages) > 5:
                print(f"    ... 还有 {len(report.error_messages) - 5} 个错误")

        print("=" * 60)
