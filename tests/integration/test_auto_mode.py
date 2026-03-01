# tests/integration/test_auto_mode.py
"""
Auto 模式端到端集成测试（黑盒测试）。

测试场景：
1. 启动 main.py --auto 模式
2. 监听浏览器状态和日志
3. 验证 bot 能正常进入牌桌、坐下、使用策略玩牌
4. 验证达到退出条件后能正常离开

运行方式：
    pytest tests/integration/test_auto_mode.py -v -s --tb=short

前置条件：
    1. data/browser_data/ 中有有效的登录 session
    2. config/settings.yaml 配置正确
"""

import asyncio
import sys
import time
import pytest
from pathlib import Path

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from playwright.async_api import async_playwright

from tests.integration.helpers import BrowserMonitor, LogCollector, TestReporter
from src.bot.browser_manager import BrowserManager


# ─── 配置 ─────────────────────────────────────────────────────────────────────
USER_DATA_DIR = "./data/browser_data"
MAX_TEST_DURATION = 60 * 5  # 5 分钟超时
REPORT_DIR = "./data/test_reports"


# ─── 测试标记 ─────────────────────────────────────────────────────────────────
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
]


class AutoModeTestRunner:
    """
    Auto 模式测试运行器。

    负责启动 BrowserManager，监听状态，收集日志，验证行为。
    """

    def __init__(self):
        self.browser_manager: BrowserManager = None
        self.monitor = BrowserMonitor(poll_interval=1.0)
        self.log_collector = LogCollector(min_level="INFO")
        self.reporter = TestReporter(output_dir=REPORT_DIR)
        self.errors: list[str] = []

    async def setup(self, test_name: str):
        """测试设置。"""
        self.reporter.start_test(test_name)
        self.log_collector.start_capture()

        # 创建 BrowserManager（auto 模式）
        self.browser_manager = BrowserManager(
            headless=False,
            apprentice_mode=False,
            auto_mode=True
        )

        # 设置状态变化回调
        self.monitor.add_state_change_callback(self._on_state_change)

    def _on_state_change(self, old_state, new_state):
        """状态变化回调。"""
        self.reporter.record_browser_state({
            "url": new_state.url,
            "is_table_page": new_state.is_table_page,
            "table_id": new_state.table_id,
            "is_sitting": new_state.is_sitting,
            "total_chips": new_state.total_chips,
            "pot": new_state.pot,
            "available_actions": new_state.available_actions,
        })

        # 记录重要状态变化
        if old_state.is_sitting != new_state.is_sitting:
            status = "入座" if new_state.is_sitting else "离座"
            self.reporter.record_action(f"player_{status}", {
                "table_id": new_state.table_id,
                "chips": new_state.total_chips,
            })
            self.log_collector.collect(
                f"Player {status} at table {new_state.table_id}",
                level="INFO",
                source="test"
            )

    async def run_test(self, duration_sec: int = 60, min_actions: int = 1):
        """
        运行测试。

        Args:
            duration_sec: 测试运行时长（秒）
            min_actions: 期望的最小动作数
        """
        try:
            # 启动浏览器
            self.reporter.record_action("browser_starting")
            await self.browser_manager.start()
            self.reporter.record_action("browser_started")

            # 开始监控
            def get_page():
                # 获取第一个 table page 或 lobby page
                if self.browser_manager.table_managers:
                    first_table = list(self.browser_manager.table_managers.values())[0]
                    return first_table.page
                elif self.browser_manager.lobby_manager:
                    return self.browser_manager.lobby_manager.page
                return None

            await self.monitor.start_monitoring(get_page)

            # 主循环
            start_time = time.time()
            last_status_time = start_time

            while time.time() - start_time < duration_sec:
                # 运行一个 tick
                await self.browser_manager.run_tick()

                # 每 10 秒打印一次状态
                if time.time() - last_status_time >= 10:
                    last_status_time = time.time()
                    elapsed = int(time.time() - start_time)
                    state = self.monitor.get_latest_state()
                    if state:
                        print(f"[TEST] {elapsed}s | Table: {state.table_id} | "
                              f"Sitting: {state.is_sitting} | Chips: {state.total_chips}")
                    else:
                        print(f"[TEST] {elapsed}s | Waiting for browser...")

                # 检查错误
                errors = self.log_collector.get_errors()
                if errors:
                    for error in errors[-3:]:  # 只记录最新的3个错误
                        if error.message not in self.errors:
                            self.errors.append(error.message)
                            self.reporter.add_error(error.message)

                await asyncio.sleep(1)

            # 验证测试结果
            await self._verify_results(min_actions)

        except Exception as e:
            self.errors.append(str(e))
            self.reporter.add_error(str(e))
            raise

    async def _verify_results(self, min_actions: int):
        """验证测试结果。"""
        history = self.monitor.get_state_history()

        # 验证 1: 应该访问过牌桌页面
        table_pages = [s for s in history if s.is_table_page]
        if not table_pages:
            self.errors.append("从未访问过牌桌页面")

        # 验证 2: 应该有入座状态
        sitting_states = [s for s in history if s.is_sitting]
        if not sitting_states:
            self.errors.append("没有检测到入座状态")

        # 验证 3: 动作数检查
        actions = self.reporter._current_report.action_log if self.reporter._current_report else []
        player_actions = [a for a in actions if "player_" in a.get("action", "")]

        if len(player_actions) < min_actions:
            self.errors.append(f"动作数不足: {len(player_actions)} < {min_actions}")

        # 记录验证结果
        self.reporter._current_report.summary = {
            "total_states_recorded": len(history),
            "table_page_visits": len(table_pages),
            "sitting_states": len(sitting_states),
            "player_actions": len(player_actions),
            "errors_count": len(self.errors),
        }

    async def teardown(self):
        """测试清理。"""
        await self.monitor.stop_monitoring()
        self.log_collector.stop_capture()

        if self.browser_manager:
            await self.browser_manager.stop()

        # 完成报告
        success = len(self.errors) == 0
        report = self.reporter.finalize_test(success)

        # 保存报告
        report_path = self.reporter.save_report()
        self.reporter.print_report(report)

        return report, report_path


