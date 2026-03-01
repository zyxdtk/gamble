"""
tests/integration/test_profit_target.py

盈利目标集成测试（使用 TaskManager + 剥削策略）。

测试场景：
1. 使用 TaskManager 创建盈利 1000 筹码的任务
2. 使用剥削策略（exploitative）根据对手类型调整打法
3. 验证 bot 能自动完成：打开浏览器 -> 找桌 -> 坐下 -> 玩到盈利1000或止损 -> 离开
4. 统计收益

运行方式：
    pytest tests/integration/test_profit_target.py -v -s --tb=short

前置条件：
    1. data/browser_data/ 中有有效的登录 session
    2. config/settings.yaml 配置正确
"""

import asyncio
import sys
import time
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

import pytest

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.bot.task_manager import TaskManager, TaskConfig, TaskType  # noqa: E402


# ─── 配置 ─────────────────────────────────────────────────────────────────────
USER_DATA_DIR = "./data/browser_data"
MAX_TEST_DURATION = 60 * 30  # 30 分钟超时（盈利目标可能需要较长时间）
REPORT_PATH = "./data/test_reports/profit_target_report.json"
TARGET_PROFIT = 1000  # 目标盈利 1000 筹码
STOP_LOSS = 500  # 止损 500 筹码


# ─── 数据类 ────────────────────────────────────────────────────────────────────
@dataclass
class GameEvent:
    """游戏事件。"""
    timestamp: float
    event_type: str  # sit, action, profit, exit, error
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    """测试结果。"""
    success: bool = False
    hands_played: int = 0
    total_buyin: int = 0
    final_chips: int = 0
    profit: int = 0
    dealer_cycles: int = 0
    tables_played: int = 0
    events: List[GameEvent] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_sec: float = 0.0
    task_state: Optional[Dict] = None
    reached_target: bool = False  # 是否达到盈利目标
    stop_loss_triggered: bool = False  # 是否触发止损


