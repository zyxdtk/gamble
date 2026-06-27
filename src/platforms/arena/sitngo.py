"""Sit & Go 单桌锦标赛

Sit & Go 特点：
- 固定人数（通常 2/6/9/10 人），满员即开
- 单桌（无需多桌平衡）
- 盲注升级
- 淘汰制 + 奖金分配
- 比 MTT 更快节奏

支持类型：
- Heads-Up (2人)
- 6-Max (6人)
- 9-Max (9人, 标准)
- 10-Max (10人)
"""

import time
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from .game import PlayerState
from .agent import ArenaAgent
from .blind_schedule import BlindSchedule, BlindLevel, create_turbo_schedule, create_standard_schedule
from .table import TournamentTable
from .mtt import MTTPlayerConfig, PrizePayout

arena_logger = logging.getLogger("arena")


# 预设 Sit & Go 类型
SNG_PRESETS = {
    "hu": {"name": "Heads-Up", "players": 2, "prize": {1: 0.66, 2: 0.34}},
    "6max": {"name": "6-Max", "players": 6, "prize": {1: 0.50, 2: 0.30, 3: 0.20}},
    "9max": {"name": "9-Max", "players": 9, "prize": {1: 0.40, 2: 0.25, 3: 0.18, 4: 0.10, 5: 0.07}},
    "10max": {"name": "10-Max", "players": 10, "prize": {1: 0.40, 2: 0.25, 3: 0.18, 4: 0.10, 5: 0.07}},
}

# 默认 HU 奖金
HU_PRIZE = PrizePayout({1: 0.66, 2: 0.34})


@dataclass
class SNGConfig:
    """Sit & Go 配置"""
    preset: str = "9max"                   # "hu", "6max", "9max", "10max"
    entry_fee: int = 50                    # 买入费
    starting_stack: int = 1500             # 起始筹码
    blind_schedule: str = "turbo"          # "standard", "turbo"
    custom_players: int = 0                # 自定义人数（覆盖 preset）
    custom_prize: Optional[PrizePayout] = None  # 自定义奖金结构

    @property
    def num_players(self) -> int:
        if self.custom_players > 0:
            return self.custom_players
        return SNG_PRESETS.get(self.preset, SNG_PRESETS["9max"])["players"]

    @property
    def prize_payout(self) -> PrizePayout:
        if self.custom_prize:
            return self.custom_prize
        if self.preset in SNG_PRESETS:
            return PrizePayout(SNG_PRESETS[self.preset]["prize"])
        return PrizePayout.default(self.num_players)


@dataclass
class SNGPlayerStats:
    """玩家 Sit & Go 统计"""
    player_id: str
    name: str
    strategy: str
    finish_pos: int = 0
    prize_won: int = 0
    total_hands: int = 0
    vpip: float = 0.0
    pfr: float = 0.0
    hands_won: int = 0
    busted_hand: int = 0
    final_stack: int = 0


@dataclass
class SNGReport:
    """Sit & Go 报告"""
    preset: str
    entries: int
    duration_sec: float
    prize_pool: int
    player_stats: List[SNGPlayerStats]
    total_hands: int


