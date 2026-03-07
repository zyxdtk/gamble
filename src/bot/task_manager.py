"""
TaskManager - 顶层任务控制器

负责任务的创建、执行和监控。
BrowserManager、LobbyManager、TableManager 都是 TaskManager 的工具。

支持的任务类型：
- 跑 N 圈 (cycles)
- 赚 N 筹码 (profit_target)
- 玩 N 手牌 (hands)
- 运行 N 分钟 (duration)
"""

import asyncio
import time
from typing import Optional, Callable
from dataclasses import dataclass
from enum import Enum


class TaskType(Enum):
    CYCLES = "cycles"           # 完成指定圈数
    PROFIT_TARGET = "profit"    # 达到指定盈利目标
    HANDS = "hands"             # 玩指定手牌数
    DURATION = "duration"       # 运行指定时长
    INFINITE = "infinite"       # 无限运行（直到手动停止）


@dataclass
class TaskConfig:
    """任务配置"""
    task_type: TaskType = TaskType.INFINITE
    target_value: int = 0           # 目标值（圈数/筹码/手牌数/分钟）
    strategy: str = "gto"           # 使用的策略
    stop_loss: Optional[int] = None  # 止损金额（可选）
    
    # 桌子选择偏好
    preferred_stakes: str = "1/2"
    min_players: int = 2
    max_players: int = 9
    
    # 并发桌子数量
    max_concurrent_tables: int = 1


@dataclass
class TaskState:
    """任务执行状态"""
    is_running: bool = False
    is_completed: bool = False
    start_time: float = 0.0
    end_time: Optional[float] = None
    
    # 累计统计
    total_tables: int = 0
    total_hands: int = 0
    total_cycles: int = 0
    total_buyin_added: int = 0
    total_profit: int = 0
    
    # 当前桌子状态
    current_table_id: Optional[str] = None
    current_table_start_time: Optional[float] = None
    
    # 任务结果
    completion_reason: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "is_running": self.is_running,
            "is_completed": self.is_completed,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.end_time - self.start_time if self.end_time else time.time() - self.start_time,
            "total_tables": self.total_tables,
            "total_hands": self.total_hands,
            "total_cycles": self.total_cycles,
            "total_buyin_added": self.total_buyin_added,
            "total_profit": self.total_profit,
            "current_table_id": self.current_table_id,
            "completion_reason": self.completion_reason,
        }


