"""
tests/unit/bot/test_task_manager.py

测试 TaskManager 的纯逻辑部分（不需要浏览器）：
- 各种任务类型的完成判定 (_check_completion)
- 进度百分比计算 (get_progress)
- 止损触发逻辑
- 报告生成 (generate_report)
"""
import time
import pytest
from src.bot.task_manager import TaskManager, TaskConfig, TaskState, TaskType


def make_task(task_type: TaskType, target: int, stop_loss=None) -> TaskManager:
    """构造一个不需要浏览器的 TaskManager 实例。"""
    config = TaskConfig(
        task_type=task_type,
        target_value=target,
        strategy="range",
        stop_loss=stop_loss
    )
    return TaskManager(config)


class TestTaskCompletionProfit:
    """PROFIT_TARGET 类型的完成条件测试。"""

    def test_profit_not_reached_returns_false(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        tm.state.start_time = time.time()
        tm.state.total_profit = 1999
        assert tm._check_completion() is False

    def test_profit_exact_target_triggers(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        tm.state.start_time = time.time()
        tm.state.total_profit = 2000
        assert tm._check_completion() is True

    def test_profit_exceeds_target_triggers(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        tm.state.start_time = time.time()
        tm.state.total_profit = 3500
        assert tm._check_completion() is True

    def test_stop_loss_triggers_at_exact_value(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000, stop_loss=500)
        tm.state.start_time = time.time()
        tm.state.total_profit = -500
        assert tm._check_completion() is True

    def test_stop_loss_triggers_when_exceeded(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000, stop_loss=500)
        tm.state.start_time = time.time()
        tm.state.total_profit = -600
        assert tm._check_completion() is True

    def test_stop_loss_not_triggered_before_limit(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000, stop_loss=500)
        tm.state.start_time = time.time()
        tm.state.total_profit = -499
        assert tm._check_completion() is False

    def test_completion_reason_set_on_profit(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        tm.state.start_time = time.time()
        tm.state.total_profit = 2001
        tm._check_completion()
        assert "2001" in tm.state.completion_reason or "profit" in tm.state.completion_reason.lower()

    def test_completion_reason_set_on_stop_loss(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000, stop_loss=500)
        tm.state.start_time = time.time()
        tm.state.total_profit = -600
        tm._check_completion()
        assert tm.state.completion_reason is not None


class TestTaskCompletionCycles:
    """CYCLES 类型的完成条件测试。"""

    def test_cycles_not_reached(self):
        tm = make_task(TaskType.CYCLES, 5)
        tm.state.total_cycles = 4
        assert tm._check_completion() is False

    def test_cycles_exact_target_triggers(self):
        tm = make_task(TaskType.CYCLES, 5)
        tm.state.total_cycles = 5
        assert tm._check_completion() is True

    def test_cycles_exceeds_target_triggers(self):
        tm = make_task(TaskType.CYCLES, 5)
        tm.state.total_cycles = 10
        assert tm._check_completion() is True


class TestTaskCompletionHands:
    """HANDS 类型的完成条件测试。"""

    def test_hands_not_reached(self):
        tm = make_task(TaskType.HANDS, 100)
        tm.state.total_hands = 99
        assert tm._check_completion() is False

    def test_hands_exact_target_triggers(self):
        tm = make_task(TaskType.HANDS, 100)
        tm.state.total_hands = 100
        assert tm._check_completion() is True


class TestTaskCompletionInfinite:
    """INFINITE 类型永不完成。"""

    def test_infinite_never_completes(self):
        tm = make_task(TaskType.INFINITE, 0)
        tm.state.start_time = time.time()
        tm.state.total_profit = 99999
        tm.state.total_hands = 99999
        tm.state.total_cycles = 99999
        assert tm._check_completion() is False


class TestTaskCompletionDuration:
    """DURATION 类型的时间判定测试。"""

    def test_duration_not_reached(self):
        tm = make_task(TaskType.DURATION, 60)
        tm.state.start_time = time.time()  # 刚启动
        assert tm._check_completion() is False

    def test_duration_simulated_past_end(self):
        tm = make_task(TaskType.DURATION, 1)  # 1 分钟
        # 模拟 2 分钟前启动
        tm.state.start_time = time.time() - 120
        assert tm._check_completion() is True


class TestTaskGetProgress:
    """get_progress 的百分比计算。"""

    def test_profit_progress_percentage(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        tm.state.total_profit = 1000
        p = tm.get_progress()
        assert p["percentage"] == pytest.approx(50.0)

    def test_progress_capped_at_100(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        tm.state.total_profit = 5000
        p = tm.get_progress()
        assert p["percentage"] == pytest.approx(100.0)

    def test_progress_zero_when_no_profit(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        tm.state.total_profit = 0
        p = tm.get_progress()
        assert p["percentage"] == pytest.approx(0.0)

    def test_hands_progress(self):
        tm = make_task(TaskType.HANDS, 100)
        tm.state.total_hands = 25
        p = tm.get_progress()
        assert p["percentage"] == pytest.approx(25.0)
        assert p["current"] == 25

    def test_cycles_progress(self):
        tm = make_task(TaskType.CYCLES, 10)
        tm.state.total_cycles = 3
        p = tm.get_progress()
        assert p["current"] == 3

    def test_progress_task_type_label(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        p = tm.get_progress()
        assert p["task_type"] == "profit"


class TestTaskGenerateReport:
    """generate_report 的内容正确性测试。"""

    def test_report_contains_task_type(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        tm.state.start_time = time.time()
        tm.state.end_time = time.time()
        report = tm.generate_report()
        assert report["task"]["type"] == "profit"
        assert report["task"]["target"] == 2000
        assert report["task"]["strategy"] == "range"

    def test_report_statistics_reflect_state(self):
        tm = make_task(TaskType.PROFIT_TARGET, 2000)
        tm.state.start_time = time.time()
        tm.state.end_time = time.time()
        tm.state.total_hands = 42
        tm.state.total_profit = 500
        tm.state.total_buyin_added = 1000
        report = tm.generate_report()
        assert report["statistics"]["hands_played"] == 42
        assert report["statistics"]["total_profit"] == 500

    def test_report_save_creates_file(self, tmp_path):
        tm = make_task(TaskType.CYCLES, 5)
        tm.state.start_time = time.time()
        tm.state.end_time = time.time()
        path = tm.save_report(output_path=str(tmp_path))
        import os
        assert os.path.exists(path)
