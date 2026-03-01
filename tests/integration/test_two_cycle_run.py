"""
tests/bot/test_two_cycle_run.py

集成测试：加入牌桌，使用 CheckOrFold 策略，稳定运行两个庄家位周期。

运行方式：
    pytest tests/bot/test_two_cycle_run.py -m integration -v -s

前提条件：
    1. data/browser_data/ 中有有效的登录 session
    2. 无其他 Chrome 实例占用 data/browser_data/

一个"周期"的定义：
    庄家位从初始位置出发，经过所有其他座位，再回到初始位置。
    6人桌 ≈ 6 手。两个周期 ≈ 12 手。

测试通过条件：
    - 无未捕获异常（bot 稳定运行）
    - dealer_cycle_count >= 2
    - 所有已执行动作均为合法 CheckOrFold 动作（fold/check/call）
    - 没有在手牌中途崩溃
"""

import asyncio
import json
import os
import time
import pytest
from playwright.async_api import async_playwright

from src.bot.table_manager import TableManager
from src.bot.lobby_manager import LobbyManager

# ─── 配置 ─────────────────────────────────────────────────────────────────────
USER_DATA_DIR    = "./data/browser_data"
TARGET_CYCLES    = 2        # 目标庄家圈数
TICK_INTERVAL    = 2.0      # 每次 tick 间隔（秒）
MAX_WAIT_SECONDS = 60 * 30  # 最长等待时间（30 分钟）
REPORT_PATH      = "./data/two_cycle_report.json"


# ─── 测试标记 ─────────────────────────────────────────────────────────────────
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
]


# ─── 辅助：记录器 ─────────────────────────────────────────────────────────────
class RunRecorder:
    """记录本次运行的所有关键事件，用于断言和报告。"""

    def __init__(self):
        self.start_time     = time.time()
        self.actions        : list[dict] = []   # 每次执行的动作
        self.dealer_changes : list[int]  = []   # 庄家位变化历史
        self.errors         : list[str]  = []   # 捕获到的错误
        self.hands_played   = 0
        self.cycles_done    = 0

    def record_action(self, action: str, pot: int, to_call: int):
        self.actions.append({
            "time": round(time.time() - self.start_time, 1),
            "action": action,
            "pot": pot,
            "to_call": to_call,
        })

    def record_dealer_change(self, seat: int):
        self.dealer_changes.append(seat)

    def record_error(self, msg: str):
        self.errors.append(msg)

    def save_report(self):
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        report = {
            "duration_sec"  : round(time.time() - self.start_time, 1),
            "hands_played"  : self.hands_played,
            "cycles_done"   : self.cycles_done,
            "total_actions" : len(self.actions),
            "errors"        : self.errors,
            "dealer_path"   : self.dealer_changes,
            "actions"       : self.actions,
        }
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return report


# ─── 子类化 TableManager，注入记录器 ──────────────────────────────────────────
class MonitoredTableManager(TableManager):
    """在 TableManager 基础上注入 RunRecorder，追踪庄家位变化和动作执行。"""

    def __init__(self, page, strategy_type: str, recorder: RunRecorder):
        super().__init__(page, strategy_type)
        self.recorder = recorder

    async def update_dealer_cycle(self):
        prev_cycles = self.dealer_cycle_count
        prev_dealer = self._last_dealer_seat
        await super().update_dealer_cycle()

        if self._last_dealer_seat is not None and self._last_dealer_seat != prev_dealer:
            self.recorder.record_dealer_change(self._last_dealer_seat)
            self.recorder.hands_played = self.hands_played

        if self.dealer_cycle_count > prev_cycles:
            self.recorder.cycles_done = self.dealer_cycle_count
            print(f"\n{'='*50}", flush=True)
            print(f"  ✅ 已完成 {self.dealer_cycle_count} 圈！累计 {self.hands_played} 手", flush=True)
            print(f"{'='*50}\n", flush=True)

    async def perform_click(self, action_text: str):
        result = await super().perform_click(action_text)
        self.recorder.record_action(
            action=action_text,
            pot=self.state.pot,
            to_call=self.state.to_call,
        )
        return result