class TaskManager:
    """
    任务管理器 - 顶层控制器
    
    职责：
    1. 管理任务生命周期（创建、执行、完成）
    2. 协调 BrowserManager、LobbyManager、TableManager
    3. 监控任务进度，决定是否继续或停止
    4. 处理桌子切换（当一个桌子退出后，找新桌子继续）
    """
    
    def __init__(self, config: TaskConfig):
        self.config = config
        self.state = TaskState()
        
        # 工具（由外部注入或创建）
        self.browser_mgr = None
        self.lobby_mgr = None
        
        # 回调
        self.on_table_changed: Optional[Callable[[Optional[str], Optional[str]], None]] = None
        self.on_progress_update: Optional[Callable[[TaskState], None]] = None
        
        # 运行控制
        self._stop_requested = False
        self._tick_interval = 1.0  # 秒
        
    async def initialize(self, headless: bool = False):
        """初始化工具"""
        from .browser_manager import BrowserManager
        
        print("[TASK] Initializing task manager...")
        print(f"[TASK] Type: {self.config.task_type.value}, Target: {self.config.target_value}")
        print(f"[TASK] Strategy: {self.config.strategy}")
        
        # 尽早设置策略环境变量
        import os
        os.environ["POKER_STRATEGY"] = self.config.strategy
        
        # 根据任务类型设置单桌限制环境变量
        if self.config.task_type == TaskType.CYCLES:
            os.environ["POKER_MAX_CYCLES"] = str(self.config.target_value)
        elif self.config.task_type == TaskType.HANDS:
            os.environ["POKER_MAX_HANDS"] = str(self.config.target_value)
        elif self.config.task_type == TaskType.INFINITE:
            # 无限模式下，给一个较大的单桌上限（或者不设限）
            os.environ["POKER_MAX_CYCLES"] = "100" 
        
        # 创建并启动 BrowserManager
        self.browser_mgr = BrowserManager(
            headless=headless,
            auto_mode=True,
            apprentice_mode=False
        )
        
        await self.browser_mgr.start()
        
        print("[TASK] Browser manager started successfully.")
        
    async def run(self):
        """运行任务主循环"""
        self.state.is_running = True
        self.state.start_time = time.time()
        
        print(f"\n{'='*50}")
        print(f"🚀 TASK STARTED: {self.config.task_type.value}")
        print(f"   Target: {self.config.target_value}")
        print(f"   Strategy: {self.config.strategy}")
        print(f"{'='*50}\n")
        
        try:
            while not self._stop_requested:
                # 检查任务是否完成
                if self._check_completion():
                    break
                
                # 执行一个 tick
                should_continue = await self._execute_tick()
                if not should_continue:
                    # 没有可用桌子，结束任务
                    break
                
                # 更新状态
                self._update_state()
                
                # 触发进度回调
                if self.on_progress_update is not None:
                    self.on_progress_update(self.state)
                
                await asyncio.sleep(self._tick_interval)
                
        except asyncio.CancelledError:
            print("[TASK] Task cancelled.")
        except Exception as e:
            print(f"[TASK] Error in task loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self._complete_task("stopped" if self._stop_requested else "completed")
            
    async def _execute_tick(self) -> bool:
        """执行一个 tick - 驱动 BrowserManager
        
        Returns:
            True 如果继续运行，False 如果没有可用桌子应该结束任务
        """
        if not self.browser_mgr:
            return True
            
        # 让 BrowserManager 执行它的 tick
        # 这会处理桌子管理、游戏逻辑等
        result = await self.browser_mgr.run_tick()
        
        # 如果 run_tick 返回 False，表示没有可用桌子
        if result is False:
            print("[TASK] No more available tables. Ending task.")
            self.state.completion_reason = "No available tables"
            return False
            
        return True
        
    def _update_state(self):
        """从 BrowserManager 更新任务状态"""
        if not self.browser_mgr:
            return
            
        # 获取统计信息
        stats = self.browser_mgr.get_statistics()
        
        # 更新累计数据
        self.state.total_hands = stats.get("total_hands_played", 0)
        self.state.total_cycles = stats.get("total_cycles_completed", 0)
        self.state.total_buyin_added = stats.get("total_buyin_added", 0)
        self.state.total_profit = stats.get("total_profit", 0)
        self.state.total_tables = stats.get("tables_played", 0)
        
        # 检查当前桌子是否变化
        current_tables = list(self.browser_mgr.table_managers.keys())
        new_table_id = current_tables[0] if current_tables else None
        
        if new_table_id != self.state.current_table_id:
            old_table = self.state.current_table_id
            self.state.current_table_id = new_table_id
            self.state.current_table_start_time = time.time() if new_table_id else None
            
            if self.on_table_changed is not None:
                self.on_table_changed(old_table, new_table_id)
                
            if new_table_id:
                print(f"[TASK] Switched to table: {new_table_id}")
                
    def _check_completion(self) -> bool:
        """检查任务是否完成"""
        if self.config.task_type == TaskType.INFINITE:
            return False
            
        if self.config.task_type == TaskType.CYCLES:
            if self.state.total_cycles >= self.config.target_value:
                self.state.completion_reason = f"Reached {self.config.target_value} cycles"
                return True
                
        elif self.config.task_type == TaskType.HANDS:
            if self.state.total_hands >= self.config.target_value:
                self.state.completion_reason = f"Reached {self.config.target_value} hands"
                return True
                
        elif self.config.task_type == TaskType.DURATION:
            elapsed_min = (time.time() - self.state.start_time) / 60
            if elapsed_min >= self.config.target_value:
                self.state.completion_reason = f"Reached {self.config.target_value} minutes"
                return True
                
        elif self.config.task_type == TaskType.PROFIT_TARGET:
            if self.state.total_profit >= self.config.target_value:
                self.state.completion_reason = f"Reached profit target: +{self.state.total_profit}"
                return True
            # 检查止损
            if self.config.stop_loss and self.state.total_profit <= -self.config.stop_loss:
                self.state.completion_reason = f"Stop loss triggered: {self.state.total_profit}"
                return True
                
        return False
        
    async def _complete_task(self, reason: str):
        """完成任务"""
        self.state.is_running = False
        self.state.is_completed = True
        self.state.end_time = time.time()

        if not self.state.completion_reason:
            self.state.completion_reason = reason

        print(f"\n{'='*50}")
        print(f"✅ TASK COMPLETED: {self.state.completion_reason}")
        print(f"{'='*50}")
        self._print_statistics()

        # 保存任务报告
        try:
            self.save_report()
        except Exception as e:
            print(f"[TASK] Failed to save report: {e}")
        
    def _print_statistics(self):
        """打印统计信息"""
        stats = self.state.to_dict()
        print("\n  📊 TASK STATISTICS")
        print("-" * 50)
        print(f"  Duration: {stats['duration_seconds']:.1f} seconds")
        print(f"  Tables played: {stats['total_tables']}")
        print(f"  Hands played: {stats['total_hands']}")
        print(f"  Cycles completed: {stats['total_cycles']}")
        print(f"  Total buyin: {stats['total_buyin_added']}")
        print(f"  Total profit: {stats['total_profit']}")
        print("-" * 50)

    def generate_report(self) -> dict:
        """
        生成任务报告。

        Returns:
            包含任务执行结果的字典
        """
        stats = self.state.to_dict()

        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "task": {
                "type": self.config.task_type.value,
                "target": self.config.target_value,
                "strategy": self.config.strategy,
            },
            "result": {
                "success": self.state.is_completed,
                "completion_reason": self.state.completion_reason,
                "duration_seconds": round(stats['duration_seconds'], 2),
            },
            "statistics": {
                "tables_played": stats['total_tables'],
                "hands_played": stats['total_hands'],
                "cycles_completed": stats['total_cycles'],
                "total_buyin_added": stats['total_buyin_added'],
                "total_profit": stats['total_profit'],
                "final_chips": stats['total_buyin_added'] + stats['total_profit'],
            },
        }

        return report

    def save_report(self, output_path: str = "./data/task_reports") -> str:
        """
        保存任务报告到文件。

        Args:
            output_path: 报告输出目录

        Returns:
            保存的文件路径
        """
        import json
        from pathlib import Path

        report = self.generate_report()

        # 确保目录存在
        report_dir = Path(output_path)
        report_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        task_type = self.config.task_type.value
        filename = f"task_report_{task_type}_{timestamp}.json"
        filepath = report_dir / filename

        # 保存报告
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"[TASK] Report saved to: {filepath}")
        return str(filepath)
        
    async def stop(self):
        """停止任务"""
        print("[TASK] Stop requested.")
        self._stop_requested = True
        
        if self.browser_mgr:
            await self.browser_mgr.stop()
            
    def request_stop(self):
        """请求停止（异步安全）"""
        self._stop_requested = True
        
    def get_progress(self) -> dict:
        """获取当前进度"""
        progress = {
            "task_type": self.config.task_type.value,
            "target": self.config.target_value,
            "current": 0,
            "percentage": 0.0,
            "is_running": self.state.is_running,
        }
        
        if self.config.task_type == TaskType.CYCLES:
            progress["current"] = self.state.total_cycles
        elif self.config.task_type == TaskType.HANDS:
            progress["current"] = self.state.total_hands
        elif self.config.task_type == TaskType.DURATION:
            progress["current"] = (time.time() - self.state.start_time) / 60
        elif self.config.task_type == TaskType.PROFIT_TARGET:
            progress["current"] = self.state.total_profit
            
        if self.config.target_value > 0:
            progress["percentage"] = min(100.0, (progress["current"] / self.config.target_value) * 100)
            
        return progress