# ─── 测试运行器 ────────────────────────────────────────────────────────────────
class ProfitTargetTest:
    """盈利目标测试运行器（使用 TaskManager）。"""

    def __init__(self, target_profit: int = TARGET_PROFIT, stop_loss: int = STOP_LOSS):
        self.target_profit = target_profit
        self.stop_loss = stop_loss
        self.result = TestResult()
        self._start_time: float = 0
        self._task_mgr: Optional[TaskManager] = None
        self._events: List[GameEvent] = []
        self._last_profit = 0

    def _on_progress(self, task_state):
        """进度回调。"""
        timestamp = time.time()

        # 记录盈利变化
        if task_state.total_profit != self._last_profit:
            self._events.append(GameEvent(
                timestamp,
                "profit",
                {"profit": task_state.total_profit, "buyin": task_state.total_buyin}
            ))
            print(f"[TEST] Profit update: {task_state.total_profit:+d} (buyin: {task_state.total_buyin})")
            self._last_profit = task_state.total_profit

    def _on_table_changed(self, old_table, new_table):
        """桌子切换回调。"""
        timestamp = time.time()
        self._events.append(GameEvent(
            timestamp,
            "table_change",
            {"old": old_table, "new": new_table}
        ))
        if new_table:
            print(f"[TEST] Table changed to: {new_table}")

    async def run(self, timeout_sec: int = MAX_TEST_DURATION) -> TestResult:
        """
        运行测试。

        Args:
            timeout_sec: 超时时间（秒）

        Returns:
            TestResult 包含测试结果
        """
        self._start_time = time.time()

        # 创建任务配置 - 盈利目标模式（使用剥削策略）
        config = TaskConfig(
            task_type=TaskType.PROFIT_TARGET,
            target_value=self.target_profit,
            strategy="exploitative",
            stop_loss=self.stop_loss
        )

        print(f"[TEST] Starting Profit Target Test (Exploitative Strategy)")
        print(f"[TEST] Target profit: {self.target_profit} chips")
        print(f"[TEST] Stop loss: {self.stop_loss} chips")
        print(f"[TEST] Timeout: {timeout_sec} seconds")
        print("-" * 60)

        # 创建 TaskManager
        self._task_mgr = TaskManager(config)
        self._task_mgr.on_progress_update = self._on_progress
        self._task_mgr.on_table_changed = self._on_table_changed

        try:
            # 初始化
            await self._task_mgr.initialize(headless=False)

            # 运行任务（带超时）
            await asyncio.wait_for(
                self._task_mgr.run(),
                timeout=timeout_sec
            )

        except asyncio.TimeoutError:
            print(f"[TEST] Timeout after {time.time() - self._start_time:.1f} seconds")
            self.result.errors.append("Test timeout")
        except Exception as e:
            print(f"[TEST] Exception: {e}")
            self.result.errors.append(str(e))
            import traceback
            traceback.print_exc()
        finally:
            if self._task_mgr:
                await self._task_mgr.stop()
            self._finalize()

        return self.result

    def _finalize(self):
        """完成测试，收集结果。"""
        self.result.duration_sec = time.time() - self._start_time
        self.result.events = self._events

        if self._task_mgr:
            state = self._task_mgr.state
            self.result.hands_played = state.total_hands
            self.result.dealer_cycles = state.total_cycles
            self.result.total_buyin = state.total_buyin
            self.result.profit = state.total_profit
            self.result.tables_played = state.total_tables
            self.result.task_state = state.to_dict()

            # 计算最终筹码
            self.result.final_chips = self.result.total_buyin + self.result.profit

            # 判断是否达到盈利目标或触发止损
            self.result.reached_target = self.result.profit >= self.target_profit
            self.result.stop_loss_triggered = self.result.profit <= -self.stop_loss

        # 判断测试是否成功
        no_critical_errors = len(self.result.errors) == 0
        has_buyin = self.result.total_buyin > 0
        reached_target_or_stop = self.result.reached_target or self.result.stop_loss_triggered

        # 成功条件：有买入记录 + 无致命错误 + 达到目标或触发止损
        self.result.success = has_buyin and no_critical_errors and reached_target_or_stop

        print("\n" + "=" * 60)
        print("  📊 TEST SUMMARY")
        print("=" * 60)
        print(f"  Duration: {self.result.duration_sec:.1f} seconds")
        print(f"  Events: {len(self.result.events)}")
        print(f"  Errors: {len(self.result.errors)}")
        print(f"  Tables played: {self.result.tables_played}")
        print(f"  Hands played: {self.result.hands_played}")
        print(f"  Dealer cycles: {self.result.dealer_cycles}")
        print(f"  Total buyin: {self.result.total_buyin}")
        print(f"  Final chips: {self.result.final_chips}")
        print(f"  Profit: {self.result.profit:+d}")
        print(f"  Target profit: {self.target_profit}")
        print(f"  Reached target: {self.result.reached_target}")
        print(f"  Stop loss triggered: {self.result.stop_loss_triggered}")
        print(f"  Success: {self.result.success}")
        print("=" * 60)

    def save_report(self):
        """保存测试报告。"""
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "success": self.result.success,
            "duration_sec": round(self.result.duration_sec, 2),
            "tables_played": self.result.tables_played,
            "hands_played": self.result.hands_played,
            "dealer_cycles": self.result.dealer_cycles,
            "total_buyin": self.result.total_buyin,
            "final_chips": self.result.final_chips,
            "profit": self.result.profit,
            "target_profit": self.target_profit,
            "stop_loss": self.stop_loss,
            "reached_target": self.result.reached_target,
            "stop_loss_triggered": self.result.stop_loss_triggered,
            "errors": self.result.errors,
            "events": [
                {
                    "timestamp": e.timestamp,
                    "type": e.event_type,
                    "data": e.data,
                }
                for e in self.result.events
            ],
            "task_state": self.result.task_state,
        }

        # 确保目录存在
        Path(REPORT_PATH).parent.mkdir(parents=True, exist_ok=True)

        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"[TEST] Report saved to: {REPORT_PATH}")


# ─── 测试用例 ──────────────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.timeout(1800)  # 30 分钟超时
async def test_profit_target_1000():
    """
    盈利目标 1000 筹码集成测试（剥削策略）。

    验证：
    1. 能自动找到牌桌并入座
    2. 使用剥削策略根据对手类型调整打法
    3. 玩到盈利 1000 筹码或触发止损
    4. 正确统计买入和收益
    """
    test = ProfitTargetTest(target_profit=1000, stop_loss=500)
    result = await test.run(timeout_sec=MAX_TEST_DURATION)
    test.save_report()

    # 断言
    assert result.success, f"测试失败: {result.errors}"
    assert result.total_buyin > 0, "应该有买入记录"
    # 要么达到盈利目标，要么触发止损
    assert result.reached_target or result.stop_loss_triggered, \
        f"应该达到盈利目标({result.target_profit})或触发止损({result.stop_loss})，实际盈亏: {result.profit}"

    print(f"\n✅ Profit Target Test 通过！")
    print(f"   目标盈利: {result.target_profit}")
    print(f"   实际盈亏: {result.profit:+d}")
    print(f"   是否达到目标: {result.reached_target}")
    print(f"   是否触发止损: {result.stop_loss_triggered}")


if __name__ == "__main__":
    asyncio.run(test_profit_target_1000())
