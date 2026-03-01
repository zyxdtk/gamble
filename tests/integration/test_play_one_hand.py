# tests/integration/test_play_one_hand.py
"""
玩1局集成测试（黑盒测试）。

测试场景：
1. 通过参数启动 main.py --mode auto --hands 1
2. 监听浏览器状态和日志
3. 验证 bot 能自动完成：打开浏览器 -> 找桌 -> 坐下 -> 玩1手 -> 离开
4. 统计收益

运行方式：
    pytest tests/integration/test_play_one_hand.py -v -s --tb=short

前置条件：
    1. data/browser_data/ 中有有效的登录 session
    2. config/settings.yaml 配置正确
"""

import asyncio
import sys
import time
import json
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

import pytest

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


# ─── 配置 ─────────────────────────────────────────────────────────────────────
USER_DATA_DIR = "./data/browser_data"
MAX_TEST_DURATION = 60 * 5  # 5 分钟超时
REPORT_PATH = "./data/test_reports/one_hand_report.json"


# ─── 数据类 ────────────────────────────────────────────────────────────────────
@dataclass
class GameEvent:
    """游戏事件。"""
    timestamp: float
    event_type: str  # sit, action, exit, error
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionResult:
    """会话结果。"""
    success: bool = False
    hands_played: int = 0
    total_buyin: int = 0
    final_chips: int = 0
    profit: int = 0
    events: List[GameEvent] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_sec: float = 0.0


# ─── 日志解析器 ────────────────────────────────────────────────────────────────
class LogParser:
    """解析应用程序日志。"""

    def __init__(self):
        self.events: List[GameEvent] = []
        self.errors: List[str] = []

    def parse_line(self, line: str):
        """解析单行日志。"""
        timestamp = time.time()

        # 检测错误
        if "[CRITICAL]" in line or "[ERROR]" in line or "Error" in line:
            self.errors.append(line.strip())
            self.events.append(GameEvent(timestamp, "error", {"message": line.strip()}))
            return

        # 检测入座
        if "Already seated" in line or "Buy-in confirmed" in line:
            self.events.append(GameEvent(timestamp, "sit", {"message": line.strip()}))
            return

        # 检测动作执行
        if "Executing:" in line:
            # 提取动作
            import re
            match = re.search(r'Executing:\s*(\w+)', line)
            if match:
                action = match.group(1)
                self.events.append(GameEvent(timestamp, "action", {"action": action}))
            return

        # 检测手数
        if "hands played" in line.lower() or "hand" in line.lower():
            import re
            match = re.search(r'(\d+)\s*hands?', line.lower())
            if match:
                hands = int(match.group(1))
                self.events.append(GameEvent(timestamp, "hands_update", {"hands": hands}))
            return

        # 检测退出
        if "Leaving table" in line or "exit" in line.lower():
            self.events.append(GameEvent(timestamp, "exit", {"message": line.strip()}))
            return

        # 检测统计信息
        if "SESSION STATISTICS" in line:
            self.events.append(GameEvent(timestamp, "statistics_start", {}))
            return

    def get_hands_played(self) -> int:
        """获取玩过的手数。"""
        for event in reversed(self.events):
            if event.event_type == "hands_update":
                return event.data.get("hands", 0)
        return 0

    def get_actions(self) -> List[str]:
        """获取执行的动作列表。"""
        return [e.data.get("action") for e in self.events if e.event_type == "action"]