# ─── 集成测试 ─────────────────────────────────────────────────────────────────
async def run_two_cycle_test() -> RunRecorder:
    """
    核心测试逻辑（独立 async 函数，方便调试时直接 asyncio.run）：
    1. 启动浏览器（复用已登录 session）
    2. 进入大厅，找一张有空位的桌
    3. 等待用户坐下（或自动坐下）
    4. 运行直到完成 TARGET_CYCLES 个庄家位周期
    5. 保存报告
    """
    recorder  = RunRecorder()
    strategy_type = "checkorfold"

    async with async_playwright() as p:
        # 1. 启动浏览器（复用登录 session）
        print("\n[TEST] 启动浏览器...", flush=True)
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )

        # 2. 初始化大厅
        lobby_page = context.pages[0] if context.pages else await context.new_page()
        lobby_mgr  = LobbyManager(lobby_page)

        # 3. 找有空位的桌
        print("[TEST] 正在查找可用牌桌...", flush=True)
        table_url = None
        if "/lobby" not in lobby_page.url:
            await lobby_mgr.navigate_to_lobby()
        table_url = await lobby_mgr.get_best_table_url()

        if not table_url:
            recorder.record_error("找不到可用牌桌，终止测试")
            recorder.save_report()
            await context.close()
            return recorder

        # 4. 进入牌桌
        print(f"[TEST] 找到牌桌: {table_url}", flush=True)
        success = await lobby_mgr.open_table(table_url)
        if not success:
            recorder.record_error(f"无法进入牌桌 {table_url}")
            recorder.save_report()
            await context.close()
            return recorder

        # 等待新 tab 打开
        await asyncio.sleep(4)
        table_page = None
        for pg in context.pages:
            if "/table/" in pg.url:
                table_page = pg
                break

        if not table_page:
            recorder.record_error("未检测到牌桌 tab")
            recorder.save_report()
            await context.close()
            return recorder

        # 5. 创建受监控的 TableManager
        print(f"[TEST] 牌桌已打开: {table_page.url}", flush=True)
        mgr = MonitoredTableManager(table_page, strategy_type, recorder)
        await mgr.initialize()

        # 6. 主循环：运行直到完成 TARGET_CYCLES 圈或超时
        deadline    = time.time() + MAX_WAIT_SECONDS
        last_status = time.time()

        print(f"[TEST] 开始运行，目标: {TARGET_CYCLES} 圈庄家位周期...", flush=True)
        print("[TEST] 如未自动入座，请手动坐下并买入筹码。\n", flush=True)

        while time.time() < deadline:
            try:
                await mgr.execute_turn()
            except Exception as e:
                recorder.record_error(f"execute_turn error: {e}")
                print(f"[TEST] ⚠️  tick 错误: {e}", flush=True)

            # 检查是否完成目标圈数
            if mgr.dealer_cycle_count >= TARGET_CYCLES:
                print(f"\n[TEST] 🎉 目标达成！{TARGET_CYCLES} 圈完成！", flush=True)
                break

            # 每 30 秒打印一次状态
            if time.time() - last_status >= 30:
                last_status = time.time()
                elapsed = int(time.time() - recorder.start_time)
                print(
                    f"[TEST] 状态: {elapsed}s 已用，"
                    f"庄家圈 {mgr.dealer_cycle_count}/{TARGET_CYCLES}，"
                    f"手数 {mgr.hands_played}，"
                    f"动作 {len(recorder.actions)} 次",
                    flush=True,
                )

            # 如果牌桌已关闭，退出
            if mgr.is_closed or mgr.exit_requested:
                recorder.record_error("牌桌提前关闭")
                break

            await asyncio.sleep(TICK_INTERVAL)

        # 7. 离桌（如果还在座）
        if not mgr.is_closed:
            print("[TEST] 正在离桌...", flush=True)
            await mgr.leave_table()

        await context.close()

    # 8. 保存并返回报告
    report = recorder.save_report()
    print(f"\n{'='*55}", flush=True)
    print(f"  测试报告已保存: {REPORT_PATH}", flush=True)
    print(f"  共玩: {report['hands_played']} 手  |  完成圈数: {report['cycles_done']}", flush=True)
    print(f"  执行动作: {report['total_actions']} 次", flush=True)
    print(f"  错误: {len(report['errors'])} 个", flush=True)
    print(f"  庄家路径: {report['dealer_path']}", flush=True)
    print(f"{'='*55}\n", flush=True)

    return recorder


@pytest.mark.integration
@pytest.mark.asyncio
async def test_checkorfold_two_dealer_cycles():
    """
    集成测试：CheckOrFold 策略稳定运行两个庄家位周期。

    断言：
    1. 无崩溃（no unhandled exceptions）
    2. 庄家圈数达到 TARGET_CYCLES (2)
    3. 所有已执行动作均为合法 CheckOrFold 行为
    4. 记录到庄家位变化（至少看到 2 个不同的庄家位）
    """
    recorder = await run_two_cycle_test()
    report   = recorder.save_report()

    # ── 断言 1：完成两圈 ────────────────────────────────────────────────
    assert report["cycles_done"] >= TARGET_CYCLES, (
        f"未完成 {TARGET_CYCLES} 圈庄家周期，"
        f"实际完成 {report['cycles_done']} 圈，"
        f"共 {report['hands_played']} 手"
    )

    # ── 断言 2：无致命错误 ───────────────────────────────────────────────
    fatal_errors = [e for e in report["errors"] if "execute_turn" in e]
    assert len(fatal_errors) == 0, (
        f"运行期间出现 {len(fatal_errors)} 个 tick 错误: {fatal_errors}"
    )

    # ── 断言 3：动作均合法 ───────────────────────────────────────────────
    LEGAL_ACTIONS = {"fold", "check", "call", "check/call"}
    illegal = [
        a for a in report["actions"]
        if not any(legal in a["action"].lower() for legal in LEGAL_ACTIONS)
    ]
    assert len(illegal) == 0, (
        f"CheckOrFold 策略执行了非法动作: {illegal}"
    )

    # ── 断言 4：庄家位有移动 ─────────────────────────────────────────────
    assert len(set(report["dealer_path"])) >= 2, (
        f"庄家位没有移动，路径: {report['dealer_path']}"
    )

    print(f"\n✅ 集成测试通过！两圈完成，共 {report['hands_played']} 手，"
          f"执行 {report['total_actions']} 次动作。")


# ─── 直接调试入口 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    """
    直接运行（不经过 pytest）：
        python tests/bot/test_two_cycle_run.py
    """
    asyncio.run(run_two_cycle_test())