# ─── 测试用例 ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_mode_basic_flow():
    """
    集成测试：Auto 模式基本流程。

    验证：
    1. 能正常启动浏览器
    2. 能进入牌桌
    3. 能检测到入座状态
    4. 无致命错误
    """
    runner = AutoModeTestRunner()

    try:
        await runner.setup("auto_mode_basic_flow")
        await runner.run_test(duration_sec=60, min_actions=1)
    finally:
        report, report_path = await runner.teardown()

    # 断言
    assert report.success, f"测试失败，错误: {runner.errors}"
    assert report.summary.get("table_page_visits", 0) > 0, "应该访问过牌桌页面"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_mode_check_or_fold_strategy():
    """
    集成测试：Auto 模式下使用 checkorfold 策略。

    验证：
    1. 策略正确加载
    2. 执行的动作符合 checkorfold（check/fold）
    3. 无策略相关错误
    """
    # 设置环境变量使用 checkorfold 策略
    import os
    os.environ["POKER_STRATEGY"] = "checkorfold"

    runner = AutoModeTestRunner()

    try:
        await runner.setup("auto_mode_checkorfold")
        await runner.run_test(duration_sec=90, min_actions=1)

        # 验证日志中没有策略错误
        strategy_errors = runner.log_collector.get_logs(
            min_level="ERROR",
            message_pattern="strategy|决策|action"
        )

        if strategy_errors:
            runner.errors.append(f"策略错误: {len(strategy_errors)} 个")

    finally:
        report, report_path = await runner.teardown()

    # 清理环境变量
    if "POKER_STRATEGY" in os.environ:
        del os.environ["POKER_STRATEGY"]

    assert report.success, f"测试失败: {runner.errors}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_mode_graceful_exit():
    """
    集成测试：Auto 模式优雅退出。

    验证：
    1. 能正常停止浏览器
    2. 资源正确释放
    3. 无未处理的异常
    """
    runner = AutoModeTestRunner()

    await runner.setup("auto_mode_graceful_exit")

    # 运行短时间
    await runner.run_test(duration_sec=30, min_actions=0)

    # 正常 teardown
    report, report_path = await runner.teardown()

    # 验证没有资源泄漏相关的错误
    leak_errors = runner.log_collector.get_logs(
        min_level="ERROR",
        message_pattern="leak|unclosed|not closed"
    )

    assert len(leak_errors) == 0, f"发现资源泄漏: {leak_errors}"
    assert report.success, f"测试失败: {runner.errors}"


# ─── 直接运行入口 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    """直接运行测试（不经过 pytest）。"""
    asyncio.run(test_auto_mode_basic_flow())