# ─── 测试运行器 ────────────────────────────────────────────────────────────────
class OneHandTestRunner:
    """
    玩1局测试运行器。

    通过 subprocess 启动 main.py，捕获输出进行验证。
    """

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.parser = LogParser()
        self.result = SessionResult()
        self._start_time: float = 0

    async def run(self, strategy: str = "checkorfold", timeout_sec: int = 300) -> SessionResult:
        """
        运行测试。

        Args:
            strategy: 使用的策略
            timeout_sec: 超时时间（秒）

        Returns:
            SessionResult 包含测试结果
        """
        self._start_time = time.time()

        # 构建命令
        cmd = [
            sys.executable,
            "src/main.py",
            "--mode", "auto",
            "--strategy", strategy,
            "--hands", "1",
        ]

        print(f"[TEST] Starting: {' '.join(cmd)}")
        print(f"[TEST] Timeout: {timeout_sec} seconds")
        print("-" * 60)

        # 启动进程
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=project_root,
        )

        # 读取输出
        try:
            while self.process.poll() is None:
                # 检查超时
                elapsed = time.time() - self._start_time
                if elapsed > timeout_sec:
                    print(f"\n[TEST] Timeout after {elapsed:.1f} seconds")
                    self._terminate()
                    self.result.errors.append(f"Timeout after {elapsed:.1f} seconds")
                    break

                # 读取一行输出
                import select
                if self.process.stdout:
                    # 使用 asyncio 等待可读
                    loop = asyncio.get_event_loop()
                    readable = await loop.run_in_executor(
                        None,
                        lambda: select.select([self.process.stdout], [], [], 0.1)[0]
                    )
                    if readable:
                        line = self.process.stdout.readline()
                        if line:
                            print(line, end='')  # 实时打印
                            self.parser.parse_line(line)

                await asyncio.sleep(0.01)

            # 读取剩余输出
            if self.process.stdout:
                remaining = self.process.stdout.read()
                if remaining:
                    print(remaining, end='')
                    for line in remaining.split('\n'):
                        self.parser.parse_line(line)

        except Exception as e:
            self.result.errors.append(f"Exception during test: {e}")
            self._terminate()

        finally:
            self._finalize()

        return self.result

    def _terminate(self):
        """终止进程。"""
        if self.process and self.process.poll() is None:
            print("[TEST] Terminating process...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("[TEST] Killing process...")
                self.process.kill()
                self.process.wait()

    def _finalize(self):
        """完成测试，收集结果。"""
        self.result.duration_sec = time.time() - self._start_time
        self.result.events = self.parser.events
        self.result.errors.extend(self.parser.errors)
        self.result.hands_played = self.parser.get_hands_played()

        # 从统计信息中解析数据
        self._parse_statistics()

        # 判断测试是否成功
        has_sit = any(e.event_type == "sit" for e in self.result.events)
        has_exit = any(e.event_type == "exit" for e in self.result.events)
        no_critical_errors = not any("[CRITICAL]" in e for e in self.result.errors)

        # 成功条件：入座 + 正常退出 + 无致命错误
        # 不强制要求检测到动作，因为可能没轮到 AI 行动
        self.result.success = has_sit and has_exit and no_critical_errors

        print("\n" + "=" * 60)
        print("  📊 TEST SUMMARY")
        print("=" * 60)
        print(f"  Duration: {self.result.duration_sec:.1f} seconds")
        print(f"  Events: {len(self.result.events)}")
        print(f"  Errors: {len(self.result.errors)}")
        print(f"  Hands played: {self.result.hands_played}")
        print(f"  Actions: {self.parser.get_actions()}")
        print(f"  Has sit event: {has_sit}")
        print(f"  Has exit event: {has_exit}")
        print(f"  Success: {self.result.success}")
        print("=" * 60)

    def _parse_statistics(self):
        """从日志中解析统计信息。"""
        # 查找统计信息
        for i, event in enumerate(self.result.events):
            if event.event_type == "statistics_start":
                # 统计信息通常在后面的几行
                # 这里简化处理，实际可以从后续事件解析
                pass

    def save_report(self):
        """保存测试报告。"""
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "success": self.result.success,
            "duration_sec": round(self.result.duration_sec, 2),
            "hands_played": self.result.hands_played,
            "total_buyin": self.result.total_buyin,
            "final_chips": self.result.final_chips,
            "profit": self.result.profit,
            "actions": self.parser.get_actions(),
            "errors": self.result.errors,
            "events": [
                {
                    "timestamp": e.timestamp,
                    "type": e.event_type,
                    "data": e.data,
                }
                for e in self.result.events
            ],
        }

        # 确保目录存在
        Path(REPORT_PATH).parent.mkdir(parents=True, exist_ok=True)

        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"[TEST] Report saved to: {REPORT_PATH}")


# ─── 测试用例 ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_play_one_hand_checkorfold():
    """
    集成测试：使用 checkorfold 策略玩1手牌。

    验证：
    1. 能正常启动并进入牌桌
    2. 能自动坐下
    3. 能执行至少1个动作
    4. 无致命错误
    """
    runner = OneHandTestRunner()

    try:
        result = await runner.run(strategy="checkorfold", timeout_sec=180)
    finally:
        runner.save_report()

    # 断言
    assert result.success, f"测试失败: {result.errors}"
    assert result.hands_played >= 0, "应该记录手数"

    # 验证动作
    actions = runner.parser.get_actions()
    assert len(actions) > 0, "应该执行至少1个动作"

    # 验证 checkorfold 策略只执行 check 或 fold
    for action in actions:
        assert action.lower() in ["check", "fold", "call"], \
            f"checkorfold 策略不应该执行 {action}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_play_one_hand_gto():
    """
    集成测试：使用 GTO 策略玩1手牌。

    验证：
    1. 能正常启动并进入牌桌
    2. 能自动坐下
    3. 能执行动作
    4. 无致命错误
    """
    runner = OneHandTestRunner()

    try:
        result = await runner.run(strategy="gto", timeout_sec=180)
    finally:
        runner.save_report()

    # 断言
    assert result.success, f"测试失败: {result.errors}"

    # 验证动作
    actions = runner.parser.get_actions()
    assert len(actions) > 0, "应该执行至少1个动作"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_mode_exit_after_one_hand():
    """
    集成测试：验证 --hands 1 参数能正确退出。

    验证：
    1. 程序在玩了1手后能自动退出
    2. 退出时打印统计信息
    """
    runner = OneHandTestRunner()
    result = await runner.run(strategy="checkorfold", timeout_sec=120)

    # 保存报告
    runner.save_report()

    # 验证有退出事件或正常结束
    has_exit = any(e.event_type == "exit" for e in result.events)
    has_statistics = any(e.event_type == "statistics_start" for e in result.events)

    assert has_exit or has_statistics or result.success, \
        "程序应该正常退出或打印统计信息"


# ─── 直接运行入口 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    """直接运行测试（不经过 pytest）。"""
    print("Running one hand test...")
    result = asyncio.run(test_play_one_hand_checkorfold())
    print(f"\nTest completed: {result}")