class SitAndGo:
    """Sit & Go 单桌锦标赛管理器"""

    def __init__(self, config: SNGConfig):
        self.config = config

        # 盲注表（Sit & Go 默认用 turbo）
        if config.blind_schedule == "standard":
            self.blind_schedule = create_standard_schedule()
        else:
            self.blind_schedule = create_turbo_schedule()

        # 奖金结构
        self.prize_payout = config.prize_payout

        # 玩家注册
        self.player_configs: List[MTTPlayerConfig] = []
        self.player_states: Dict[str, PlayerState] = {}
        self.player_agents: Dict[str, ArenaAgent] = {}
        self.player_stats: Dict[str, SNGPlayerStats] = {}

        # 单桌
        self.table: Optional[TournamentTable] = None

        # 锦标赛状态
        self.elimination_order: List[str] = []
        self._hand_idx = 0

    def register_players(self, configs: List[MTTPlayerConfig]):
        """注册参赛者"""
        strategies = ["gto", "range", "exploitative", "checkorfold", "aggressive"]

        for i, cfg in enumerate(configs):
            player_id = f"sng_p{i}"
            strategy_name = cfg.strategy
            if strategy_name == "mixed":
                strategy_name = strategies[i % len(strategies)]

            strategy = self._create_strategy(strategy_name)
            agent = ArenaAgent(seat_id=0, strategy=strategy, player_id=player_id,
                               pilot_mode=cfg.pilot_mode)
            agent.name = cfg.name

            ps = PlayerState(seat_id=0, name=cfg.name, stack=cfg.starting_stack)
            ps.player_id = player_id

            self.player_configs.append(cfg)
            self.player_states[player_id] = ps
            self.player_agents[player_id] = agent
            self.player_stats[player_id] = SNGPlayerStats(
                player_id=player_id,
                name=cfg.name,
                strategy=strategy_name,
            )

        arena_logger.info(f"SNG: 已注册 {len(configs)} 名参赛者")

    def initial_seating(self):
        """安排座位（单桌）"""
        num = self.config.num_players
        self.table = TournamentTable(table_id=0, max_seats=max(num, 9))

        for pid, ps in self.player_states.items():
            agent = self.player_agents[pid]
            self.table.sit_player(ps, agent)

        arena_logger.info(f"SNG: 座位分配完成, {self.table.player_count} 人")

    async def run(self) -> SNGReport:
        """运行完整 Sit & Go"""
        start_time = time.time()

        if not self.table:
            self.initial_seating()

        preset_name = SNG_PRESETS.get(self.config.preset, {}).get("name", self.config.preset)
        arena_logger.info("=" * 50)
        arena_logger.info(f"Sit & Go ({preset_name}) 开始! 参赛: {self.config.num_players} 人")
        arena_logger.info(f"买入: {self.config.entry_fee}, 起始筹码: {self.config.starting_stack}")
        arena_logger.info("=" * 50)

        self._hand_idx = 0
        last_blind_level = -1

        while True:
            remaining = self._count_remaining()
            if remaining <= 1:
                break

            # 移除淘汰玩家（stack==0）
            busted_seats = [s for s in range(self.table.max_seats)
                           if self.table.seats[s] is not None and self.table.seats[s].stack == 0]
            for seat_id in busted_seats:
                self.table.remove_player(seat_id)

            if self.table.player_count < 2:
                break

            # 盲注升级
            blind_level = self.blind_schedule.current_level(self._hand_idx + 1)
            level_idx = self.blind_schedule.level_index(self._hand_idx + 1)
            if level_idx != last_blind_level:
                arena_logger.info(f"--- 盲注升级至 Level {blind_level.level}: "
                                  f"SB={blind_level.sb} BB={blind_level.bb} Ante={blind_level.ante} ---")
                last_blind_level = level_idx

            # 打一手
            busted = await self.table.play_hand(blind_level)
            self._hand_idx += 1

            # 处理淘汰
            for pid, _ in busted:
                self._handle_bust(pid)

            # 更新统计
            self._update_stats()

            # 进度
            if self._hand_idx % 5 == 0:
                self._print_progress()

            # 安全上限
            if self._hand_idx > 3000:
                arena_logger.warning("超过 3000 手安全上限，强制结束")
                break

        # 设置最终排名
        self._finalize_rankings()

        duration = time.time() - start_time
        prize_pool = self.config.entry_fee * len(self.player_configs)

        report = SNGReport(
            preset=self.config.preset,
            entries=len(self.player_configs),
            duration_sec=duration,
            prize_pool=prize_pool,
            player_stats=sorted(self.player_stats.values(), key=lambda s: s.finish_pos),
            total_hands=self._hand_idx,
        )

        self._print_final_report(report)
        return report

    def _create_strategy(self, strategy_type: str):
        """创建策略实例"""
        from src.strategies.strategies.balanced import BalancedStrategy
        from src.strategies.strategies.exploitative import ExploitativeStrategy
        from src.strategies.strategies.range import RangeStrategy
        from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
        from src.strategies.strategies.aggressive import AggressiveStrategy

        strategy_type = strategy_type.lower()
        if strategy_type == "balanced":
            return BalancedStrategy(thinking_timeout=2.0)
        elif strategy_type in ("gto", "gto_solver"):
            from src.strategies.strategies.gto_solver import GtoSolverStrategy
            return GtoSolverStrategy()
        elif strategy_type == "exploitative":
            return ExploitativeStrategy(thinking_timeout=2.0)
        elif strategy_type == "neural":
            from src.strategies.strategies.neural import NeuralStrategy
            return NeuralStrategy(thinking_timeout=2.0)
        elif strategy_type == "checkorfold":
            return CheckOrFoldStrategy()
        elif strategy_type == "aggressive":
            return AggressiveStrategy(thinking_timeout=2.0)
        elif strategy_type == "icm":
            from src.strategies.strategies.icm import ICMStrategy
            return ICMStrategy(thinking_timeout=2.0)
        else:
            return RangeStrategy(thinking_timeout=2.0)

    def _count_remaining(self) -> int:
        return sum(1 for ps in self.player_states.values() if ps.stack > 0)

    def _handle_bust(self, player_id: str):
        if player_id in self.player_states and self.player_states[player_id].stack == 0:
            if player_id not in self.elimination_order:
                self.elimination_order.append(player_id)
            stats = self.player_stats.get(player_id)
            if stats and stats.busted_hand == 0:
                stats.busted_hand = self._hand_idx
                stats.final_stack = 0
            arena_logger.info(f"玩家 {self.player_states[player_id].name} 淘汰! "
                              f"(第 {len(self.elimination_order)} 名淘汰)")

    def _update_stats(self):
        for pid, stats in self.player_stats.items():
            ps = self.player_states.get(pid)
            if ps and ps.stack > 0:
                stats.total_hands += 1
                stats.final_stack = ps.stack

    def _finalize_rankings(self):
        total = len(self.player_configs)

        for i, pid in enumerate(self.elimination_order):
            finish_pos = total - i
            stats = self.player_stats.get(pid)
            if stats:
                stats.finish_pos = finish_pos

        eliminated_set = set(self.elimination_order)
        remaining = [pid for pid in self.player_states
                     if self.player_states[pid].stack > 0 and pid not in eliminated_set]
        if remaining:
            remaining.sort(key=lambda pid: self.player_states[pid].stack, reverse=True)
            for i, pid in enumerate(remaining):
                stats = self.player_stats.get(pid)
                if stats:
                    stats.finish_pos = i + 1
                    stats.final_stack = self.player_states[pid].stack

        for pid, stats in self.player_stats.items():
            if stats.finish_pos == 0:
                stats.finish_pos = total
                stats.final_stack = 0

        prize_pool = self.config.entry_fee * len(self.player_configs)
        for stats in self.player_stats.values():
            prize_pct = self.prize_payout.structure.get(stats.finish_pos, 0.0)
            stats.prize_won = int(prize_pool * prize_pct)

    def _print_progress(self):
        remaining = self._count_remaining()
        blind = self.blind_schedule.current_level(self._hand_idx + 1)
        arena_logger.info(
            f"[SNG] Hand #{self._hand_idx} | "
            f"剩余: {remaining} 人 | 盲注: {blind.sb}/{blind.bb}"
        )

    def _print_final_report(self, report: SNGReport):
        preset_name = SNG_PRESETS.get(self.config.preset, {}).get("name", self.config.preset)
        print("\n" + "=" * 60)
        print(f"  Sit & Go ({preset_name}) 完赛报告")
        print("-" * 60)
        print(f"  参赛: {report.entries} 人  |  奖池: {report.prize_pool}")
        print(f"  总手数: {report.total_hands}  |  耗时: {report.duration_sec:.1f}s")
        print("-" * 60)
        print(f"  {'名次':>4} | {'玩家':<16} | {'策略':<14} | {'奖金':>8} | {'淘汰手':>6}")
        print("-" * 60)

        for ps in report.player_stats:
            prize_str = f"{ps.prize_won}" if ps.prize_won > 0 else "-"
            busted_str = f"#{ps.busted_hand}" if ps.busted_hand > 0 else "冠军!"
            print(f"  {ps.finish_pos:>4} | {ps.name:<16} | {ps.strategy:<14} | {prize_str:>8} | {busted_str:>6}")

        print("=" * 60 + "\n")
